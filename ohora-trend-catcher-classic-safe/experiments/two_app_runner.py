#!/usr/bin/env python3
"""Manual two-or-more-authorized-app OHORA Business Discovery collection.

Preview by default: no credentials read, no Meta calls, no file writes.
Live preflight verifies separate credential files before sending requests.
Each app has a stable, non-overlapping account range of --capacity rows.
There is intentionally NO scheduler or automatic retry.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys

import full_batch_collector as collector

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "experiments" / "results" / "dual_app_latest10"
APP_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,29}\Z")


def parse_apps(entries: list[str]) -> list[tuple[str, Path]]:
    if not entries:
        raise ValueError("Specify at least two --app NAME=LOCAL_ENV_PATH entries")
    apps: list[tuple[str, Path]] = []
    names: set[str] = set()
    paths: set[Path] = set()
    for raw in entries:
        if "=" not in raw:
            raise ValueError("--app needs NAME=LOCAL_ENV_PATH")
        name, pathstr = raw.split("=", 1)
        if not APP_NAME.fullmatch(name) or not pathstr.strip():
            raise ValueError("Invalid --app NAME=LOCAL_ENV_PATH (alphanumeric safe names)")
        p = Path(pathstr).expanduser().resolve()
        if name.casefold() in names or p in paths:
            raise ValueError("Each app name and credential file must be unique")
        names.add(name.casefold())
        paths.add(p)
        apps.append((name, p))
    return apps


def plan_accounts(source: list[dict], apps: list[tuple[str, Path]],
                  capacity: int) -> list[tuple[str, Path, int, int, int]]:
    if capacity < 1 or capacity > 1000:
        raise ValueError("--capacity must be 1..1000 (150 is project default, not a Meta quota)")
    if len(source) > capacity * len(apps):
        raise ValueError(
            f"{len(source)} accounts exceed {capacity} x {len(apps)} slots. "
            f"Add another authorized --app for accounts "
            f"{capacity * len(apps) + 1}..{len(source)}, or explicitly revise the allocation.")
    return [
        (name, path, index * capacity + 1,
         (index + 1) * capacity,
         max(0, min(capacity, len(source) - index * capacity)))
        for index, (name, path) in enumerate(apps)
        if index * capacity < len(source)
    ]


def preflight_credentials(plan: list[tuple[str, Path, int, int, int]]) -> None:
    """Reject missing or accidentally duplicated credentials before ANY Meta call.

    Different tokens do not in themselves prove different Meta app identities or
    independent quota. META_APP_ID is optional, but if present in every file,
    distinct IDs are required. No token, hash or credential is ever printed.
    """
    tokens: set[str] = set()
    ids: set[str] = set()
    app_id_present = 0
    for name, path, *_ in plan:
        if not path.is_file():
            raise ValueError(f"Credential file missing for app '{name}'")
        # Require actual local file keys rather than environment fallback.
        local: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                local[key.strip()] = val.strip().strip(chr(39) + chr(34))
        token = local.get("META_ACCESS_TOKEN", "")
        caller = local.get("META_IG_USER_ID", "")
        version = local.get("META_GRAPH_VERSION", "v26.0")
        app_id = local.get("META_APP_ID", "")
        if not token or not caller.isdecimal() or not re.fullmatch(r"v\d+\.\d+", version):
            raise ValueError(f"Invalid local Meta credentials for '{name}': check required env keys")
        # Keep fingerprints only transiently in memory; never expose tokens.
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        if fingerprint in tokens:
            raise ValueError("Two app configuration files use the same Meta access token")
        tokens.add(fingerprint)
        if app_id:
            if not app_id.isdecimal():
                raise ValueError(f"Invalid META_APP_ID for '{name}'")
            if app_id in ids:
                raise ValueError("Two configured Meta apps claim the same META_APP_ID")
            ids.add(app_id)
            app_id_present += 1
    if app_id_present not in (0, len(plan)):
        raise ValueError("META_APP_ID must either be set in every app file or in none")
    if app_id_present == 0:
        print("WARNING: META_APP_ID not supplied. Different tokens may still share "
              "Meta user/business quota; independent limits are NOT verified.")
    else:
        print("Distinct declared app IDs found. Token-to-app identity and independent "
              "Meta quota still require verification in Meta Developer dashboard.")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--app", action="append", required=True, metavar="NAME=ENVFILE",
                        help="repeat per Meta app in ordinal allocation order")
    parser.add_argument("--capacity", type=int, default=150,
                        help="project-managed maximum target accounts per app (default 150)")
    parser.add_argument("--posts", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--stop-usage", type=float, default=70.0)
    parser.add_argument("--max-batches-per-app", type=int, default=None,
                        help="guarded pilot: limit batches per app, then resume later")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only-app", type=str, default=None,
                        help="Run one named authorized app only, keeping original immutable range")
    parser.add_argument("--live", action="store_true", help="authorize real Meta requests")
    args = parser.parse_args(argv)
    try:
        if not (1 <= args.posts <= 20 and 1 <= args.batch_size <= 10):
            raise ValueError("Posts must be 1..20 and batch-size 1..10")
        if (not 0 < args.stop_usage <= 100 or args.delay_seconds < 0 or
                (args.max_batches_per_app is not None and args.max_batches_per_app < 1)):
            raise ValueError("Invalid stop-usage, delay or max-batches")
        apps = parse_apps(args.app)
        if len(apps) < 2:
            raise ValueError("Configure at least two approved Meta apps for dual-app runner")
        source, sha = collector.load_source(args.source)
        plan = plan_accounts(source, apps, args.capacity)
        if args.output_dir.resolve() == ROOT.resolve() or (
                args.output_dir.resolve().is_relative_to((ROOT / "kq3_294_collection").resolve())):
            raise ValueError("Refusing to write into source repository or legacy collection")
        print(f"Account source: {len(source)} official/append-only targets. "
              f"posts={args.posts}, batch={args.batch_size}, project capacity={args.capacity}.")
        for name, path, first, last, total in plan:
            print(f"  {name}: official rows {first}..{min(last, len(source))} "
                  f"({total} accounts), <= {(total + args.batch_size-1)//args.batch_size} outer batches; "
                  f"output={args.output_dir / name}")
        if args.only_app is not None and args.only_app not in {name for name, *_ in plan}:
            raise ValueError("--only-app must match an active configured app name")
        if not args.live:
            print("DRY RUN ONLY: no credential reads, API requests or file writes. "
                  "Run with --live only after verifying app credentials and quota.")
            return 0
        # All configurations are validated first, even for a single-app run.
        # This prevents accidental use of duplicate tokens or declared IDs.
        preflight_credentials(plan)
        for name, path, first, last, total in plan:
            if args.only_app is not None and name != args.only_app:
                continue
            print(f"START {name}: assigned rows {first}..{min(last,len(source))} "
                  f"(max {args.posts} posts each), safely resumable", flush=True)
            opts = ["--source", str(args.source), "--env-file", str(path),
                    "--output-dir", str(args.output_dir / name),
                    "--posts", str(args.posts), "--batch-size", str(args.batch_size),
                    "--delay-seconds", str(args.delay_seconds),
                    "--stop-usage", str(args.stop_usage),
                    "--start-ordinal", str(first), "--end-ordinal", str(last),
                    "--assigned-app", name, "--require-usage", "--live"]
            if args.max_batches_per_app:
                opts += ["--max-batches", str(args.max_batches_per_app)]
            result = collector.main(opts)
            if result not in (0, 1):
                print(f"STOP: app {name} returned {result} (limit/transport/validation). "
                      "Other apps not started automatically; review status before resuming.")
                return result
            if result == 1:
                print(f"NOTICE: app {name} has failed/partial/pending targets within its range. "
                      "Already saved successful rows; continuing to next authorized app.")
        print("Finished this manual run. No scheduled retries. "
              "Check each app's summary.json and collection_status.csv.")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        # Do not print raw exception content from API libraries or env values.
        print("Two-app collector stopped: " + str(exc)[:220] if not args.live
              else "Two-app collector stopped. Check configuration/range and output paths; "
                   "no credentials are printed.", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
