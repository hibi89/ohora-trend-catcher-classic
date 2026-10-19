"""Offline HTTP-envelope bridge for synthetic Meta responses.

No requests or credentials. Enforces fail-closed quota observation BEFORE
staging any posts. A 2xx payload without trustworthy usage is not committed.
"""
from __future__ import annotations

from three_api_meta_normalizer import normalize_meta_page
from three_api_usage import classify_failure, observe_headers


class FixtureEnvelopeError(ValueError):
    pass


def stage_fixture_envelope(coordinator, evidence, job, envelope, *, now=None):
    """Apply one synthetic HTTP response to a leased job, without network I/O."""
    if not isinstance(envelope, dict):
        raise FixtureEnvelopeError("Invalid response envelope")
    status = envelope.get("status")
    headers = envelope.get("headers")
    body = envelope.get("body")
    if type(status) is not int or not 100 <= status <= 599:
        raise FixtureEnvelopeError("Invalid HTTP status")
    if not isinstance(headers, dict):
        raise FixtureEnvelopeError("Missing response headers")
    lane = job["lane"]
    if status < 200 or status >= 300:
        error = body.get("error") if isinstance(body, dict) else None
        policy = classify_failure(status, error)
        # Never stage a failed HTTP response. Treat all failures as unsafe
        # for this lane until operator review; no automatic retry.
        coordinator.observe_usage(lane, None, now=now)
        return {"status": "blocked", "reason": policy, "lane": lane}
    # Some API envelopes carry an error despite HTTP 2xx. Never stage it.
    if isinstance(body, dict) and "error" in body:
        coordinator.observe_usage(lane, None, now=now)
        return {"status": "blocked", "reason": "api_error_envelope", "lane": lane}
    observed = observe_headers(coordinator, lane, headers, now=now)
    if observed["halted"]:
        return {"status": "blocked", "reason": "usage_limit_or_missing", "lane": lane}
    cursor = evidence.required_cursor(job["account_ordinal"], job["page"])
    normalized = normalize_meta_page(body, requested_cursor=cursor)
    edge = evidence.commit_staged_page(
        job["id"], job["lease_id"], normalized,
        requested_cursor=cursor, now=now,
    )
    return {"status": "staged", "lane": lane, "records": edge["records"],
            "terminal": edge["terminal"], "usage": observed["usage"]}
