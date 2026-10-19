"""Offline three-lane collection runner using an injected page fetcher.

Never reads Meta credentials, never calls HTTP, never opens collection.sqlite.
The fetcher is a test double; a live implementation needs separate approval,
quota checks, snapshot anchoring and explicit security review.
"""
from __future__ import annotations

from pathlib import Path

from three_api_coordinator import Coordinator, LANES
from three_api_evidence import PageEvidenceStore
from three_api_adapter import build_intent
from three_api_meta_normalizer import normalize_meta_page
from three_api_http_fixture import stage_fixture_envelope


class OfflineThreeApiRunner:
    def __init__(self, state_db, accounts, fetch_page, *, meta_fixture=False, envelope_fixture=False):
        if not callable(fetch_page):
            raise TypeError("A callable offline page fixture is required")
        self.coordinator = Coordinator(Path(state_db))
        self.evidence = PageEvidenceStore(self.coordinator)
        self.accounts = accounts
        self.fetch_page = fetch_page
        if meta_fixture and envelope_fixture:
            raise ValueError('Choose only one fixture format')
        self.meta_fixture = meta_fixture
        self.envelope_fixture = envelope_fixture

    def close(self):
        self.coordinator.db.close()

    def seed(self):
        self.coordinator.seed()

    def run_one(self, lane, now=None):
        """Lease and stage one synthetic response; never retry on failure."""
        if lane not in LANES:
            raise ValueError("Invalid lane")
        job = self.coordinator.lease(lane, now=now)
        if job is None:
            return {"status": "no_eligible_job", "lane": lane}
        intent = build_intent(job, self.accounts)
        cursor = self.evidence.required_cursor(
            job["account_ordinal"], job["page"]
        )
        # The injected function MUST be an offline fixture. No live adapter.
        response = self.fetch_page(intent, cursor)
        if not isinstance(response, dict):
            raise ValueError("Fixture response must be a dictionary")
        if self.envelope_fixture:
            return stage_fixture_envelope(
                self.coordinator, self.evidence, job, response, now=now)
        if self.meta_fixture:
            response = normalize_meta_page(response, requested_cursor=cursor)
        edge = self.evidence.commit_staged_page(
            job["id"], job["lease_id"], response,
            requested_cursor=cursor, now=now,
        )
        return {
            "status": "staged",
            "lane": lane,
            "job_id": job["id"],
            "account_ordinal": job["account_ordinal"],
            "page": job["page"],
            "records": edge["records"],
            "terminal": edge["terminal"],
            "next_cursor_available": bool(edge["next_cursor"]),
        }
