"""Transactional cursor evidence for the offline three-API coordinator.

Only a *separate, verified* staging writer may supply the opaque receipt after
its collected page has been durably saved. This module does not independently
verify the external writer, and MUST NOT be used for live calls as-is.

Once the evidence table exists, Coordinator.lease enforces valid preceding
edges and Coordinator.complete is disabled. An evidence row and its job's
'done' transition commit atomically. No Meta calls or production DB writes.
"""
from __future__ import annotations

import re
import hashlib
import json

from three_api_coordinator import stamp, utcnow
from three_api_paging import validate_page_edge

# Opaque non-secret reference, never a token, URL, raw response, or credential.
RECEIPT_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


class PageEvidenceStore:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.db = coordinator.db
        self.db.execute("""CREATE TABLE IF NOT EXISTS page_evidence (
            account_ordinal INTEGER NOT NULL,
            page INTEGER NOT NULL CHECK(page BETWEEN 1 AND 3),
            job_id INTEGER NOT NULL UNIQUE,
            receipt TEXT NOT NULL,
            requested_cursor TEXT,
            response_cursor TEXT,
            terminal INTEGER NOT NULL CHECK(terminal IN (0,1)),
            PRIMARY KEY(account_ordinal,page)
        )""")
        self.db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
            page_evidence_receipt_unique ON page_evidence(receipt)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS staging_posts (
            job_id INTEGER NOT NULL,
            account_ordinal INTEGER NOT NULL,
            page INTEGER NOT NULL,
            post_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(job_id,post_id)
        )""")

    def required_cursor(self, account_ordinal, page):
        if page == 1:
            return None
        if page not in (2, 3):
            raise ValueError("Invalid page")
        previous = self.db.execute(
            """SELECT e.response_cursor,e.terminal FROM page_evidence e
               JOIN jobs j ON j.id=e.job_id
               WHERE e.account_ordinal=? AND e.page=? AND j.state='done'""",
            (account_ordinal, page - 1),
        ).fetchone()
        if previous is None or previous["terminal"] or not previous["response_cursor"]:
            raise ValueError("Missing verified predecessor cursor")
        return previous["response_cursor"]

    def commit_staged_page(self, job_id, lease_id, response,
                           requested_cursor=None, now=None):
        """Commit normalized posts and cursor evidence in ONE coordinator DB.

        Offline staging only. Payloads are not production RAW v2 schema and
        cannot substitute for the existing production collector.
        """
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ValueError("Invalid staging page")
        posts = response["data"]
        if len(posts) > 4:
            raise ValueError("Page exceeds four-post staging limit")
        ids = []
        for post in posts:
            if not isinstance(post, dict) or not isinstance(post.get("id"), str):
                raise ValueError("Every staged post needs a string id")
            if not post["id"].strip() or len(post["id"]) > 256:
                raise ValueError("Invalid staged post id")
            ids.append(post["id"])
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate post ids within a page")
        canonical = json.dumps(
            {"job_id": job_id, "posts": posts}, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        receipt = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self.commit_page(
            job_id, lease_id, receipt, response,
            requested_cursor=requested_cursor, now=now, staged_posts=posts,
        )

    def commit_page(self, job_id, lease_id, receipt, response,
                    requested_cursor=None, now=None, staged_posts=None):
        """Commit a validated cursor edge and the lease completion together.

        The caller must FIRST commit collected posts in a staging DB and
        verify that receipt. We do not attest cross-database atomicity here.
        """
        if not isinstance(receipt, str) or not RECEIPT_RE.fullmatch(receipt):
            raise ValueError("Invalid non-secret durable staging receipt")
        now = now or utcnow()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            job = self.db.execute(
                """SELECT * FROM jobs
                   WHERE id=? AND lease_id=? AND state='leased'
                     AND leased_until>?""",
                (job_id, lease_id, stamp(now)),
            ).fetchone()
            if job is None:
                raise ValueError("Missing, stale, or expired lease")
            if job["page"] == 1:
                if requested_cursor is not None:
                    raise ValueError("Head page must not use a cursor")
            elif requested_cursor != self.required_cursor(
                job["account_ordinal"], job["page"]
            ):
                raise ValueError("Cursor does not match predecessor evidence")
            prior = [
                row["response_cursor"]
                for row in self.db.execute(
                    """SELECT response_cursor FROM page_evidence
                       WHERE account_ordinal=? AND page<?
                       ORDER BY page""",
                    (job["account_ordinal"], job["page"] - 1),
                )
                if row["response_cursor"]
            ]
            edge = validate_page_edge(
                response, requested_cursor=requested_cursor, prior_cursors=prior,
            )
            if edge["next_cursor"] and edge["records"] == 0:
                raise ValueError("Empty nonterminal page cannot advance cursor")
            if staged_posts is not None:
                for post in staged_posts:
                    self.db.execute(
                        """INSERT INTO staging_posts
                           (job_id,account_ordinal,page,post_id,payload_json)
                           VALUES (?,?,?,?,?)""",
                        (job_id, job["account_ordinal"], job["page"], post["id"],
                         json.dumps(post, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False)),
                    )
            self.db.execute(
                """INSERT INTO page_evidence
                   (account_ordinal,page,job_id,receipt,requested_cursor,
                    response_cursor,terminal) VALUES (?,?,?,?,?,?,?)""",
                (job["account_ordinal"], job["page"], job_id, receipt,
                 requested_cursor, edge["next_cursor"], int(edge["terminal"])),
            )
            changed = self.db.execute(
                """UPDATE jobs SET state='done',lease_id=NULL,leased_until=NULL
                   WHERE id=? AND lease_id=? AND state='leased'""",
                (job_id, lease_id),
            )
            if changed.rowcount != 1:
                raise ValueError("Lease changed during commit")
            self.db.execute("COMMIT")
            return edge
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
