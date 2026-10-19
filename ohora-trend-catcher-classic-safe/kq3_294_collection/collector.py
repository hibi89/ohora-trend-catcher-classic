#!/usr/bin/env python3
"""Resumable Meta Business Discovery and Elice vision collector for KQ3."""

from __future__ import annotations

import argparse
import csv
import email.utils
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
SOURCE_CSV = HERE.parent / "account_list.csv"
MANIFEST = HERE / "manifest.json"
ENV_FILE = Path(os.environ.get("KQ3_ENV_FILE", str(HERE / ".env.local"))).expanduser()
SUMMARY = HERE / "collection_summary.md"
KST = timezone(timedelta(hours=9), name="KST")
EXPECTED_ACCOUNTS = 294
MAX_POSTS = 20
MAX_RETRIES = 4
REQUEST_LOG = HERE / "api_request_log.csv"
REQUEST_LOG_FIELDS = [
    "requested_at", "method", "host", "path", "wait_ms", "response_ms",
    "http_status", "error_code", "retry_after_seconds", "app_usage_json",
    "business_use_case_usage_json",
]
_next_request_at = 0.0

ACCOUNT_FIELDS = [
    "account_key", "username", "country", "image_url", "ig_user_id",
    "followers_count", "media_count", "posts_collected", "status",
    "error_code", "error_message", "collected_at",
]
POST_FIELDS = [
    "post_id", "account_key", "username", "country", "timestamp",
    "caption", "media_type", "media_product_type", "permalink",
    "like_count", "comments_count", "engagement_count",
    "engagement_rate_pct", "media_count", "collected_at",
]
MEDIA_FIELDS = [
    "media_id", "post_id", "parent_media_id", "account_key", "username",
    "country", "media_role", "media_type", "media_url", "thumbnail_url",
    "sort_order", "collected_at",
]
STATUS_FIELDS = [
    "account_key", "username", "country", "status", "attempt_count",
    "last_attempt_at", "completed_at", "posts_requested", "posts_collected",
    "collection_completeness", "collection_strategy", "error_code",
    "error_message", "api_status", "data_completeness", "missing_fields",
    "error_type", "error_subcode", "http_status", "error_history_json",
]
TAG_FIELDS = [
    "media_id", "post_id", "account_key", "username", "country",
    "analyzed_at", "model_id", "visual_summary", "tags_json", "nail_style",
    "dominant_colors", "patterns", "finish", "shape", "confidence",
    "status", "error_code", "error_message",
]
CSV_FIELDS = {
    "accounts.csv": ACCOUNT_FIELDS,
    "posts.csv": POST_FIELDS,
    "media.csv": MEDIA_FIELDS,
    "collection_status.csv": STATUS_FIELDS,
    "design_tags.csv": TAG_FIELDS,
}


class CollectorError(Exception):
    def __init__(
        self, code: str, message: str, retry_after: float | None = None,
        error_type: str | None = None, error_subcode: str | None = None,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.error_type = error_type
        self.error_subcode = error_subcode
        self.http_status = http_status


@contextmanager
def process_lock():
    lock_path = HERE / "collection.lock"
    handle = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise CollectorError("run_already_active", "다른 수집 실행이 진행 중입니다.")
    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def source_rows() -> tuple[list[dict[str, str]], str]:
    if not SOURCE_CSV.is_file():
        raise CollectorError("source_missing", "공식 account_list.csv를 찾을 수 없습니다.")
    digest = hashlib.sha256(SOURCE_CSV.read_bytes()).hexdigest()
    with SOURCE_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"account_key", "username", "country", "image_url"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise CollectorError("source_schema", "공식 CSV에 필요한 열이 없습니다.")
        rows = []
        for row in reader:
            clean = {key: (row.get(key) or "").strip() for key in required}
            if not all(clean.values()):
                raise CollectorError("source_blank", "공식 CSV에 필수 값이 비어 있습니다.")
            rows.append(clean)
    if len(rows) != EXPECTED_ACCOUNTS:
        raise CollectorError("source_count", f"공식 CSV 행 수가 {EXPECTED_ACCOUNTS}개가 아닙니다.")
    if len({row["account_key"] for row in rows}) != len(rows):
        raise CollectorError("source_duplicate_key", "공식 CSV에 중복 account_key가 있습니다.")
    if len({row["username"].casefold() for row in rows}) != len(rows):
        raise CollectorError("source_duplicate_username", "공식 CSV에 중복 username이 있습니다.")
    return rows, digest


def read_csv(name: str) -> list[dict[str, str]]:
    path = HERE / name
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_csv(name: str, rows: list[dict[str, Any]]) -> None:
    path = HERE / name
    fields = CSV_FIELDS[name]
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=HERE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_text(path: Path, text: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=HERE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_manifest(source_hash: str) -> None:
    expected = {
        "source_file": "account_list.csv",
        "source_sha256": source_hash,
        "expected_accounts": EXPECTED_ACCOUNTS,
        "max_posts_per_account": MAX_POSTS,
        "created_at": now_kst(),
    }
    if MANIFEST.exists():
        saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if saved.get("source_sha256") != source_hash:
            raise CollectorError(
                "source_changed",
                "초기화 후 공식 account_list.csv가 바뀌었습니다. 기존 결과를 덮어쓰지 않았습니다.",
            )
        return
    atomic_text(MANIFEST, json.dumps(expected, ensure_ascii=False, indent=2) + "\n")


def ensure_outputs(
    source: list[dict[str, str]], source_hash: str
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]],
           dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    write_manifest(source_hash)
    for filename in CSV_FIELDS:
        if not (HERE / filename).exists():
            atomic_csv(filename, [])

    accounts = {row["account_key"]: row for row in read_csv("accounts.csv")}
    statuses = {row["account_key"]: row for row in read_csv("collection_status.csv")}
    for item in source:
        account_key = item["account_key"]
        accounts.setdefault(account_key, {
            **item, "ig_user_id": "", "followers_count": "", "media_count": "",
            "posts_collected": "0", "status": "pending", "error_code": "",
            "error_message": "", "collected_at": "",
        })
        statuses.setdefault(account_key, {
            **{k: item[k] for k in ("account_key", "username", "country")},
            "status": "pending", "attempt_count": "0", "last_attempt_at": "",
            "completed_at": "", "posts_requested": str(MAX_POSTS),
            "posts_collected": "0", "collection_completeness": "not_assessed",
            "collection_strategy": "", "error_code": "",
            "error_message": "", "api_status": "not_started",
            "data_completeness": "not_assessed", "missing_fields": "",
            "error_type": "", "error_subcode": "", "http_status": "",
            "error_history_json": "[]",
        })
        # Older status files predate the API/completeness split. Upgrade them
        # in memory without changing their existing operational status.
        statuses[account_key].setdefault(
            "api_status",
            "success" if statuses[account_key].get("status") == "success" else "not_started",
        )
        statuses[account_key].setdefault("data_completeness", "not_assessed")
        statuses[account_key].setdefault("missing_fields", "")
        statuses[account_key].setdefault("error_type", "")
        statuses[account_key].setdefault("error_subcode", "")
        statuses[account_key].setdefault("http_status", "")
        statuses[account_key].setdefault("error_history_json", "[]")
        statuses[account_key].setdefault("posts_requested", str(MAX_POSTS))
        statuses[account_key].setdefault("collection_completeness", "not_assessed")
        statuses[account_key].setdefault("collection_strategy", "")
    posts = {row["post_id"]: row for row in read_csv("posts.csv") if row.get("post_id")}
    media = {row["media_id"]: row for row in read_csv("media.csv") if row.get("media_id")}
    tags = {row["media_id"]: row for row in read_csv("design_tags.csv") if row.get("media_id")}
    persist(accounts, posts, media, statuses, tags)
    return accounts, posts, media, statuses, tags


def persist(
    accounts: dict[str, dict[str, Any]],
    posts: dict[str, dict[str, Any]],
    media: dict[str, dict[str, Any]],
    statuses: dict[str, dict[str, Any]],
    tags: dict[str, dict[str, Any]],
) -> None:
    atomic_csv("accounts.csv", list(accounts.values()))
    atomic_csv("posts.csv", list(posts.values()))
    atomic_csv("media.csv", list(media.values()))
    atomic_csv("design_tags.csv", list(tags.values()))
    # Status is written last so it acts as the resume commit marker.
    atomic_csv("collection_status.csv", list(statuses.values()))


def safe_text(value: Any, secrets: list[str], limit: int = 500) -> str:
    text = "" if value is None else str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization\s*[=:]\s*)(?:bearer\s+)?[^&\s,;]+",
        r"\1[REDACTED]", text,
    )
    text = re.sub(
        r"(?i)((?:access[_-]?token|api[_-]?key)\s*[=:]\s*)[^&\s,;]+",
        r"\1[REDACTED]", text,
    )
    return re.sub(r"[\r\n\t]+", " ", text).strip()[:limit]


