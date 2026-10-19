#!/usr/bin/env python3
"""Safe, independent 5-post cursor backfill per authorized Meta app.

Dry-run by default. Each actual --live invocation takes at most ONE next page
per account; persisted cursor enables 5 -> 10 -> ... -> 50 distinct posts.
No automatic scheduling or retries: use an external scheduler only after
validating cursor support and independent Meta app credentials.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode

import full_batch_collector as base

TAKE = 5
TARGET = 50
RANGES = {"A": (1, 150), "B": (151, 294)}
COLS = {"posts", "media"}


def cursor_operation(account: dict, caller: str, after: str | None) -> dict:
    if after is not None and not re.fullmatch(r"[A-Za-z0-9_=+/-]{1,4096}", after):
        raise ValueError("Invalid or unsupported Meta pagination cursor")
    media_edge = f"media.limit({TAKE})"
    if after:
        media_edge += f".after({after})"
    fields = (f'business_discovery.username({account["username"]})'
              f'{{id,username,followers_count,media_count,'
              f'{media_edge}{{{base.MEDIA_FIELDS}}}}}')
    return {"method": "GET", "relative_url": f"{caller}?{urlencode({'fields': fields})}"}


def init_backfill(conn: sqlite3.Connection, accounts: list[dict]) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS backfill_state(
        account_key TEXT PRIMARY KEY, next_cursor TEXT,
        last_cycle TEXT, pages_fetched INTEGER NOT NULL DEFAULT 0,
        exhausted INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
        last_error_code TEXT, last_error TEXT, last_updated TEXT
    );
    CREATE TABLE IF NOT EXISTS backfill_runs(
        cycle TEXT PRIMARY KEY, started_utc TEXT NOT NULL,
        finished_utc TEXT, pages_requested INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'started'
    );
    """)
    with conn:
        conn.executemany("INSERT OR IGNORE INTO backfill_state(account_key) VALUES (?)",
                         [(a["account_key"],) for a in accounts])


def now() -> datetime:
    return datetime.now(timezone.utc)


