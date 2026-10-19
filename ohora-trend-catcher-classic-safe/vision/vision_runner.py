#!/usr/bin/env python3
"""OHORA: independently analyze collected Instagram post images and captions.

Default: offline preview, no API requests or writes. --live calls a user-configured
OpenAI-compatible /chat/completions endpoint. Source datasets are NEVER mutated.
Run from repo root, e.g. python vision/vision_runner.py --source experiments/results/full_294
"""
from __future__ import annotations

import argparse
import base64
import csv
from contextlib import contextmanager, closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "experiments" / "results" / "full_294"
DEFAULT_OUTPUT = REPO / "experiments" / "results" / "vision"
DEFAULT_ENV = REPO / "vision" / ".env.local"
PROMPT_VERSION = "ohora-kq3-design-v1"
FIELD_NAMES = ("color", "technique", "texture", "motif", "season", "use")
SYSTEM_PROMPT = (
    "You analyze Instagram nail-design posts for OHORA product planners. "
    "Inspect the provided image(s) first, then use the caption only as supplemental context. "
    "Never infer unobservable details. Images may show product ads, faces, or video thumbnails. "
    "Respond with a single valid JSON object, no markdown: "
    '{"is_design_post":true,"visual_summary":"brief visible evidence",'
    '"color":["pink"],"technique":["gradient"],"texture":["glossy"],'
    '"motif":[],"season":[],"use":[],"confidence":0.8,'
    '"limitations":"optional uncertainty or video thumbnail caveat"}. '
    "is_design_post must be a JSON boolean. Each of color/technique/texture/motif/season/use "
    "must be an array of concise lowercase category strings, empty if unsupported. "
    "confidence must be a number 0..1. For non-design posts, tags should be empty. "
    "Do not claim a full video was analyzed when only a thumbnail was provided."
)


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


