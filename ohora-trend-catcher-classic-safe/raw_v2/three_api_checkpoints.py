"""Read-only checkpoint inspection for a future three-API live adapter.

Logical page numbers are not Meta offsets. Never infer a cursor by page number.
Only page 1 can start at the head; later pages need a verified cursor chain
anchored to that same snapshot. This module does not call Meta or write DBs.
"""
from __future__ import annotations

import re
import sqlite3

CURSOR_RE = re.compile(r"[A-Za-z0-9_=+/\-]{1,4096}\Z")


def inspect_checkpoint(db_path, account_key):
    """Read existing RAW v2 checkpoint without opening its DB for writing."""
    uri = f"file:{__import__('pathlib').Path(db_path).resolve().as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            """SELECT account_key, latest_id, backfill_cursor,
                      catchup_cursor, catchup_anchor, backfill_done
               FROM accounts WHERE account_key=?""", (account_key,)
        ).fetchone()
        if row is None:
            raise ValueError("Account not present in checkpoint database")
        result = dict(row)
        for field in ("backfill_cursor", "catchup_cursor"):
            value = result[field]
            if value is not None and not CURSOR_RE.fullmatch(value):
                raise ValueError(f"Invalid {field} in checkpoint")
        return result
    finally:
        db.close()


def page_request_policy(logical_page, *, verified_chain=None):
    """Fail closed: historical checkpoints cannot substitute for snapshot edges."""
    if logical_page not in (1, 2, 3):
        raise ValueError("Invalid logical page")
    if logical_page == 1:
        return {"allowed": True, "cursor": None, "reason": "head_page"}
    if not verified_chain or len(verified_chain) < logical_page - 1:
        return {"allowed": False, "cursor": None,
                "reason": "missing_verified_snapshot_cursor_chain"}
    edges = verified_chain[:logical_page - 1]
    if any(not isinstance(c, str) or not CURSOR_RE.fullmatch(c) for c in edges):
        raise ValueError("Invalid snapshot cursor")
    if len(set(edges)) != len(edges):
        raise ValueError("Repeated snapshot cursor")
    return {"allowed": True, "cursor": edges[-1],
            "reason": "verified_snapshot_cursor_chain"}
