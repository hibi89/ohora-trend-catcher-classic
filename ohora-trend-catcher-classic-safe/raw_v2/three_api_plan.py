"""Deterministic, API-free three-lane OHORA collection plan.

This is a planning/validation tool, NOT a live multi-token collector.
The existing single-token scheduler is unchanged.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

LANES = ("A", "B", "C")
ROSTER_SIZE = 294
POSTS_PER_PAGE = 4
STOP_USAGE = 85
COOLDOWN_MINUTES = 65


def build_plan(roster_size=ROSTER_SIZE):
    if roster_size != ROSTER_SIZE:
        raise ValueError("official roster must have exactly 294 accounts")
    # First two 65-minute rounds cover 12 positions per account.
    # Positions are planning labels only: runtime MUST use per-account cursors.
    return [
        {"round": 1, "lane": "A", "first": 1, "last": 150, "page": 1, "positions": [1, 4]},
        {"round": 1, "lane": "B", "first": 151, "last": 294, "page": 1, "positions": [1, 4]},
        {"round": 1, "lane": "C", "first": 1, "last": 150, "page": 2, "positions": [5, 8]},
        {"round": 2, "lane": "A", "first": 151, "last": 294, "page": 2, "positions": [5, 8]},
        {"round": 2, "lane": "B", "first": 1, "last": 150, "page": 3, "positions": [9, 12]},
        {"round": 2, "lane": "C", "first": 151, "last": 294, "page": 3, "positions": [9, 12]},
    ]


def validate(plan):
    if len(plan) != 6 or {(p["round"], p["lane"]) for p in plan} != {
        (round_no, lane) for round_no in (1, 2) for lane in LANES
    }:
        raise ValueError("exactly one assignment per lane per round required")
    for p in plan:
        if not 1 <= p["first"] <= p["last"] <= ROSTER_SIZE:
            raise ValueError("invalid account range")
        if p["last"] - p["first"] + 1 > 150:
            raise ValueError("lane exceeds 150 distinct accounts")
    for ordinal in range(1, ROSTER_SIZE + 1):
        pages = sorted(p["page"] for p in plan if p["first"] <= ordinal <= p["last"])
        if pages != [1, 2, 3]:
            raise ValueError(f"account {ordinal} has duplicate or missing pages: {pages}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Official 294-account CSV; read only")
    args = parser.parse_args(argv)
    with args.source.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != ROSTER_SIZE or len({r["account_key"] for r in rows}) != ROSTER_SIZE:
        parser.error("source must contain 294 unique account_key values")
    plan = build_plan()
    validate(plan)
    print(json.dumps({
        "mode": "PLAN_ONLY_NO_API_CALLS",
        "post_limit": POSTS_PER_PAGE,
        "stop_usage_percent": STOP_USAGE,
        "cooldown_minutes": COOLDOWN_MINUTES,
        "assignments": plan,
        "warning": "Not safe to execute as three existing collectors. Runtime cursor/lease/token isolation not implemented.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
