#!/usr/bin/env python3
"""Restore exactly five verified history roots; dry-run by default, no Meta calls."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from collector import fixed_history_cutoff, history_chain_status, parse_date

TARGETS = tuple(f"KR_{i:03d}" for i in range(1, 6))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    base = a.output_dir.resolve()
    dbfile = base / "collection.sqlite"
    if not dbfile.is_file():
        raise SystemExit("FAIL: database missing")
    db = sqlite3.connect(dbfile if a.apply else dbfile.as_uri() + "?mode=ro", uri=not a.apply)
    db.row_factory = sqlite3.Row
    if not a.apply:
        db.execute("PRAGMA query_only=ON")
    plans = []
    errors = []
    try:
        for key in TARGETS:
            issues = []
            account = db.execute("SELECT * FROM accounts WHERE account_key=?", (key,)).fetchone()
            if account is None:
                errors.append(key + ": missing account")
                continue
            if db.execute("SELECT COUNT(*) FROM history_page_evidence WHERE account_key=? AND requested_cursor IS NULL", (key,)).fetchone()[0]:
                issues.append("root already present")
            fronts = list(db.execute("SELECT * FROM request_log WHERE account_key=? AND phase='front' AND status='success'", (key,)))
            histories = list(db.execute("""SELECT e.* FROM history_page_evidence e
                JOIN request_log r ON r.request_id=e.request_id
                WHERE e.account_key=? AND r.phase='history' AND r.status='success'
                ORDER BY r.started_at""", (key,)))
            if not histories or not histories[0]["requested_cursor"]:
                issues.append("no history requested cursor")
            if len(histories) != 1:
                issues.append("expected exactly one history evidence")
            candidates = []
            if histories:
                cursor = histories[0]["requested_cursor"]
                for log in fronts:
                    path = (base / str(log["raw_response_path"] or "")).resolve()
                    if not path.is_relative_to(base / "runs") or not path.is_file():
                        issues.append("missing/outside raw for " + log["request_id"])
                        continue
                    try:
                        media = json.loads(path.read_text(encoding="utf-8"))["business_discovery"]["media"]
                        posts = media["data"]
                        after = media.get("paging", {}).get("cursors", {}).get("after")
                        dates = [parse_date(item["timestamp"]) for item in posts]
                        if not posts or not all(dates) or dates != sorted(dates, reverse=True):
                            issues.append("invalid post ordering/timestamps " + log["request_id"])
                            continue
                        count = db.execute("SELECT COUNT(*) FROM post_observations WHERE request_id=? AND run_id=?", (log["request_id"], log["run_id"])).fetchone()[0]
                        if count != len(posts):
                            issues.append("observation mismatch " + log["request_id"])
                            continue
                        if after == cursor:
                            candidates.append((log, after, dates))
                    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                        issues.append("invalid raw " + log["request_id"] + ": " + str(exc))
            if len(candidates) != 1:
                issues.append("matching front count " + str(len(candidates)))
            if candidates:
                log, after, dates = candidates[0]
                if db.execute("SELECT COUNT(*) FROM history_page_evidence WHERE request_id=?", (log["request_id"],)).fetchone()[0]:
                    issues.append("evidence request ID exists")
                if db.execute("SELECT COUNT(*) FROM request_log WHERE request_id=?", (log["request_id"],)).fetchone()[0] != 1:
                    issues.append("ambiguous request ID")
                if histories and histories[0]["requested_cursor"] != after:
                    issues.append("cursor mismatch")
                if histories and histories[0]["response_cursor"] != account["backfill_cursor"]:
                    issues.append("checkpoint mismatch")
            if issues:
                errors.append(key + ": " + "; ".join(issues))
            else:
                plans.append((log["request_id"], key, None, after,
                    min(dates).isoformat(), max(dates).isoformat(),
                    fixed_history_cutoff(db, 365).isoformat(), "front_root", log["finished_at"]))
                print(key, "MATCH", log["request_id"])
        for issue in errors:
            print("FAIL", issue)
        print("VALID_CANDIDATES", len(plans), "ERRORS", len(errors), "MODE", "APPLY" if a.apply else "DRY_RUN")
        if errors or len(plans) != len(TARGETS):
            return 2
        if not a.apply:
            print("DRY_RUN_PASS: no modifications")
            return 0
        destdir = base.parent / "OHORA_RAW_v2_backups"
        destdir.mkdir(parents=True, exist_ok=True)
        dest = destdir / ("five_roots_before_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite")
        copy = sqlite3.connect(dest)
        try:
            db.backup(copy)
        finally:
            copy.close()
        check = sqlite3.connect(dest)
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("backup integrity check failed")
        finally:
            check.close()
        print("BACKUP_VERIFIED", dest)
        db.execute("BEGIN IMMEDIATE")
        try:
            for item in plans:
                db.execute("INSERT INTO history_page_evidence VALUES (?,?,?,?,?,?,?,?,?)", item)
            for key in TARGETS:
                status = history_chain_status(db, key)
                if status["reason"] not in ("continuing", "verified"):
                    raise RuntimeError(key + ": unexpected chain " + str(status["reason"]))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        print("APPLIED_ROOTS", len(plans))
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
