#!/usr/bin/env python3
"""Isolated, opt-in Meta Graph batch probe. Never mutates production collection CSVs.

A dry run is the default. --live sends exactly ONE batch HTTP POST of 1..10
Business Discovery sub-requests (and NEVER retries). Output is a minimal
statistics JSON with no access tokens, source captions, post IDs or media URLs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "account_list.csv"
DEFAULT_ENV = REPO / "kq3_294_collection" / ".env.local"
DEFAULT_OUTPUT = REPO / "experiments" / "results"
FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count,media_url,thumbnail_url,"
    "children.limit(50){id,media_type,media_url,thumbnail_url}"
)


def load_env(path: Path) -> dict[str, str]:
    values = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values.setdefault(key.strip(), val.strip().strip('"\''))
    return values


def accounts_for_keys(path: Path, keys: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 294 or not all(
        {"account_key", "username", "country"}.issubset(r) for r in rows
    ):
        raise ValueError("Official account_list.csv must contain 294 accounts and the required columns")
    by_key = {r["account_key"]: r for r in rows}
    if len(by_key) != 294 or len(set(keys)) != len(keys):
        raise ValueError("Duplicate account keys in source or selected keys")
    if not 1 <= len(keys) <= 10:
        raise ValueError("Probe is limited to 1–10 accounts per execution")
    if any(k not in by_key for k in keys):
        raise ValueError("Unknown account key (check official account_list.csv)")
    return [by_key[k] for k in keys]


def build_operations(accounts: list[dict[str, str]], ig_id: str, posts: int) -> list[dict[str, str]]:
    result = []
    for account in accounts:
        username = account["username"].strip().removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            raise ValueError("Invalid Instagram username in official CSV")
        fields = (
            f"business_discovery.username({username})"
            f"{{id,username,followers_count,media_count,media.limit({posts}){{{FIELDS}}}}}"
        )
        result.append({
            "method": "GET",
            "relative_url": f"{ig_id}?{urlencode({'fields': fields})}",
        })
    return result


def parse_usage_header(value: str | None) -> dict[str, int | float]:
    if not value:
        return {}
    try:
        raw = json.loads(value)
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in {
        "call_count", "total_time", "total_cputime"
    } and isinstance(v, (int, float)) and not isinstance(v, bool)}


def stats_for_result(code: int, body: object, account: dict[str, str]) -> dict:
    row = {"account_key": account["account_key"], "country": account["country"],
           "http_code": code, "meta_error_code": None, "posts": 0, "images": 0,
           "videos": 0, "carousels": 0, "carousel_children": 0, "image_urls": 0,
           "video_thumbnails": 0, "likes_missing": 0, "comments_missing": 0}
    if not isinstance(body, dict):
        row["meta_error_code"] = "invalid_json"
        return row
    if code != 200 or isinstance(body.get("error"), dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        row["meta_error_code"] = err.get("code", "unknown")
        return row
    discovery = body.get("business_discovery")
    if not isinstance(discovery, dict):
        row["meta_error_code"] = "missing_business_discovery"
        return row
    media = discovery.get("media") or {}
    posts = media.get("data", []) if isinstance(media, dict) else []
    if not isinstance(posts, list):
        row["meta_error_code"] = "invalid_media"
        return row
    row["posts"] = len(posts)
    for post in posts:
        if not isinstance(post, dict):
            continue
        t = post.get("media_type")
        row["likes_missing"] += post.get("like_count") is None
        row["comments_missing"] += post.get("comments_count") is None
        if t == "IMAGE":
            row["images"] += 1
            row["image_urls"] += bool(post.get("media_url"))
        elif t == "VIDEO":
            row["videos"] += 1
            row["video_thumbnails"] += bool(post.get("thumbnail_url"))
        elif t == "CAROUSEL_ALBUM":
            row["carousels"] += 1
            childset = post.get("children") or {}
            children = childset.get("data", []) if isinstance(childset, dict) else []
            if isinstance(children, list):
                row["carousel_children"] += len(children)
                row["image_urls"] += sum(
                    bool(c.get("media_url")) for c in children
                    if isinstance(c, dict) and c.get("media_type") == "IMAGE"
                )
    return row


def summarize(response: object, accounts: list[dict[str, str]], outer_code: int,
              outer_headers: object, elapsed: float, limit: int) -> dict:
    outer_usage = parse_usage_header(outer_headers.get("X-App-Usage"))
    out = {"measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "batch_http_code": outer_code, "batch_wall_seconds": round(elapsed, 3),
           "subrequests": len(accounts), "posts_requested_per_account": limit,
           "outer_app_usage": outer_usage, "inner_app_usage": [], "accounts": []}
    if isinstance(response, list) and len(response) == len(accounts):
        for entry, account in zip(response, accounts):
            code = entry.get("code", 0) if isinstance(entry, dict) else 0
            try:
                body = json.loads(entry.get("body") or "{}") if isinstance(entry, dict) else {}
            except (ValueError, TypeError):
                body = {}
            headers = entry.get("headers", []) if isinstance(entry, dict) else []
            if isinstance(headers, list):
                for h in headers:
                    if isinstance(h, dict) and str(h.get("name", "")).lower() == "x-app-usage":
                        out["inner_app_usage"].append(parse_usage_header(h.get("value")))
            out["accounts"].append(stats_for_result(code, body, account))
    else:
        out["response_error"] = "Unexpected batch response format or subresponse count"
    out["successful_accounts"] = sum(r["http_code"] == 200 and
                                     r["meta_error_code"] is None for r in out["accounts"])
    out["rate_limited"] = outer_code in (429, 403) or any(
        r["meta_error_code"] in (4, 17, 32, 613) for r in out["accounts"]
    )
    return out


def execute_once(version: str, token: str, operations: list[dict], timeout: int = 90) -> tuple[int, object, object, float]:
    # Official Graph Batch uses a top-level fallback access token. Keep it in the
    # HTTPS POST *body*, never in URL, console output, JSON reports, or Git history.
    form = urlencode({"access_token": token, "batch": json.dumps(operations),
                      "include_headers": "true"}).encode("utf-8")
    req = Request(f"https://graph.facebook.com/{version}", data=form, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded",
                           "Accept": "application/json"})
    start = time.monotonic()
    try:
        with urlopen(req, timeout=timeout) as rsp:
            raw = rsp.read()
            return rsp.status, json.loads(raw), rsp.headers, time.monotonic()-start
    except HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}  # Do not print potentially sensitive upstream payloads.
        return e.code, parsed, e.headers, time.monotonic()-start


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--keys", nargs="+", default=["KR_001"])
    p.add_argument("--posts", type=int, default=10)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--live", action="store_true", help="Authorize exactly ONE Meta batch API call")
    args = p.parse_args(argv)
    try:
        if not 1 <= args.posts <= 20:
            raise ValueError("--posts must be between 1 and 20")
        accounts = accounts_for_keys(args.source, args.keys)
        if not args.live:
            print(f"DRY RUN: one batch, {len(accounts)} subrequest(s), "
                  f"{args.posts} recent posts each; keys={','.join(args.keys)}")
            print("No Meta API request sent; no local data files modified.")
            return 0
        cfg = load_env(args.env_file)
        token = cfg.get("META_ACCESS_TOKEN", "").strip()
        ig_id = cfg.get("META_IG_USER_ID", "").strip()
        version = cfg.get("META_GRAPH_VERSION", "v26.0").strip()
        if not token or not re.fullmatch(r"[0-9]+", ig_id):
            raise ValueError("META_ACCESS_TOKEN/META_IG_USER_ID not configured")
        if not re.fullmatch(r"v\d+\.\d+", version):
            raise ValueError("Invalid META_GRAPH_VERSION")
        ops = build_operations(accounts, ig_id, args.posts)
        print(f"Sending ONE Meta batch containing {len(ops)} subrequest(s); no retries.")
        code, body, headers, elapsed = execute_once(version, token, ops)
        report = summarize(body, accounts, code, headers, elapsed, args.posts)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        target = args.output_dir / ("meta_batch_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
        with target.open("x", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("Local statistics report:", target)
        if report["rate_limited"]:
            print("RATE LIMITED: stop; do not run further batches.", file=sys.stderr)
            return 4
        return 0 if report["successful_accounts"] == len(accounts) else 2
    except (ValueError, OSError, URLError, TimeoutError) as e:
        # Deliberately do not print exceptions from HTTP libraries containing form/token.
        print(f"Probe stopped ({type(e).__name__}). Check local paths or connectivity.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