def json_error(body: bytes, secrets: list[str]) -> tuple[str, str, str, str]:
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        error = payload.get("error", payload)
        if not isinstance(error, dict):
            raise ValueError("invalid_error_shape")
        code = error.get("code")
        error_type = error.get("type")
        subcode = error.get("error_subcode")
        message = error.get("message") or "API 요청이 실패했습니다."
        return (
            safe_text(code if code is not None else (error_type or "api_error"), secrets, 100),
            safe_text(message, secrets),
            safe_text(error_type, secrets, 100),
            safe_text(subcode, secrets, 100),
        )
    except (ValueError, AttributeError, TypeError):
        return "api_error", "API 응답 오류를 해석할 수 없습니다.", "", ""


def configured_request_interval() -> float:
    raw = os.getenv("META_REQUEST_INTERVAL_SECONDS", "25").strip()
    try:
        interval = float(raw)
    except ValueError:
        raise CollectorError(
            "configuration_invalid", "META_REQUEST_INTERVAL_SECONDS must be a non-negative number."
        ) from None
    if not 0 <= interval <= 3600:
        raise CollectorError(
            "configuration_invalid", "META_REQUEST_INTERVAL_SECONDS must be between 0 and 3600."
        )
    return interval


def retry_after_seconds(value: Any) -> float | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def usage_header_summary(headers: Any, name: str) -> dict[str, float]:
    """Whitelist numeric usage metrics and discard all IDs/raw header content."""
    allowed = {
        "call_count", "total_cputime", "total_time", "estimated_time_to_regain_access",
        "acc_id_util_pct", "business_use_case_usage", "ads_api_access_tier",
    }
    raw = headers.get(name) if headers is not None else None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    values: dict[str, float] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                normalized = str(key).lower()
                if normalized in allowed and isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[normalized] = max(values.get(normalized, float("-inf")), float(value))
                elif isinstance(value, (dict, list)):
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(parsed)
    return values


def append_request_log(
    *, method: str, url: str, wait_ms: float, response_ms: float,
    http_status: Any = "", error_code: Any = "", retry_after: Any = None,
    headers: Any = None, secrets: list[str] | None = None,
) -> None:
    parts = urlsplit(url)
    secret_values = secrets or []
    row = {
        "requested_at": now_kst(), "method": method,
        "host": safe_text(parts.hostname or "", secret_values, 200),
        "path": safe_text(parts.path, secret_values, 500),
        "wait_ms": round(wait_ms, 1), "response_ms": round(response_ms, 1),
        "http_status": http_status or "", "error_code": safe_text(error_code, [], 100),
        "retry_after_seconds": "" if retry_after is None else round(float(retry_after), 3),
        "app_usage_json": json.dumps(usage_header_summary(headers, "X-App-Usage"), sort_keys=True),
        "business_use_case_usage_json": json.dumps(
            usage_header_summary(headers, "X-Business-Use-Case-Usage"), sort_keys=True
        ),
    }
    exists = REQUEST_LOG.exists()
    with REQUEST_LOG.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUEST_LOG_FIELDS, extrasaction="ignore")
        if not exists or REQUEST_LOG.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def schedule_next_request(
    retry_after: float | None = None, backoff: float = 0.0, pace: bool = True,
) -> None:
    global _next_request_at
    interval = configured_request_interval() if pace else 0.0
    delay = max(interval, retry_after or 0.0, backoff)
    _next_request_at = max(_next_request_at, time.monotonic() + delay)