class ProviderError(Exception):
    def __init__(self, code: str, http_status: int | None = None, stop: bool = False):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.stop = stop


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def settings(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            out[key.strip()] = val.strip().strip('"\'')
    # OS-provided keys win, do not print either source.
    out.update(os.environ)
    return out


def provider_from(cfg: dict[str, str], prefix: str = "VISION") -> Provider:
    return Provider(prefix.lower(), cfg.get(prefix + "_BASE_URL", "").strip(),
                    cfg.get(prefix + "_API_KEY", "").strip(),
                    cfg.get(prefix + "_MODEL", "").strip())


def endpoint_url(base: str) -> str:
    if not base or not base.startswith("https://"):
        raise ValueError("Configured vision endpoint must be an HTTPS URL")
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    # OpenAI-compatible API convention when provider gives domain only
    return base + "/v1/chat/completions"


def read_inputs(source: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source.is_file() and source.suffix.lower() in {".sqlite", ".db"}:
        dbpath = source
    elif source.is_dir() and (source / "collection.sqlite").is_file():
        dbpath = source / "collection.sqlite"
    else:
        dbpath = None
    if dbpath:
        with closing(sqlite3.connect(f"file:{dbpath.resolve().as_posix()}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            posts = [dict(x) for x in conn.execute("SELECT * FROM posts")]
            media = [dict(x) for x in conn.execute("SELECT * FROM media")]
    elif source.is_dir():
        def read(name: str) -> list[dict]:
            with (source / name).open("r", encoding="utf-8-sig", newline="") as fp:
                return list(csv.DictReader(fp))
        posts, media = read("posts.csv"), read("media.csv")
    else:
        raise ValueError("--source must be a collection.sqlite file or folder with posts.csv and media.csv")
    ids = [str(p.get("post_id") or "") for p in posts]
    if any(not k for k in ids) or len(ids) != len(set(ids)):
        raise ValueError("Missing or duplicated post_id in source")
    m_ids = [str(m.get("media_id") or "") for m in media]
    if any(not k for k in m_ids) or len(m_ids) != len(set(m_ids)):
        raise ValueError("Missing or duplicated media_id in source")
    return posts, media


def valid_image_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://") and not any(c in value for c in '\r\n\t')


def select_images(items: list[dict], cap: int) -> list[dict]:
    """Prefer all actual images over video thumbnails; representative carousel slots."""
    eligible: list[dict] = []
    for m in items:
        if str(m.get("media_role") or "") == "carousel_container":
            continue
        t = str(m.get("media_type") or "").upper()
        media_url = m.get("media_url")
        thumb_url = m.get("thumbnail_url")
        if t == "IMAGE" and valid_image_url(media_url):
            url, basis = media_url, "image"
        elif t == "VIDEO" and valid_image_url(thumb_url):
            url, basis = thumb_url, "video_thumbnail"
        elif t != "VIDEO" and valid_image_url(media_url):
            url, basis = media_url, "image"
        elif valid_image_url(thumb_url):
            url, basis = thumb_url, "video_thumbnail"
        else:
            continue
        eligible.append({"media_id": str(m["media_id"]), "url": url, "basis": basis,
                         "role": str(m.get("media_role") or ""), "sort_order": int(m.get("sort_order") or 0)})
    eligible.sort(key=lambda m: (m["sort_order"], m["media_id"]))
    if len(eligible) <= cap:
        return eligible
    # First, middle, last to reflect possible distinct carousel designs.
    if cap == 1:
        indexes = [0]
    elif cap == 2:
        indexes = [0, len(eligible)-1]
    else:
        indexes = [round(i*(len(eligible)-1)/(cap-1)) for i in range(cap)]
    return [eligible[i] for i in dict.fromkeys(indexes)]


def fingerprint(post: dict, images: list[dict], model: str, max_images: int) -> str:
    # Do not fingerprint signed/CDN URLs: URL rotation must not trigger reanalysis.
    obj = {"post_id": post["post_id"], "caption": (post.get("caption") or "")[:1800],
           "images": [(x["media_id"], x["basis"]) for x in images],
           "max_images": max_images, "model": model, "prompt": PROMPT_VERSION}
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()



@contextmanager
def process_lock(folder: Path):
    """Prevent concurrent paid analysis workers from processing the same posts."""
    path = folder / ".vision.lock"
    with path.open("a+b") as fp:
        if path.stat().st_size == 0:
            fp.write(b"0")
            fp.flush()
        fp.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another vision analysis process is active") from None
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def output_database(folder: Path) -> sqlite3.Connection:
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "vision.sqlite")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS post_analysis (
        post_id TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
        input_fingerprint TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
        analyzed_at TEXT, last_attempt_at TEXT,
        country TEXT, account_key TEXT, username TEXT, timestamp TEXT, permalink TEXT,
        caption TEXT, media_type TEXT, likes INTEGER, comments INTEGER, engagement INTEGER,
        visual_summary TEXT, is_design_post INTEGER, confidence REAL,
        color_json TEXT, technique_json TEXT, texture_json TEXT, motif_json TEXT,
        season_json TEXT, use_json TEXT, limitations TEXT,
        selected_media_json TEXT, http_status INTEGER, error_code TEXT,
        PRIMARY KEY(post_id,model,prompt_version)
    );
    CREATE TABLE IF NOT EXISTS selected_media (
        post_id TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
        media_id TEXT NOT NULL, role TEXT, basis TEXT, sort_order INTEGER,
        PRIMARY KEY(post_id,model,prompt_version,media_id)
    );
    CREATE TABLE IF NOT EXISTS run_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
        mode TEXT, model TEXT, source TEXT, attempted INTEGER, succeeded INTEGER,
        failed INTEGER, unavailable INTEGER, skipped_cached INTEGER, stopped_reason TEXT
    );
    """)
    return db


def extract_content(response: dict) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("no_choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    if not isinstance(content, str) or not content.strip():
        raise ProviderError("empty_content")
    return content.strip()


def parse_response(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
    try:
        obj = json.loads(content)
    except ValueError:
        # Some gateways surround otherwise valid JSON with brief prose. Recover
        # one complete JSON object; do not guess at or repair truncated JSON.
        start = content.find("{")
        if start < 0:
            raise ProviderError("invalid_json") from None
        try:
            obj, used = json.JSONDecoder().raw_decode(content[start:])
        except ValueError:
            raise ProviderError("invalid_json") from None
        remainder = content[start + used:]
        if "{" in remainder or "}" in remainder or "}" in content[:start]:
            raise ProviderError("invalid_json") from None
    if not isinstance(obj, dict) or type(obj.get("is_design_post")) is not bool:
        raise ProviderError("invalid_schema")
    result: dict[str, Any] = {}
    for field in FIELD_NAMES:
        value = obj.get(field)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ProviderError("invalid_schema")
        result[field] = sorted({v.strip().lower()[:64] for v in value if v.strip()})[:12]
    try:
        conf = float(obj.get("confidence"))
        if not 0 <= conf <= 1:
            raise ValueError()
    except (TypeError, ValueError):
        raise ProviderError("invalid_confidence") from None
    for key in ("visual_summary", "limitations"):
        value = obj.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ProviderError("invalid_schema")
        result[key] = value[:1000]
    result["confidence"] = conf
    result["is_design_post"] = obj["is_design_post"]
    if not obj["is_design_post"]:
        for key in FIELD_NAMES:
            result[key] = []
    return result



def inline_image_url(url: str, timeout: int = 20, max_bytes: int = 5_000_000) -> str:
    """Optional temporary image fetch: no image file is saved to disk."""
    if not valid_image_url(url):
        raise ProviderError("invalid_image_url")
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(max_bytes + 1)
            mimetype = response.headers.get_content_type() if response.headers else ""
    except HTTPError as exc:
        # Do not show the temporary CDN URL, it may include signed parameters.
        raise ProviderError("image_fetch_http_" + str(exc.code), exc.code) from None
    except (URLError, TimeoutError, OSError):
        raise ProviderError("image_fetch_network_error") from None
    if len(payload) > max_bytes:
        raise ProviderError("image_too_large")
    # Content type and actual bytes must both be compatible with image inputs.
    signatures = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"),
                  (b"RIFF", "image/webp"))
    actual = next((mime for prefix, mime in signatures if payload.startswith(prefix)), "")
    if payload.startswith(b"RIFF") and payload[8:12] != b"WEBP":
        actual = ""
    if actual not in {"image/jpeg", "image/png", "image/webp"}:
        raise ProviderError("image_invalid_format")
    return "data:" + actual + ";base64," + base64.b64encode(payload).decode("ascii")


def analyze(post: dict, images: list[dict], provider: Provider, timeout: int,
            image_transfer: str = "remote", max_tokens: int = 1500) -> dict:
    endpoint = endpoint_url(provider.base_url)
    caption = (post.get("caption") or "")[:1800]
    media_content: list[dict] = [{"type": "text", "text": f"Caption (untrusted social text): {caption}\nVisual basis: " +
                                             ", ".join(x["basis"] for x in images)}]
    for item in images:
        asset = inline_image_url(item["url"]) if image_transfer == "inline" else item["url"]
        media_content.append({"type": "image_url", "image_url": {"url": asset}})
    payload = {"model": provider.model, "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": media_content}],
        "temperature": 0.1, "max_tokens": max_tokens}
    req = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
                  headers={"Authorization": "Bearer " + provider.api_key,
                           "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as res:
            raw = res.read(2_000_000)
    except HTTPError as exc:
        # Never persist or print upstream body, token, signed CDN URL or request.
        status = exc.code
        stop = status in {400, 401, 403, 404, 413, 422, 429}
        raise ProviderError("provider_http_"+str(status), status, stop=stop) from None
    except (URLError, TimeoutError, OSError):
        raise ProviderError("provider_transport_error", stop=True) from None
    try:
        decoded = json.loads(raw)
    except ValueError:
        raise ProviderError("invalid_provider_json", stop=True) from None
    if not isinstance(decoded, dict):
        raise ProviderError("invalid_provider_json", stop=True)
    choices = decoded.get("choices")
    if (isinstance(choices, list) and choices and isinstance(choices[0], dict)
            and choices[0].get("finish_reason") in {"length", "max_tokens"}):
        raise ProviderError("truncated_response")
    return parse_response(extract_content(decoded))


def safe_num(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def persist_post(db: sqlite3.Connection, post: dict, pics: list[dict], model: str,
                 sig: str, status: str, result: dict | None, error: ProviderError | None) -> None:
    key = (str(post["post_id"]), model, PROMPT_VERSION)
    prev = db.execute("SELECT attempts FROM post_analysis WHERE post_id=? AND model=? AND prompt_version=?", key).fetchone()
    attempts = (prev[0] if prev else 0) + 1
    likes, comments = safe_num(post.get("like_count")), safe_num(post.get("comments_count"))
    engagement = (likes + comments) if (likes is not None and comments is not None) else None
    values: dict[str, Any] = {
        "post_id": key[0], "model": model, "prompt_version": PROMPT_VERSION,
        "input_fingerprint": sig, "status": status, "attempts": attempts,
        "analyzed_at": now() if status == "success" else None, "last_attempt_at": now(),
        "country": post.get("country") or "", "account_key": post.get("account_key") or "",
        "username": post.get("username") or "", "timestamp": post.get("timestamp") or "",
        "permalink": post.get("permalink") or "", "caption": post.get("caption") or "",
        "media_type": post.get("media_type") or "", "likes": likes,
        "comments": comments, "engagement": engagement,
        "visual_summary": (result or {}).get("visual_summary", ""),
        "is_design_post": int(result["is_design_post"]) if result else None,
        "confidence": (result or {}).get("confidence"),
        "limitations": (result or {}).get("limitations", ""),
        "selected_media_json": json.dumps([{k:p[k] for k in ("media_id", "basis", "role")}
                                            for p in pics], ensure_ascii=False),
        "http_status": error.http_status if error else None,
        "error_code": error.code if error else None,
    }
    for field in FIELD_NAMES:
        values[field + "_json"] = json.dumps((result or {}).get(field, []), ensure_ascii=False)
    cols = list(values)
    params = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("post_id", "model", "prompt_version"))
    with db:
        db.execute(f"INSERT INTO post_analysis ({','.join(cols)}) VALUES ({params}) "
                   f"ON CONFLICT(post_id,model,prompt_version) DO UPDATE SET {updates}", list(values.values()))
        db.execute("DELETE FROM selected_media WHERE post_id=? AND model=? AND prompt_version=?", key)
        for p in pics:
            db.execute("INSERT INTO selected_media (post_id,model,prompt_version,media_id,role,basis,sort_order) "
                       "VALUES (?,?,?,?,?,?,?)", (*key, p["media_id"], p["role"], p["basis"], p["sort_order"]))


def export(db: sqlite3.Connection, folder: Path) -> None:
    for table, filename in (("post_analysis", "post_analysis.csv"),
                            ("selected_media", "selected_media.csv")):
        cur = db.execute(f"SELECT * FROM {table} ORDER BY post_id")
        headers = [c[0] for c in cur.description]
        fd, name = tempfile.mkstemp(prefix=".vision_", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(headers)
                writer.writerows(cur.fetchall())
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(name, folder / filename)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    counts = dict(db.execute("SELECT status,COUNT(*) FROM post_analysis GROUP BY status").fetchall())
    summary = {"exported_at_utc": now(), "counts": counts,
               "note": "Images and captions were evaluated by post; per-media tags are not independently inferred."}
    fd, name = tempfile.mkstemp(prefix=".vision_summary_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(name, folder / "vision_summary.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(args: argparse.Namespace) -> int:
    if not 1 <= args.max_images <= 5:
        raise ValueError("--max-images must be 1..5")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be >=1")
    if args.delay_seconds < 0:
        raise ValueError("--delay-seconds must be nonnegative")
    if not 1 <= args.timeout <= 300:
        raise ValueError("--timeout must be 1..300 seconds")
    source = args.source.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    if output == source or output == source.parent or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("The output must be separate from the source dataset")
    posts, media = read_inputs(source)
    media_by_post: dict[str, list[dict]] = {}
    for m in media:
        media_by_post.setdefault(str(m.get("post_id") or ""), []).append(m)
    posts.sort(key=lambda p: (str(p.get("timestamp") or ""), str(p["post_id"])), reverse=True)
    if args.post_id is not None:
        # Exact post selection prevents a --limit 1 retry from billing a different,
        # previously unanalysed post simply because it sorts first.
        posts = [p for p in posts if str(p["post_id"]) == args.post_id]
        if not posts:
            raise ValueError("Requested --post-id does not exist in source collection")
    config = settings(args.env_file.expanduser())
    provider = provider_from(config, "VISION" if args.provider == "primary" else "VISION_FALLBACK")
    # Allow offline setup before key, and never reveal key in error messages.
    if not args.live:
        capable = sum(bool(select_images(media_by_post.get(str(p["post_id"]), []), args.max_images)) for p in posts)
        print(f"OFFLINE PREVIEW: source_posts={len(posts)}, media_rows={len(media)}, "
              f"image_or_thumbnail_eligible_posts={capable}, no_media={len(posts)-capable}")
        print(f"Provider fields present: url={bool(provider.base_url)}, model={bool(provider.model)}, "
              f"key={bool(provider.api_key)}. No API calls and no files modified.")
        return 0
    if not (provider.api_key and provider.model and provider.base_url):
        raise ValueError("Missing VISION[_FALLBACK] credentials or model in local env file")
    endpoint_url(provider.base_url)
    # Prevent accidental writing into the original CSV collection directory.
    output.mkdir(parents=True, exist_ok=True)
    with process_lock(output):
        return run_locked(args, source, output, posts, media_by_post, provider)


def run_locked(args: argparse.Namespace, source: Path, output: Path, posts: list[dict],
               media_by_post: dict[str, list[dict]], provider: Provider) -> int:
    db = output_database(output)
    attempted = succeeded = failed = unavailable = cached = 0
    stop_reason = ""
    consecutive_errors = 0
    started = now()
    log_id = None
    try:
        with db:
            cur = db.execute("INSERT INTO run_log (started_at,mode,model,source) VALUES (?,?,?,?)",
                             (started, "live", provider.model, str(source)))
            log_id = cur.lastrowid
        for post in posts:
            media_images = select_images(media_by_post.get(str(post["post_id"]), []), args.max_images)
            sig = fingerprint(post, media_images, provider.model, args.max_images)
            old = db.execute("SELECT input_fingerprint,status FROM post_analysis "
                             "WHERE post_id=? AND model=? AND prompt_version=?",
                             (str(post["post_id"]), provider.model, PROMPT_VERSION)).fetchone()
            if old and old[0] == sig and (old[1] == "success" or
                                         (old[1] in {"failed", "unavailable"} and not args.retry_failed)):
                cached += 1
                continue
            if args.limit is not None and attempted >= args.limit:
                break
            attempted += 1
            if not media_images:
                unavailable += 1
                persist_post(db, post, [], provider.model, sig, "unavailable", None,
                             ProviderError("no_usable_image_url"))
                continue
            try:
                try:
                    result = analyze(post, media_images, provider, args.timeout, args.image_transfer)
                except ProviderError as first_error:
                    # Only a malformed/truncated model output gets ONE bounded
                    # second attempt. Authentication, rate and network issues stop.
                    if first_error.code not in {"invalid_json", "invalid_schema",
                                                "invalid_confidence", "empty_content",
                                                "truncated_response"}:
                        raise
                    print(f"Malformed model output for post {post['post_id']}; "
                          "one retry with larger output budget.", flush=True)
                    result = analyze(post, media_images, provider, args.timeout,
                                     args.image_transfer, max_tokens=2200)
                persist_post(db, post, media_images, provider.model, sig, "success", result, None)
                succeeded += 1
                consecutive_errors = 0
            except ProviderError as err:
                persist_post(db, post, media_images, provider.model, sig, "failed", None, err)
                failed += 1
                consecutive_errors += 1
                # Stop & Pivot: 2 consecutive failed requests warrant diagnosis.
                if err.stop or consecutive_errors >= 2:
                    stop_reason = err.code
                    print(f"Provider stopped safely: {err.code}; remaining posts untouched.")
                    break
            if args.delay_seconds > 0:
                time.sleep(args.delay_seconds)
        return 3 if stop_reason else (1 if failed else 0)
    finally:
        if log_id is not None:
            with db:
                db.execute("UPDATE run_log SET finished_at=?,attempted=?,succeeded=?,failed=?,"
                           "unavailable=?,skipped_cached=?,stopped_reason=? WHERE id=?",
                           (now(), attempted, succeeded, failed, unavailable, cached, stop_reason, log_id))
        export(db, output)
        db.close()
        print(f"Vision results saved: attempted={attempted}, success={succeeded}, "
              f"failed={failed}, no_media={unavailable}, cached={cached}; output={output}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    p.add_argument("--provider", choices=("primary", "fallback"), default="primary")
    p.add_argument("--max-images", type=int, default=3)
    p.add_argument("--image-transfer", choices=("remote", "inline"), default="remote",
                   help="remote forwards media URL; inline temporarily reads and encodes bytes")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--limit", type=int, default=None, help="max uncached posts processed this run")
    p.add_argument("--delay-seconds", type=float, default=0.4)
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--post-id", type=str, default=None,
                   help="target exactly this post ID, skipping every other source post")
    p.add_argument("--live", action="store_true", help="authorize actual external image model API calls")
    args = p.parse_args(argv)
    try:
        return run(args)
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        # Never print raw exception objects with credentials or private media URLs.
        print(f"Vision runner stopped safely ({type(exc).__name__}); check --source/--env-file and config.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