def cycle_id(at: datetime, minutes: int = 90) -> str:
    return str(int(at.timestamp()) // (minutes * 60))


def select_pages(conn: sqlite3.Connection, first: int, last: int, cycle: str,
                 limit: int, target: int = TARGET) -> list[dict]:
    result = conn.execute("""
        SELECT a.ordinal,a.account_key,a.username,a.country,a.image_url,
               s.next_cursor,s.last_cycle,
               (SELECT COUNT(*) FROM posts p WHERE p.account_key=a.account_key) AS saved
        FROM accounts a JOIN backfill_state s ON s.account_key=a.account_key
        WHERE a.ordinal BETWEEN ? AND ? AND s.exhausted=0 AND s.blocked=0
          AND (s.last_cycle IS NULL OR s.last_cycle <> ?)
        ORDER BY s.pages_fetched ASC, a.ordinal
        """, (first, last, cycle)).fetchall()
    return [dict(r) for r in result if r["saved"] < target][:limit]


def parse_page(response: dict, account: dict, previous: str | None):
    discovery = response.get("business_discovery")
    if not isinstance(discovery, dict):
        raise ValueError("Missing business_discovery")
    media = discovery.get("media")
    if not isinstance(media, dict) or not isinstance(media.get("data"), list):
        raise ValueError("Missing media.data")
    posts = media["data"]
    if len(posts) > TAKE:
        raise ValueError("Meta returned more than requested 5 posts")
    info, decoded_posts, decoded_media = base.decode_success(response, account)
    paging = media.get("paging") or {}
    cursors = paging.get("cursors") or {} if isinstance(paging, dict) else {}
    after = cursors.get("after") if isinstance(cursors, dict) else None
    if after is not None and (not isinstance(after, str)
                              or not re.fullmatch(r"[A-Za-z0-9_=+/-]{1,4096}", after)):
        raise ValueError("Invalid next cursor format")
    if after and previous == after:
        raise ValueError("Meta returned unchanged pagination cursor")
    # A missing cursor on a full page, when the account has more media,
    # is ambiguous: do NOT silently mark 50-post coverage complete.
    media_total = info.get("media_count")
    uncertain = not after and len(posts) == TAKE and media_total is not None and media_total > TAKE
    exhausted = len(posts) < TAKE or (not after and not uncertain)
    return info, decoded_posts, decoded_media, after, exhausted, uncertain


def save_page(conn: sqlite3.Connection, account: dict, cycle: str, page: tuple,
              target: int = TARGET) -> tuple[int, int, str]:
    info, posts, media, after, exhausted, uncertain = page
    key = account["account_key"]
    with conn:
        old = conn.execute("SELECT COUNT(*) FROM posts WHERE account_key=?", (key,)).fetchone()[0]
        # Keep every existing post; never delete/replace earlier cycles.
        for row in posts:
            conn.execute("INSERT OR IGNORE INTO posts (" + ",".join(row) + ") VALUES (" +
                         ",".join("?" for _ in row) + ")", list(row.values()))
        for row in media:
            conn.execute("INSERT OR IGNORE INTO media (" + ",".join(row) + ") VALUES (" +
                         ",".join("?" for _ in row) + ")", list(row.values()))
        new = conn.execute("SELECT COUNT(*) FROM posts WHERE account_key=?", (key,)).fetchone()[0]
        done = new >= target
        if not done and not exhausted and not uncertain and new == old:
            # No new unique posts despite a moving cursor; no silent repeated calls.
            uncertain = True
        state = ("complete" if done else "exhausted" if exhausted else
                 "cursor_blocked" if uncertain else "partial")
        conn.execute("""UPDATE backfill_state SET next_cursor=?,last_cycle=?,
            pages_fetched=pages_fetched+1,exhausted=?,blocked=?,
            last_error_code=NULL,last_error=NULL,last_updated=? WHERE account_key=?""",
            (after, cycle, int(exhausted or done), int(uncertain), base.stamp(), key))
        conn.execute("""UPDATE accounts SET status=?,coverage=?,ig_user_id=?,
            followers_count=?,media_count=?,posts_collected=?,last_attempt_at=?,
            completed_at=?,error_code=NULL,error_message=NULL WHERE account_key=?""",
            ("success" if done or exhausted else "failed" if uncertain else "partial",
             state, info["ig_user_id"], info["followers_count"], info["media_count"],
             new, base.stamp(), base.stamp(), key))
    return new - old, new, state


def save_failure(conn: sqlite3.Connection, account: dict, cycle: str,
                 code: str, message: str, permanent: bool):
    with conn:
        conn.execute("""UPDATE backfill_state SET last_cycle=?,last_error_code=?,
            last_error=?,blocked=?,last_updated=? WHERE account_key=?""",
            (cycle, code, message[:300], int(permanent), base.stamp(), account["account_key"]))
        conn.execute("""UPDATE accounts SET status=?,error_code=?,error_message=?,
            last_attempt_at=? WHERE account_key=?""",
            ("failed" if permanent else "rate_limited", code,
             message[:300], base.stamp(), account["account_key"]))


def run(args) -> int:
    first, last = RANGES[args.app]
    if args.probe_ordinal is not None:
        if not first <= args.probe_ordinal <= last:
            raise ValueError("Probe ordinal must be inside this app range")
        first = last = args.probe_ordinal
    if not 1 <= args.batch_size <= 10 or (args.max_batches is not None and args.max_batches < 1):
        raise ValueError("Invalid batch size or max-batches")
    if not 0 < args.stop_usage < 100:
        raise ValueError("Usage stop threshold must be between 0 and 100")
    if args.max_minutes < 1 or args.max_minutes > 30:
        raise ValueError("Run duration must be 1..30 minutes")
    if args.delay_seconds < 0:
        raise ValueError("delay-seconds must be nonnegative")
    if args.interval_minutes != 90:
        raise ValueError("This backfill is configured for 90-minute cycles")
    source, digest = base.load_source(args.source)
    if len(source) != 294:
        raise ValueError("Current 150/144 app split requires exactly 294 account rows")
    cycle = cycle_id(now(), args.interval_minutes) if args.cycle_id is None else args.cycle_id
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", cycle):
        raise ValueError("Invalid cycle ID")
    if not args.live:
        print(f"DRY RUN: app {args.app}, official rows {first}..{last}, "
              f"{TAKE} posts/page, up to {TARGET} unique posts/account, "
              f"cycle={cycle}; no API calls or writes")
        print("Scheduler is NOT enabled; second app credentials must be independently authorized.")
        return 0
    if not args.env_file.is_file():
        raise ValueError("Missing authorized local Meta credential file")
    cfg = base.load_env(args.env_file)
    token = cfg.get("META_ACCESS_TOKEN", "").strip()
    caller = cfg.get("META_IG_USER_ID", "").strip()
    version = cfg.get("META_GRAPH_VERSION", "v26.0")
    if not token or not caller.isdigit() or not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Invalid Meta token, IG user ID or Graph API version")
    out = args.output_dir.resolve()
    if out == base.ROOT.resolve() or out.is_relative_to((base.ROOT / "kq3_294_collection").resolve()):
        raise ValueError("Refusing to write into legacy collector directory")
    out.mkdir(parents=True, exist_ok=True)
    with base.process_lock(out):
        db = base.database(out / "collection.sqlite", source, digest, TAKE,
                           (first, last, f"{args.app}_cursor_backfill"))
        try:
            init_backfill(db, source)
            if db.execute("SELECT 1 FROM backfill_runs WHERE cycle=?", (cycle,)).fetchone():
                print(f"SKIPPED: app {args.app} already ran cycle={cycle}")
                return 0
            if args.cycle_id is None:
                # Production: enforce exact cooldown in addition to fixed slots.
                # Explicit cycle IDs are reserved for network-free unit tests.
                prev = db.execute(
                    "SELECT started_utc,finished_utc FROM backfill_runs "
                    "ORDER BY started_utc DESC LIMIT 1").fetchone()
                if prev:
                    current = now()
                    started_age = (current - datetime.fromisoformat(prev["started_utc"])).total_seconds()
                    finished_age = ((current - datetime.fromisoformat(prev["finished_utc"])).total_seconds()
                                    if prev["finished_utc"] else -1)
                    if started_age < 90*60 or finished_age < 60*60:
                        print("SKIPPED: start-to-start 90min or finish-to-start 60min cooldown")
                        return 0
            # Reserve cycle before calls so overlapping tasks / duplicate
            # triggers cannot repeat the same page or race this run.
            with db:
                db.execute("INSERT INTO backfill_runs(cycle,started_utc) VALUES (?,?)",
                           (cycle, base.stamp()))
            started = time.monotonic()
            runs = 0
            fetched = 0
            try:
                while True:
                    if args.max_batches and runs >= args.max_batches:
                        print("Paused by --max-batches")
                        break
                    if time.monotonic() - started >= args.max_minutes * 60:
                        print("Paused by 30-minute runtime guard")
                        break
                    targets = select_pages(db, first, last, cycle, args.batch_size)
                    if not targets:
                        print("No eligible cursor pages in this cycle")
                        break
                    ops = [cursor_operation(a, caller, a["next_cursor"]) for a in targets]
                    batch_id = base.begin_batch(db, targets, TAKE)
                    print(f"App {args.app} cycle={cycle} batch {runs+1}: "
                          f"{targets[0]['ordinal']}..{targets[-1]['ordinal']} "
                          f"({len(targets)} accounts; 5 posts each)", flush=True)
                    try:
                        http, body, headers, sec = base.request_batch(version, token, ops)
                    except (URLError, TimeoutError, OSError):
                        with db:
                            db.execute("UPDATE batches SET finished_at=?,status=?,error=? "
                                       "WHERE batch_id=?",
                                       (base.stamp(), "transport_error",
                                        "Meta transport error; no retry", batch_id))
                        print("HALTED: transport failure; no automatic retry")
                        break
                    if http != 200 or not isinstance(body, list) or len(body) != len(targets):
                        with db:
                            db.execute("""UPDATE batches SET finished_at=?,http_status=?,
                                duration_seconds=?,status=?,error=? WHERE batch_id=?""",
                                (base.stamp(), http, round(sec,3), "invalid_response",
                                 "Malformed batch envelope; page checkpoints unchanged",
                                 batch_id))
                        print(f"HALTED: invalid outer batch response HTTP={http}")
                        break
                    ratios = [base.usage(headers)]
                    fatal = False
                    ok = 0
                    errors = 0
                    for account, item in zip(targets, body):
                        if not isinstance(item, dict):
                            fatal = True
                            break
                        ratios.append(base.usage(item.get("headers")))
                        sub_code = base.as_integer(item.get("code")) or 0
                        try:
                            payload = json.loads(item.get("body") or "{}")
                        except (TypeError, ValueError):
                            payload = {}
                        error_obj = payload.get("error") if isinstance(payload, dict) else None
                        if sub_code == 200 and isinstance(payload, dict) and not error_obj:
                            try:
                                page = parse_page(payload, account, account["next_cursor"])
                                added, count, state = save_page(db, account, cycle, page)
                                fetched += added
                                ok += 1
                            except (ValueError, sqlite3.Error):
                                save_failure(db, account, cycle, "cursor_or_payload",
                                             "Invalid pagination or post payload", True)
                                errors += 1
                        else:
                            code, message = base.safe_error(error_obj, token)
                            permanent = code not in base.STOP_CODES
                            save_failure(db, account, cycle, code, message, permanent)
                            errors += 1
                            if code in base.STOP_CODES or sub_code in base.STOP_HTTP:
                                fatal = True
                    runs += 1
                    vals = [x["total_time"] for x in ratios if "total_time" in x]
                    max_usage = max(vals) if vals else None
                    app_usage = {"outer": ratios[0], "inner": ratios[1:],
                                 "max_total_time_pct": max_usage}
                    with db:
                        db.execute("""UPDATE batches SET finished_at=?,http_status=?,
                            duration_seconds=?,success_count=?,failed_count=?,
                            rate_limited=?,usage_json=?,status=? WHERE batch_id=?""",
                            (base.stamp(), http, round(sec, 3), ok, errors,
                             int(fatal), json.dumps(app_usage), "completed", batch_id))
                    print(f"Batch {runs}: {sec:.3f}s success={ok} failed={errors} "
                          f"total_time_max={max_usage}% newly_unique_posts={fetched}")
                    if fatal:
                        print("HALTED: Meta authentication/rate error or malformed response")
                        break
                    if max_usage is None or max_usage >= args.stop_usage:
                        print(f"HALTED: usage missing or reached {args.stop_usage}% safety threshold")
                        break
                    if args.delay_seconds > 0:
                        time.sleep(args.delay_seconds)
            finally:
                with db:
                    db.execute("UPDATE backfill_runs SET finished_utc=?,pages_requested=?,status=? WHERE cycle=?",
                               (base.stamp(), runs, "closed", cycle))
                base.export_all(db, out)
            complete = db.execute("""SELECT COUNT(*) FROM backfill_state s JOIN accounts a
                                   ON s.account_key=a.account_key WHERE a.ordinal BETWEEN ? AND ?
                                   AND s.exhausted=1""", (first, last)).fetchone()[0]
            covered = db.execute("""SELECT COUNT(DISTINCT p.account_key)
                        FROM posts p JOIN accounts a ON a.account_key=p.account_key
                        WHERE a.ordinal BETWEEN ? AND ?""", (first, last)).fetchone()[0]
            print(f"SUMMARY: app={args.app} batches={runs} new_unique_posts={fetched} "
                  f"accounts_with_posts={covered} done_or_exhausted={complete}/{last-first+1}. "
                  "Previous posts and media preserved.")
            return 0
        finally:
            db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=tuple(RANGES), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--probe-ordinal", type=int,
                        help="Single account for isolated two-cycle cursor validation")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--delay-seconds", type=float, default=1.)
    parser.add_argument("--stop-usage", type=float, default=70.)
    parser.add_argument("--max-minutes", type=int, default=30)
    parser.add_argument("--interval-minutes", type=int, default=90)
    parser.add_argument("--cycle-id", help="Test-only cycle ID; NEVER set in live scheduling")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"Backfill stopped ({type(exc).__name__}): "
              + (str(exc)[:160] if not args.live else "check configuration or safe logs"),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
