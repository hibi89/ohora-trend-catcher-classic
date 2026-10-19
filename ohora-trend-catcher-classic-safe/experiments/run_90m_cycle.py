#!/usr/bin/env python3
"""One-shot two-app OHORA 90-minute cycle orchestrator.

This is NOT a daemon or activated schedule. An external trusted scheduler may
call this script every 90 minutes AFTER the separate Meta credentials,
business-hour window and consent are configured and tested.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

import full_batch_collector as base
import rolling_backfill as backfill

KST = timezone(timedelta(hours=9))  # Korea Standard Time has no DST


def now_kst():
    return datetime.now(KST)


def resolve(config_path: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("Schedule config requires explicit local source/env/output paths")
    p = Path(value).expanduser()
    return (p if p.is_absolute() else config_path.parent / p).resolve()


def read_local_config(path: Path):
    if not path.is_file():
        raise ValueError("Missing local schedule config; copy and edit the example")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Schedule configuration must be JSON object")
    return data


def eligible_business_window(config: dict, instant: datetime) -> bool:
    window = config.get("business_hours_kst") or {}
    start, end = window.get("start"), window.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("Specify business_hours_kst start and end before scheduling")
    if not re.fullmatch(r"\d{2}:\d{2}", start) or not re.fullmatch(r"\d{2}:\d{2}", end):
        raise ValueError("Business hours must use HH:MM")
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    if max(h1,h2) > 23 or max(m1,m2) > 59:
        raise ValueError("Invalid business-hour clock")
    minutes = instant.hour * 60 + instant.minute
    first = h1*60+m1
    last = h2*60+m2
    if last <= first:
        raise ValueError("Overnight or empty business window is not supported")
    weekdays = config.get("weekdays", [])
    if not isinstance(weekdays, list) or not weekdays or any(
        not isinstance(d,int) or isinstance(d,bool) or d not in range(7)
        for d in weekdays
    ):
        raise ValueError("Set explicit weekdays as integers 0..6")
    # Reserve enough room to finish two bounded 30-minute app runs.
    return instant.weekday() in weekdays and first <= minutes and minutes + 60 <= last


def verify_pair(config_path: Path, config: dict):
    apps = config.get("apps")
    if not isinstance(apps, dict) or set(apps) != {"A","B"}:
        raise ValueError("Exactly apps A and B must be configured")
    if config.get("cycle_minutes") != 90:
        raise ValueError("Cycle cadence must be 90 minutes")
    if not config.get("separate_authorized_apps_confirmed", False):
        raise ValueError("Separate authorized Meta apps must be confirmed before live scheduling")
    paths = {}
    metadata = {}
    for app in ("A", "B"):
        slot = apps[app]
        if not isinstance(slot,dict) or slot.get("enabled") is not True:
            raise ValueError(f"App {app} remains disabled")
        env_path = resolve(config_path, slot.get("env_file"))
        out_path = resolve(config_path, slot.get("output_dir"))
        if not env_path.is_file():
            raise ValueError(f"App {app} local token/ID file is not ready")
        values = base.load_env(env_path)
        token = values.get("META_ACCESS_TOKEN","")
        ig = values.get("META_IG_USER_ID","")
        app_id = values.get("META_APP_ID","")
        if not token or not ig.isdigit() or not app_id.isdigit():
            raise ValueError(f"App {app} requires token, META_IG_USER_ID and META_APP_ID")
        paths[app] = (env_path, out_path)
        metadata[app] = (token, ig, app_id)
    if (paths["A"][0] == paths["B"][0] or paths["A"][1] == paths["B"][1]
            or metadata["A"][0] == metadata["B"][0]
            or metadata["A"][2] == metadata["B"][2]):
        raise ValueError("Separate app slots must use different files, outputs, tokens and App IDs")
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_file = args.config.expanduser().resolve()
        config = read_local_config(config_file)
        if not args.live:
            print("PREVIEW ONLY: 90-minute two-app cursor-backfill cycle; no API calls or writes")
            print("Requested: app A rows 1..150; app B rows 151..294; "
                  "5 posts per account per cycle, 50 unique posts target")
            print(f"Schedule enabled: {config.get('schedule_enabled') is True}")
            return 0
        if config.get("schedule_enabled") is not True:
            print("SKIPPED: schedule_enabled=false; no API calls")
            return 0
        if not eligible_business_window(config, now_kst()):
            print("SKIPPED: outside configured business days/hours or less than 60 minutes left")
            return 0
        pairs = verify_pair(config_file, config)
        source = resolve(config_file, config.get("source"))
        if not source.is_file():
            raise ValueError("Official source account file not found")
        if source in {pairs["A"][1] / "collection.sqlite", pairs["B"][1] / "collection.sqlite"}:
            raise ValueError("Source and output paths overlap")
        for app in ("A", "B"):
            env_path, out = pairs[app]
            print(f"APP {app} start: range {backfill.RANGES[app]}, 5 posts/account")
            flags = ["--app", app, "--source", str(source),
                     "--env-file", str(env_path), "--output-dir", str(out),
                     "--batch-size", "10", "--stop-usage", "70",
                     "--max-minutes", "30", "--interval-minutes", "90", "--live"]
            ret = backfill.main(flags)
            if ret != 0:
                print(f"App {app} stopped at configuration or local error; no forced retry")
                return ret
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Schedule not run ({type(exc).__name__}): check local nonsecret config",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