def wait_for_request_slot(pace: bool = True) -> float:
    if not pace and _next_request_at <= time.monotonic():
        return 0.0
    wait = max(0.0, _next_request_at - time.monotonic())
    if wait:
        time.sleep(wait)
    return wait


def is_data_pressure_error(exc: CollectorError) -> bool:
    return (
        str(exc.code) == "1"
        and exc.http_status == 500
        and "reduce the amount of data" in exc.message.casefold()
    )


def request_json(
    url: str,
    headers: dict[str, str],
    secrets: list[str],
    body: bytes | None = None,
    timeout: int = 45,
    max_retries: int = MAX_RETRIES,
    pace: bool = True,
) -> dict[str, Any]:
    method = "POST" if body is not None else "GET"
    for attempt in range(max_retries + 1):
        wait_seconds = wait_for_request_slot(pace)
        wait_ms = wait_seconds * 1000
        request_started = time.monotonic()
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw_response = response.read()
                elapsed_ms = (time.monotonic() - request_started) * 1000
                status = getattr(response, "status", None)
                response_headers = getattr(response, "headers", None)
                response_retry_after = retry_after_seconds(
                    response_headers.get("Retry-After", "") if response_headers is not None else ""
                )
                payload = json.loads(raw_response.decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                    code, message, error_type, error_subcode = json_error(raw_response, secrets)
                    append_request_log(
                        method=method, url=url, wait_ms=wait_ms, response_ms=elapsed_ms,
                        http_status=status, error_code=code, retry_after=response_retry_after,
                        headers=response_headers, secrets=secrets,
                    )
                    schedule_next_request(response_retry_after, pace=pace)
                    raise CollectorError(code, message, response_retry_after, error_type, error_subcode, status)
                append_request_log(
                    method=method, url=url, wait_ms=wait_ms, response_ms=elapsed_ms,
                    http_status=status, retry_after=response_retry_after,
                    headers=response_headers, secrets=secrets,
                )
                schedule_next_request(response_retry_after, pace=pace)
                return payload
        except HTTPError as exc:
            raw_error = exc.read(1_000_000)
            code, message, error_type, error_subcode = json_error(raw_error, secrets)
            response_ms = (time.monotonic() - request_started) * 1000
            retry_after = retry_after_seconds(exc.headers.get("Retry-After", ""))
            error = CollectorError(code, message, retry_after, error_type, error_subcode, exc.code)
            append_request_log(
                method=method, url=url, wait_ms=wait_ms, response_ms=response_ms,
                http_status=exc.code, error_code=code, retry_after=retry_after, headers=exc.headers,
                secrets=secrets,
            )
            retryable = (
                attempt < max_retries
                and not is_data_pressure_error(error)
                and exc.code >= 500
                and exc.code not in {501, 505}
            )
            if retryable:
                schedule_next_request(retry_after, backoff=min(2 ** attempt, 30), pace=pace)
                continue
            schedule_next_request(retry_after, pace=pace)
            raise error
        except CollectorError:
            raise
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            response_ms = (time.monotonic() - request_started) * 1000
            append_request_log(
                method=method, url=url, wait_ms=wait_ms, response_ms=response_ms,
                error_code=type(exc).__name__, secrets=secrets,
            )
            if attempt < max_retries:
                schedule_next_request(backoff=min(2 ** attempt, 30), pace=pace)
                continue
            schedule_next_request(pace=pace)
            raise CollectorError("network_or_json_error", type(exc).__name__) from None
    raise CollectorError("retry_exhausted", "API 재시도 횟수를 초과했습니다.")


def business_discovery(
    username: str, api_version: str, ig_user_id: str, token: str,
    max_posts: int = MAX_POSTS, max_retries: int = MAX_RETRIES,
    after: str | None = None, minimal_fields: bool = False,
) -> dict[str, Any]:
    if not 1 <= max_posts <= MAX_POSTS:
        raise CollectorError("invalid_post_limit", f"max_posts must be between 1 and {MAX_POSTS}.")
    version_number = api_version.strip().removeprefix("v").removeprefix("V")
    if not re.fullmatch(r"\d+\.\d+", version_number):
        raise CollectorError("configuration_invalid", "META_GRAPH_VERSION must use a value such as v26.0.")
    version_segment = f"v{version_number}"
    media_fields = "id,caption,media_type,permalink,timestamp,like_count,comments_count,media_url,thumbnail_url"
    if not minimal_fields:
        media_fields += ",media_product_type,children.limit(50){id,media_type,media_url,thumbnail_url}"
    media_edge = f"media.limit({max_posts})"
    if after:
        media_edge += f".after({json.dumps(after, ensure_ascii=True)})"
    fields = (
        f"business_discovery.username({username})"
        f"{{username,id,followers_count,media_count,{media_edge}{{{media_fields}}}}}"
    )
    query = urlencode({"fields": fields})
    url = f"https://graph.facebook.com/{version_segment}/{ig_user_id}?{query}"
    payload = request_json(url, {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }, [token], max_retries=max_retries)
    result = payload.get("business_discovery")
    if not isinstance(result, dict):
        raise CollectorError("target_unavailable", "Business Discovery에서 계정을 반환하지 않았습니다.")
    return result


def business_discovery_with_fallback(
    username: str, api_version: str, ig_user_id: str, token: str,
) -> tuple[dict[str, Any], str, str, CollectorError | None]:
    """Collect up to twenty latest posts, reducing Graph response cost only on code 1/HTTP 500."""
    strategy: list[str] = []

    def request_page(limit: int, after: str | None = None) -> tuple[dict[str, Any], str]:
        try:
            result = business_discovery(
                username, api_version, ig_user_id, token, max_posts=limit,
                max_retries=1 if limit == MAX_POSTS and after is None else 0,
                after=after, minimal_fields=False,
            )
            strategy.append(f"full_{limit}")
            return result, "full"
        except CollectorError as full_error:
            if not is_data_pressure_error(full_error):
                raise
            if limit > 10:
                limit = 10
                try:
                    result = business_discovery(
                        username, api_version, ig_user_id, token, max_posts=limit,
                        max_retries=0, after=after, minimal_fields=False,
                    )
                    strategy.append("full_10_fallback")
                    return result, "full"
                except CollectorError as reduced_error:
                    if not is_data_pressure_error(reduced_error):
                        raise
            result = business_discovery(
                username, api_version, ig_user_id, token, max_posts=limit,
                max_retries=0, after=after, minimal_fields=True,
            )
            strategy.append(f"minimal_{limit}")
            return result, "minimal"

    # First attempt requests the standard target. Only the specific Meta data-volume
    # error activates the 10-post fallback path.
    first, first_mode = request_page(MAX_POSTS)
    first_media = first.get("media") if isinstance(first.get("media"), dict) else {}
    first_posts = first_media.get("data", []) if isinstance(first_media.get("data"), list) else []
    combined = dict(first)
    combined_media = dict(first_media)
    combined_posts = [post for post in first_posts if isinstance(post, dict)][:MAX_POSTS]
    combined_media["data"] = combined_posts
    combined["media"] = combined_media

    if len(combined_posts) >= MAX_POSTS:
        return combined, "+".join(strategy), "complete", None

    media_count = first.get("media_count")
    try:
        if media_count is not None and int(media_count) <= len(combined_posts):
            return combined, "+".join(strategy), "complete", None
    except (TypeError, ValueError):
        pass

    paging = first_media.get("paging") if isinstance(first_media.get("paging"), dict) else {}
    cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
    after = cursors.get("after")
    if not after or not combined_posts:
        return combined, "+".join(strategy), "partial", None

    remaining = MAX_POSTS - len(combined_posts)
    next_limit = min(10, remaining)
    try:
        second, second_mode = request_page(next_limit, str(after))
        second_media = second.get("media") if isinstance(second.get("media"), dict) else {}
        second_posts = second_media.get("data", []) if isinstance(second_media.get("data"), list) else []
        known_ids = {str(post.get("id")) for post in combined_posts if post.get("id")}
        for post in second_posts:
            if isinstance(post, dict) and (not post.get("id") or str(post.get("id")) not in known_ids):
                combined_posts.append(post)
                if post.get("id"):
                    known_ids.add(str(post["id"]))
            if len(combined_posts) >= MAX_POSTS:
                break
        combined_media["data"] = combined_posts[:MAX_POSTS]
        # Keep account-level values from the first page, and the latest available
        # cursor metadata from page two to make the actual returned coverage explicit.
        if isinstance(second_media.get("paging"), dict):
            combined_media["paging"] = second_media["paging"]
        coverage = "complete" if len(combined_posts) >= MAX_POSTS else "partial"
        if coverage == "partial":
            try:
                coverage = "complete" if int(media_count) <= len(combined_posts) else "partial"
            except (TypeError, ValueError):
                pass
        return combined, "+".join(strategy), coverage, None
    except CollectorError as exc:
        # Retain first-page data and defer the error so the caller can commit it
        # before applying account-specific or global halt policy.
        combined_media["data"] = combined_posts[:MAX_POSTS]
        return combined, "+".join(strategy), "partial", exc


def media_posts(result: dict[str, Any], limit: int = MAX_POSTS) -> list[dict[str, Any]]:
    media_result = result.get("media")
    raw_posts = media_result.get("data", []) if isinstance(media_result, dict) else []
    if not isinstance(raw_posts, list):
        return []
    return [post for post in raw_posts[:limit] if isinstance(post, dict)]


def media_children(post: dict[str, Any]) -> list[dict[str, Any]]:
    children_result = post.get("children")
    raw_children = children_result.get("data", []) if isinstance(children_result, dict) else []
    if not isinstance(raw_children, list):
        return []
    return [child for child in raw_children if isinstance(child, dict)]


def has_media_url(media: dict[str, Any]) -> bool:
    return bool(media.get("media_url") or media.get("thumbnail_url"))


def assess_data_completeness(
    result: dict[str, Any], limit: int = MAX_POSTS,
) -> tuple[str, list[str]]:
    posts = media_posts(result, limit)
    if not posts:
        missing_account = [] if result.get("id") else ["account_id"]
        return ("partial" if missing_account else "not_applicable"), missing_account
    missing: set[str] = set()
    if not result.get("id"):
        missing.add("account_id")
    for index, post in enumerate(posts, start=1):
        post_id = str(post.get("id") or f"row_{index}")
        if not post.get("id"):
            missing.add(f"post_id:{post_id}")
        if not post.get("timestamp"):
            missing.add(f"published_date:{post_id}")
        # Graph API can omit like_count for some media types. None means absent;
        # integer 0 is a valid observed value and must remain present.
        if post.get("like_count") is None:
            missing.add(f"like_count:{post_id}")
        if post.get("comments_count") is None:
            missing.add(f"comments_count:{post_id}")
        children = media_children(post)
        if post.get("media_type") == "CAROUSEL_ALBUM":
            if not children:
                missing.add(f"carousel_children:{post_id}")
            for child_index, child in enumerate(children, start=1):
                child_id = str(child.get("id") or f"{post_id}_child_{child_index}")
                if not child.get("id"):
                    missing.add(f"carousel_child_id:{child_id}")
                if not has_media_url(child):
                    missing.add(f"image_url:{child_id}")
        elif not has_media_url(post):
            missing.add(f"image_url:{post_id}")
    return ("partial" if missing else "complete"), sorted(missing)


def should_halt_meta(exc: CollectorError) -> bool:
    code = str(exc.code)
    return (
        exc.http_status == 429
        or code in {"4", "17", "32", "613"}
        or exc.http_status in {401, 403}
        or code in {"10", "102", "104", "190", "200"}
    )


def smoke_test(source: list[dict[str, str]], username_override: str | None = None) -> int:
    """Read-only Meta check: no lock, manifest, summary, or collection CSV writes."""
    load_env_file()
    target = source[0]
    target_kind = "official_first_account"
    username = target["username"]
    if username_override:
        username = username_override.strip().removeprefix("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
            print(json.dumps({
                "test": "meta_business_discovery_smoke", "success": False,
                "error_code": "invalid_username", "request_duration_ms": 0,
            }))
            return 2
        target_kind = "alternate_public_professional_account"

    try:
        token, ig_user_id, version = check_meta_config()
    except CollectorError as exc:
        print(json.dumps({
            "test": "meta_business_discovery_smoke", "target": target_kind,
            "success": False, "api_success": False, "data_completeness": "not_assessed",
            "posts_requested": 3,
            "error_code": safe_text(exc.code, []),
            "missing_configuration": exc.message.split(": ", 1)[-1].split(", "),
            "request_duration_ms": 0,
        }, ensure_ascii=False))
        return 2

    started = time.perf_counter()
    try:
        result = business_discovery(
            username, version, ig_user_id, token, max_posts=3, max_retries=0,
        )
    except CollectorError as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        print(json.dumps({
            "test": "meta_business_discovery_smoke", "target": target_kind,
            "success": False, "api_success": False, "data_completeness": "not_assessed",
            "posts_requested": 3,
            "error_code": safe_text(exc.code, [token]),
            "meta_error": {
                "message": safe_text(exc.message, [token]),
                "type": safe_text(exc.error_type, [token]) or None,
                "code": safe_text(exc.code, [token]),
                "error_subcode": safe_text(exc.error_subcode, [token]) or None,
            },
            "error_code_capture_ready": True,
            "request_duration_ms": duration_ms,
        }, ensure_ascii=False))
        return 1
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        print(json.dumps({
            "test": "meta_business_discovery_smoke", "target": target_kind,
            "success": False, "api_success": False, "data_completeness": "not_assessed",
            "posts_requested": 3,
            "error_code": type(exc).__name__, "error_code_capture_ready": True,
            "request_duration_ms": duration_ms,
        }, ensure_ascii=False))
        return 1

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    posts = media_posts(result, 3)
    post_ids = sum(bool(post.get("id")) for post in posts)
    likes = sum(post.get("like_count") is not None for post in posts)
    comments = sum(post.get("comments_count") is not None for post in posts)
    dates = sum(bool(post.get("timestamp")) for post in posts)
    image_urls = sum(
        has_media_url(post) or any(has_media_url(child) for child in media_children(post))
        for post in posts
    )
    account_id_obtained = bool(result.get("id"))
    completeness, missing_fields = assess_data_completeness(result, 3)
    print(json.dumps({
        "test": "meta_business_discovery_smoke", "target": target_kind,
        "success": True, "api_success": True, "posts_requested": 3, "posts_returned": len(posts),
        "account_id_obtained": account_id_obtained,
        "post_ids_obtained": post_ids, "like_count_obtained": likes,
        "comments_count_obtained": comments, "published_date_obtained": dates,
        "image_url_obtained": image_urls, "request_duration_ms": duration_ms,
        "data_completeness": completeness, "missing_fields": missing_fields,
        "error_code": None, "error_code_capture_ready": True,
        "csv_outputs_modified": False,
    }, ensure_ascii=False))
    return 0


def collect_account(
    source: dict[str, str],
    result: dict[str, Any],
    collected_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    account = {
        **source,
        "ig_user_id": result.get("id", ""),
        "followers_count": result.get("followers_count", ""),
        "media_count": result.get("media_count", ""),
        "posts_collected": "0",
        "status": "success",
        "error_code": "",
        "error_message": "",
        "collected_at": collected_at,
    }
    account_posts = []
    account_media = []
    for post in media_posts(result, MAX_POSTS):
        post_id = str(post.get("id") or "")
        if not post_id:
            continue
        likes = post.get("like_count")
        comments = post.get("comments_count")
        try:
            engagement = int(likes) + int(comments) if likes is not None and comments is not None else ""
        except (ValueError, TypeError):
            engagement = ""
        followers = result.get("followers_count") or 0
        try:
            rate = f"{(100 * engagement / int(followers)):.6f}" if followers and engagement != "" else ""
        except (ValueError, TypeError, ZeroDivisionError):
            rate = ""
        children = media_children(post)
        is_carousel = post.get("media_type") == "CAROUSEL_ALBUM"
        count = (len(children) if children else "") if is_carousel else 1
        account_posts.append({
            "post_id": post_id, "account_key": source["account_key"],
            "username": source["username"], "country": source["country"],
            "timestamp": post.get("timestamp", ""), "caption": post.get("caption", ""),
            "media_type": post.get("media_type", ""),
            "media_product_type": post.get("media_product_type", ""),
            "permalink": post.get("permalink", ""), "like_count": likes if likes is not None else "",
            "comments_count": comments if comments is not None else "", "engagement_count": engagement,
            "engagement_rate_pct": rate, "media_count": count,
            "collected_at": collected_at,
        })
        if is_carousel:
            account_media.append({
                "media_id": post_id, "post_id": post_id, "parent_media_id": "",
                "account_key": source["account_key"], "username": source["username"],
                "country": source["country"], "media_role": "carousel_container",
                "media_type": "CAROUSEL_ALBUM", "media_url": post.get("media_url", ""),
                "thumbnail_url": post.get("thumbnail_url", ""),
                "sort_order": "0", "collected_at": collected_at,
            })
            for idx, child in enumerate(children, start=1):
                child_id = str(child.get("id") or f"{post_id}:child:{idx}")
                account_media.append({
                    "media_id": child_id, "post_id": post_id, "parent_media_id": post_id,
                    "account_key": source["account_key"], "username": source["username"],
                    "country": source["country"], "media_role": "carousel_item",
                    "media_type": child.get("media_type", ""),
                    "media_url": child.get("media_url", ""),
                    "thumbnail_url": child.get("thumbnail_url", ""),
                    "sort_order": str(idx), "collected_at": collected_at,
                })
        else:
            account_media.append({
                "media_id": post_id, "post_id": post_id, "parent_media_id": "",
                "account_key": source["account_key"], "username": source["username"],
                "country": source["country"], "media_role": "primary",
                "media_type": post.get("media_type", ""),
                "media_url": post.get("media_url", ""),
                "thumbnail_url": post.get("thumbnail_url", ""),
                "sort_order": "1", "collected_at": collected_at,
            })
    account["posts_collected"] = str(len(account_posts))
    return account, account_posts, account_media


def extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S)
    text = re.sub(r"</?answer>", "", text, flags=re.I).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("model_output_not_json")


def classify_image(
    media_url: str,
    base_url: str,
    api_key: str,
    model_id: str,
) -> dict[str, Any]:
    prompt = (
        "Analyze this public nail-art image for a KQ3 trend dataset. "
        "Return only one JSON object with keys visual_summary, nail_style, "
        "dominant_colors (array), patterns (array), finish, shape, tags (array), "
        "confidence (0 to 1). Describe visible nail design features only. "
        "Use null or an empty array when uncertain."
    )
    payload = {
        "model": model_id,
        "temperature": 0.1,
        "max_tokens": 500,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": media_url}},
            ],
        }],
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = base_url.rstrip("/") + "/v1/chat/completions"
    response = request_json(endpoint, {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, [api_key], body=body, timeout=120, pace=False)
    choices = response.get("choices") or []
    content = ((choices[0].get("message") or {}).get("content")) if choices else None
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    if not content:
        raise CollectorError("empty_model_response", "Elice 비전 모델 응답에 분석 결과가 없습니다.")
    return extract_json(str(content))


def update_summary(
    source: list[dict[str, str]],
    statuses: dict[str, dict[str, Any]],
    posts: dict[str, dict[str, Any]],
    media: dict[str, dict[str, Any]],
    tags: dict[str, dict[str, Any]],
    event: str,
) -> None:
    by_status: dict[str, int] = {}
    by_api_status: dict[str, int] = {}
    by_completeness: dict[str, int] = {}
    by_collection_coverage: dict[str, int] = {}
    for row in statuses.values():
        key = row.get("status", "pending")
        by_status[key] = by_status.get(key, 0) + 1
        api_key = row.get("api_status", "not_started")
        by_api_status[api_key] = by_api_status.get(api_key, 0) + 1
        completeness_key = row.get("data_completeness", "not_assessed")
        by_completeness[completeness_key] = by_completeness.get(completeness_key, 0) + 1
        coverage_key = row.get("collection_completeness", "not_assessed")
        by_collection_coverage[coverage_key] = by_collection_coverage.get(coverage_key, 0) + 1
    countries: dict[str, int] = {}
    for row in source:
        countries[row["country"]] = countries.get(row["country"], 0) + 1
    rendered = [
        "## 자동 갱신 진행 현황",
        "",
        f"- 마지막 실행 상태: {event}",
        f"- 계정 상태: {json.dumps(by_status, ensure_ascii=False, sort_keys=True)}",
        f"- API 상태: {json.dumps(by_api_status, ensure_ascii=False, sort_keys=True)}",
        f"- 데이터 완전성: {json.dumps(by_completeness, ensure_ascii=False, sort_keys=True)}",
        f"- 게시물 수집 범위: {json.dumps(by_collection_coverage, ensure_ascii=False, sort_keys=True)}",
        f"- posts.csv 행: {len(posts)}",
        f"- media.csv 행: {len(media)}",
        f"- design_tags.csv 행: {len(tags)}",
        f"- 마지막 갱신: {now_kst()}",
        "",
        "| 국가 | 계정 수 |",
        "|---|---:|",
    ]
    rendered.extend(f"| {country} | {count} |" for country, count in sorted(countries.items()))
    new_block = "\n".join(rendered)
    old = SUMMARY.read_text(encoding="utf-8") if SUMMARY.exists() else ""
    start_marker = "<!-- AUTO_STATUS_START -->"
    end_marker = "<!-- AUTO_STATUS_END -->"
    if start_marker in old and end_marker in old:
        prefix = old.split(start_marker, 1)[0]
        suffix = old.split(end_marker, 1)[1]
    else:
        prefix, suffix = "", ""
    atomic_text(SUMMARY, prefix + start_marker + "\n" + new_block + "\n" + end_marker + suffix)


def check_meta_config() -> tuple[str, str, str]:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("META_IG_USER_ID", "").strip()
    version = os.getenv("META_GRAPH_VERSION", "").strip().removeprefix("v").removeprefix("V")
    missing = [
        name for name, value in (
            ("META_ACCESS_TOKEN", token),
            ("META_IG_USER_ID", ig_user_id),
            ("META_GRAPH_VERSION", version),
        ) if not value
    ]
    if missing:
        raise CollectorError("configuration_missing", "Required configuration not set: " + ", ".join(missing))
    if not re.fullmatch(r"\d+\.\d+", version):
        raise CollectorError("configuration_invalid", "META_GRAPH_VERSION must use a value such as 24.0.")
    return token, ig_user_id, version


def meta_stage(
    source: list[dict[str, str]], source_hash: str,
    account_keys: list[str] | None = None,
    retry_account_keys: list[str] | None = None,
) -> int:
    if account_keys is not None and retry_account_keys is not None:
        raise CollectorError(
            "conflicting_account_filters",
            "Use either --account-keys or --retry-account-keys, not both.",
        )
    manual_retry_keys = set(retry_account_keys or [])
    requested_keys = retry_account_keys if retry_account_keys is not None else account_keys
    targets = source
    if requested_keys is not None:
        if len(requested_keys) != len(set(requested_keys)):
            raise CollectorError("duplicate_account_filter", "계정 키 필터에 중복 키가 있습니다.")
        source_by_key = {row["account_key"]: row for row in source}
        unknown = [key for key in requested_keys if key not in source_by_key]
        if unknown:
            raise CollectorError("unknown_account_filter", "계정 키 필터에 공식 CSV에 없는 키가 있습니다.")
        selected = set(requested_keys)
        targets = [row for row in source if row["account_key"] in selected]

    load_env_file()
    accounts, posts, media, statuses, tags = ensure_outputs(source, source_hash)
    try:
        token, ig_user_id, version = check_meta_config()
    except CollectorError as exc:
        update_summary(source, statuses, posts, media, tags, f"API 미호출: {exc.message}")
        print(f"Meta collection not started; {exc.message}")
        return 2

    if manual_retry_keys:
        not_retryable = [
            item["account_key"] for item in targets
            if statuses[item["account_key"]].get("status") not in {"failed", "partial"}
        ]
        if not_retryable:
            raise CollectorError(
                "manual_retry_requires_failed_or_partial_status",
                "--retry-account-keys can target only accounts currently marked failed or partial.",
            )

    total = len(targets)
    completed = sum(
        1 for item in targets
        if statuses[item["account_key"]].get("status") in {"success", "partial"}
    )
    halted = False
    failed_this_run = 0
    skipped_failed = 0
    for index, item in enumerate(targets, start=1):
        key = item["account_key"]
        if statuses[key].get("status") in {"success", "partial"} and key not in manual_retry_keys:
            print(f"account {index}/{total} {key}: skipped; prior collection exists")
            continue
        if statuses[key].get("status") == "failed" and key not in manual_retry_keys:
            skipped_failed += 1
            print(f"account {index}/{total} {key}: skipped; prior failure requires explicit retry")
            continue
        started = now_kst()
        attempts = int(statuses[key].get("attempt_count") or 0) + 1
        if key in manual_retry_keys:
            try:
                error_history = json.loads(statuses[key].get("error_history_json") or "[]")
                if not isinstance(error_history, list):
                    error_history = []
            except (ValueError, TypeError):
                error_history = []
            if statuses[key].get("error_code") or statuses[key].get("error_message"):
                error_history.append({
                    "attempt": statuses[key].get("attempt_count", ""),
                    "at": statuses[key].get("completed_at") or statuses[key].get("last_attempt_at", ""),
                    "error_code": safe_text(statuses[key].get("error_code", ""), [token], 100),
                    "error_message": safe_text(statuses[key].get("error_message", ""), [token]),
                    "error_type": safe_text(statuses[key].get("error_type", ""), [token], 100),
                    "error_subcode": safe_text(statuses[key].get("error_subcode", ""), [token], 100),
                    "http_status": statuses[key].get("http_status", ""),
                })
            statuses[key]["error_history_json"] = json.dumps(error_history, ensure_ascii=False)
        statuses[key].update({
            "status": "in_progress", "attempt_count": str(attempts),
            "last_attempt_at": started, "posts_requested": str(MAX_POSTS),
            "collection_completeness": "in_progress", "collection_strategy": "",
            "error_code": "", "error_message": "",
            "api_status": "in_progress", "data_completeness": "not_assessed",
            "missing_fields": "", "error_type": "", "error_subcode": "",
            "http_status": "",
        })
        atomic_csv("collection_status.csv", list(statuses.values()))
        api_succeeded = False
        halt_after_save = False
        result: dict[str, Any] = {}
        try:
            result, collection_strategy, coverage, deferred_error = business_discovery_with_fallback(
                item["username"], version, ig_user_id, token,
            )
            api_succeeded = True
            completeness, missing_fields = assess_data_completeness(result)
            account, account_posts, account_media = collect_account(item, result, now_kst())
            account_status = "success" if coverage == "complete" else "partial"
            accounts[key] = account
            accounts[key]["status"] = account_status
            for row in account_posts:
                posts[row["post_id"]] = row
            for row in account_media:
                media[row["media_id"]] = row
            statuses[key].update({
                "status": account_status, "completed_at": now_kst(),
                "posts_requested": str(MAX_POSTS),
                "posts_collected": str(len(account_posts)),
                "collection_completeness": coverage,
                "collection_strategy": collection_strategy,
                "error_code": safe_text(deferred_error.code, [token]) if deferred_error else "",
                "error_message": safe_text(deferred_error.message, [token]) if deferred_error else "",
                "api_status": "success", "data_completeness": completeness,
                "missing_fields": json.dumps(missing_fields, ensure_ascii=False),
                "error_type": safe_text(deferred_error.error_type, [token], 100) if deferred_error else "",
                "error_subcode": safe_text(deferred_error.error_subcode, [token], 100) if deferred_error else "",
                "http_status": str(deferred_error.http_status or "") if deferred_error else "",
            })
            completed += 1
            if deferred_error:
                halt_after_save = should_halt_meta(deferred_error)
                event = f"Meta 계정 {key} 부분 저장 ({statuses[key]['posts_collected']}/{MAX_POSTS})"
            else:
                event = f"Meta 계정 {key} 저장 완료 ({statuses[key]['posts_collected']}/{MAX_POSTS})"
        except CollectorError as exc:
            safe_message = safe_text(exc.message, [token])
            accounts[key].update({
                "status": "failed", "error_code": safe_text(exc.code, [token]),
                "error_message": safe_message, "collected_at": now_kst(),
            })
            statuses[key].update({
                "status": "failed", "completed_at": now_kst(),
                "posts_requested": str(MAX_POSTS),
                "collection_completeness": "none",
                "collection_strategy": "",
                "posts_collected": "0",
                "error_code": safe_text(exc.code, [token]),
                "error_message": safe_message,
                "api_status": "success" if api_succeeded else "failed",
                "data_completeness": (
                    assess_data_completeness(result)[0] if api_succeeded else "not_assessed"
                ),
                "missing_fields": (
                    json.dumps(assess_data_completeness(result)[1], ensure_ascii=False)
                    if api_succeeded else ""
                ),
                "error_type": safe_text(exc.error_type, [token], 100),
                "error_subcode": safe_text(exc.error_subcode, [token], 100),
                "http_status": str(exc.http_status or ""),
            })
            halt_after_save = should_halt_meta(exc)
            failed_this_run += 1
            event = f"Meta 계정 {key} 실패 ({statuses[key]['error_code']})"
        except Exception as exc:
            error_code = type(exc).__name__
            accounts[key].update({
                "status": "failed", "error_code": error_code,
                "error_message": "Unexpected collection error; inspect the error code.",
                "collected_at": now_kst(),
            })
            statuses[key].update({
                "status": "failed", "completed_at": now_kst(),
                "posts_requested": str(MAX_POSTS),
                "collection_completeness": "none",
                "collection_strategy": "",
                "posts_collected": "0",
                "error_code": error_code,
                "error_message": "Unexpected collection error; inspect the error code.",
                "api_status": "success" if api_succeeded else "failed",
                "data_completeness": (
                    assess_data_completeness(result)[0] if api_succeeded else "not_assessed"
                ),
                "missing_fields": (
                    json.dumps(assess_data_completeness(result)[1], ensure_ascii=False)
                    if api_succeeded else ""
                ),
                "error_type": "", "error_subcode": "", "http_status": "",
            })
            failed_this_run += 1
            event = f"Meta 계정 {key} 실패 ({error_code})"
        persist(accounts, posts, media, statuses, tags)
        update_summary(source, statuses, posts, media, tags, event)
        print(
            f"account {index}/{total} {key}: {statuses[key]['status']}; "
            f"posts={statuses[key].get('posts_collected', '0')}/{statuses[key].get('posts_requested', MAX_POSTS)}"
        )
        if halt_after_save:
            halted = True
            print(f"Meta collection safely halted after account {key} due to rate-limit/authentication error.")
            break
    outcome = "safely halted" if halted else "finished"
    unresolved_failed = sum(
        1 for item in targets if statuses[item["account_key"]].get("status") == "failed"
    )
    print(
        f"Meta collection {outcome}; success={completed}; failed_this_run={failed_this_run}; "
        f"skipped_prior_failures={skipped_failed}; unresolved_failed={unresolved_failed}; "
        f"posts={len(posts)}; media={len(media)}"
    )
    return 1 if halted or failed_this_run else 0


def vision_stage(source: list[dict[str, str]], source_hash: str) -> int:
    load_env_file()
    accounts, posts, media, statuses, tags = ensure_outputs(source, source_hash)
    api_key = os.getenv("ELICE_API_KEY", "").strip()
    base_url = os.getenv("ELICE_API_BASE_URL", "").strip()
    model_id = os.getenv("ELICE_MODEL", "helpy-v-reasoning-c").strip()
    missing = [name for name, value in (("ELICE_API_KEY", api_key), ("ELICE_API_BASE_URL", base_url)) if not value]
    images = [
        row for row in media.values()
        if row.get("media_url")
        and row.get("media_type", "").upper() == "IMAGE"
        and row.get("media_role") != "carousel_container"
    ]
    if missing:
        update_summary(source, statuses, posts, media, tags, "Elice 분류 대기: " + ", ".join(missing))
        print("Vision classification not started; missing configuration: " + ", ".join(missing))
        return 2
    total = len(images)
    success = sum(1 for row in tags.values() if row.get("status") == "success")
    for index, item in enumerate(images, start=1):
        old = tags.get(item["media_id"])
        if old and old.get("status") == "success":
            continue
        try:
            result = classify_image(item["media_url"], base_url, api_key, model_id)
            row = {
                "media_id": item["media_id"], "post_id": item["post_id"],
                "account_key": item["account_key"], "username": item["username"],
                "country": item["country"], "analyzed_at": now_kst(),
                "model_id": model_id, "visual_summary": result.get("visual_summary", ""),
                "tags_json": json.dumps(result.get("tags", []), ensure_ascii=False),
                "nail_style": result.get("nail_style", ""),
                "dominant_colors": json.dumps(result.get("dominant_colors", []), ensure_ascii=False),
                "patterns": json.dumps(result.get("patterns", []), ensure_ascii=False),
                "finish": result.get("finish", ""), "shape": result.get("shape", ""),
                "confidence": result.get("confidence", ""), "status": "success",
                "error_code": "", "error_message": "",
            }
            success += 1
        except Exception as exc:
            code = exc.code if isinstance(exc, CollectorError) else type(exc).__name__
            message = (
                exc.message if isinstance(exc, CollectorError)
                else "Unexpected vision classification error; inspect the error code."
            )
            row = {
                "media_id": item["media_id"], "post_id": item["post_id"],
                "account_key": item["account_key"], "username": item["username"],
                "country": item["country"], "analyzed_at": now_kst(),
                "model_id": model_id, "visual_summary": "", "tags_json": "",
                "nail_style": "", "dominant_colors": "", "patterns": "",
                "finish": "", "shape": "", "confidence": "", "status": "failed",
                "error_code": safe_text(code, [api_key]),
                "error_message": safe_text(message, [api_key]),
            }
        tags[item["media_id"]] = row
        persist(accounts, posts, media, statuses, tags)
        update_summary(source, statuses, posts, media, tags, f"Elice 이미지 {item['media_id']} 처리 완료")
        print(f"image {index}/{total} {item['media_id']}: {row['status']}")
    failed = sum(1 for row in tags.values() if row.get("status") == "failed")
    update_summary(source, statuses, posts, media, tags, f"Elice 분류 완료: success={success}, failed={failed}")
    print(f"Vision classification finished; success={success}; failed={failed}; images={total}")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("meta", "vision", "smoke-test"), required=True)
    parser.add_argument(
        "--username",
        help="Alternate public professional Instagram username for smoke-test only.",
    )
    parser.add_argument(
        "--account-keys", nargs="+",
        help="Limit --stage meta to account_key values from the official account_list.csv.",
    )
    parser.add_argument(
        "--retry-account-keys", nargs="+",
        help="Manually retry only failed/partial accounts; preserves prior error history.",
    )
    args = parser.parse_args()
    try:
        source, source_hash = source_rows()
        if args.stage == "smoke-test":
            return smoke_test(source, args.username)
        if args.username:
            print("collector stopped; --username is only valid with --stage smoke-test", file=sys.stderr)
            return 2
        if args.account_keys and args.stage != "meta":
            print("collector stopped; --account-keys is only valid with --stage meta", file=sys.stderr)
            return 2
        if args.retry_account_keys and args.stage != "meta":
            print("collector stopped; --retry-account-keys is only valid with --stage meta", file=sys.stderr)
            return 2
        if args.account_keys and args.retry_account_keys:
            print("collector stopped; use either --account-keys or --retry-account-keys", file=sys.stderr)
            return 2
        with process_lock():
            if args.stage == "meta":
                return meta_stage(source, source_hash, args.account_keys, args.retry_account_keys)
            return vision_stage(source, source_hash)
    except CollectorError as exc:
        print(f"collector stopped; error_code={safe_text(exc.code, [])}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
