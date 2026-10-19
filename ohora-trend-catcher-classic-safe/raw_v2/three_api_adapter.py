"""Offline adapter boundary for OHORA three-lane coordinator.

Produces a validated, credential-free work intent. It never calls Meta,
reads credentials, or opens the production collection.sqlite.
The snapshot page index is NOT a valid Meta cursor: execution is forbidden
until a live adapter resolves anchored cursors from a safe checkpoint store.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from three_api_coordinator import Coordinator, LANES
from collector import load_accounts

POST_LIMIT = 4


def build_intent(job, accounts):
    ordinal = job["account_ordinal"]
    if not 1 <= ordinal <= len(accounts) == 294:
        raise ValueError("Official roster mismatch")
    if job["lane"] not in LANES or job["page"] not in (1, 2, 3):
        raise ValueError("Invalid lane/page")
    account = accounts[ordinal - 1]
    if account["ordinal"] != ordinal:
        raise ValueError("Roster order mismatch")
    return {
        "mode": "OFFLINE_INTENT_NO_API_CALLS",
        "lane": job["lane"],
        "account_key": account["key"],
        "username": account["username"],
        "account_ordinal": ordinal,
        "logical_page": job["page"],
        "post_limit": POST_LIMIT,
        "phase": job["phase"],
        "requires_verified_cursor": job["page"] > 1,
        "meta_request_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--lane", choices=LANES, required=True)
    args = parser.parse_args()
    accounts, _ = load_accounts(args.source)
    coordinator = Coordinator(args.state_db)
    coordinator.seed()
    job = coordinator.lease(args.lane)
    if job is None:
        print(json.dumps({"mode": "OFFLINE_INTENT_NO_API_CALLS",
                          "status": "no_eligible_job"}))
        return
    print(json.dumps(build_intent(job, accounts), ensure_ascii=False, indent=2))
    # Deliberately do not acknowledge completion: no data was collected.


if __name__ == "__main__":
    main()
