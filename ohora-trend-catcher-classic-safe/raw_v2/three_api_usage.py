"""Offline policy for Meta usage observations and retry classification.

Does not perform HTTP requests, sleep, or automatically reset lane cooldowns.
"""
from __future__ import annotations

import math

USAGE_HEADERS = ("x-app-usage", "x-business-use-case-usage")
TRANSIENT_CODES = {1, 2, 4, 17, 32, 613}


def _numbers(value):
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)] if math.isfinite(value) else []
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            if key in ("call_count", "total_cputime", "total_time"):
                result += _numbers(item)
            elif isinstance(item, (dict, list)):
                result += _numbers(item)
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result += _numbers(item)
        return result
    return []


def parse_usage(headers):
    """Return max observed 0..100 utilization, or None (fail closed).

    Business-use-case header may be nested by business ID. Invalid/missing
    observations never imply unused quota.
    """
    if not isinstance(headers, dict):
        return None
    values = []
    for name, raw in headers.items():
        if not isinstance(name, str) or name.lower() not in USAGE_HEADERS:
            continue
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return None
        parsed = _numbers(raw)
        if not parsed:
            return None
        values.extend(parsed)
    if not values or any(v < 0 or v > 100 for v in values):
        return None
    return max(values)


def classify_failure(status, error=None):
    """Return stop policy without exposing request payload or credentials."""
    if type(status) is not int or not isinstance(error, (dict, type(None))):
        raise ValueError("Invalid response metadata")
    error = error or {}
    code = error.get("code")
    if status == 429 or code in TRANSIENT_CODES:
        return "cooldown"
    if status in (401, 403) or code in (10, 190, 200):
        return "credentials_or_permissions"
    if status >= 500:
        return "cooldown"
    return "invalid_response"


def observe_headers(coordinator, lane, headers, now=None):
    """Persist stop/cooldown when usage >=85 or usage is unavailable."""
    usage = parse_usage(headers)
    halted = coordinator.observe_usage(lane, usage, now=now)
    return {"usage": usage, "halted": halted}
