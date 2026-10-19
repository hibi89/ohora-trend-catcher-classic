#!/usr/bin/env python3
"""Prepare a read-only, Excel-friendly CSV+ZIP handoff from an existing OHORA collection.

Does not call Meta/OpenAI, re-collect data, change source files, or include .env files.
Supports both the legacy kq3_294_collection CSVs and the experiment collection.sqlite.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile, ZIP_DEFLATED

KST = timezone(timedelta(hours=9))
TABLES = ("accounts", "posts", "media")
STATUS_COLS = ("account_key", "username", "country", "status", "coverage",
               "posts_collected", "error_code", "http_status")
POST_COLS = (
    "post_id", "account_key", "username", "country", "timestamp", "caption",
    "media_type", "media_product_type", "permalink", "like_count",
    "comments_count", "engagement_count", "engagement_rate_pct",
    "media_count", "collected_at",
)
MEDIA_COLS = (
    "media_id", "post_id", "parent_media_id", "account_key", "username",
    "country", "media_role", "media_type", "media_url", "thumbnail_url",
    "sort_order", "collected_at",
)
ACCOUNT_COLS = (
    "account_key", "username", "country", "image_url", "ig_user_id",
    "followers_count", "media_count", "posts_collected", "status",
    "error_code", "error_message", "collected_at",
)
COVERAGE_COLS = (
    "account_key", "username", "country", "status", "coverage",
    "all_posts_in_source", "latest5_in_source", "missing_like_count_in_source",
    "missing_comment_count_in_source", "error_code",
)


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_collection(source: Path) -> tuple[dict[str, list[dict]], str]:
    if source.is_file() and source.suffix == ".sqlite":
        database = source
    elif source.is_dir() and (source / "collection.sqlite").is_file():
        database = source / "collection.sqlite"
    else:
        database = None

    if database is not None:
        uri = "file:" + database.resolve().as_posix() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as con:
            con.row_factory = sqlite3.Row
            tables = {x[0] for x in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not set(TABLES).issubset(tables):
                raise ValueError("SQLite lacks accounts/posts/media tables")
            data = {t: [dict(r) for r in con.execute("SELECT * FROM " + t)]
                    for t in TABLES}
        return data, "sqlite"

    if source.is_dir() and all((source / (t + ".csv")).is_file() for t in TABLES):
        return {t: read_csv(source / (t + ".csv")) for t in TABLES}, "csv"

    raise ValueError("Source requires collection.sqlite or accounts.csv/posts.csv/media.csv")



def combine_collections(primary: dict[str, list[dict]],
                        supplement: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Prefer the richer primary account snapshot on overlaps; add only new accounts.

    Both sources must have the same official roster. The supplement is a
    one-post experiment: some of its accounts may subsequently be recollected
    with five posts by the primary collector. In that case, retain primary
    account/posts/media and skip the entire overlapping supplemental account.
    """
    original_accounts = {str(a["account_key"]): a for a in primary["accounts"]}
    extra_accounts = {str(a["account_key"]): a for a in supplement["accounts"]}
    if len(original_accounts) != len(primary["accounts"]) or (
            len(extra_accounts) != len(supplement["accounts"])):
        raise ValueError("Duplicate account keys in a merge source")
    if original_accounts.keys() != extra_accounts.keys():
        raise ValueError("Supplement account roster differs from primary")
    for key, base in original_accounts.items():
        second = extra_accounts[key]
        if (str(base.get("country")) != str(second.get("country"))
                or str(base.get("username")).casefold() !=
                str(second.get("username")).casefold()):
            raise ValueError("Country or username mismatch for supplement account")

    new_accounts: list[dict] = []
    add_keys: set[str] = set()
    overlap_keys: set[str] = set()
    recovered_keys: set[str] = set()
    for a in primary["accounts"]:
        key = str(a["account_key"])
        extra = extra_accounts[key]
        base_status = str(a.get("status") or "pending")
        extra_status = str(extra.get("status") or "pending")
        if extra_status in {"success", "partial"}:
            if base_status in {"success", "partial"}:
                # Existing five-post snapshot is authoritative. A prior
                # one-post snapshot from the same account is now redundant.
                overlap_keys.add(key)
                new_accounts.append(dict(a, collection_source="primary"))
            elif base_status in {"pending", "rate_limited", "failed"}:
                add_keys.add(key)
                if base_status == "failed":
                    # A failed five-post request does not invalidate an earlier
                    # successful one-post result from this same official account.
                    recovered_keys.add(key)
                    new_accounts.append(dict(
                        extra, collection_source="supplement",
                        primary_latest5_status="failed",
                        primary_latest5_error_code=a.get("error_code") or ""))
                else:
                    new_accounts.append(dict(extra, collection_source="supplement"))
            else:
                raise ValueError("Unsupported primary account status during merge")
        else:
            new_accounts.append(dict(a, collection_source="primary"))

    extra_posts = supplement["posts"]
    extra_media = supplement["media"]
    expected_keys = add_keys | overlap_keys
    if any(str(p.get("account_key")) not in expected_keys for p in extra_posts):
        raise ValueError("Supplement post belongs to an ineligible account")
    if any(str(m.get("account_key")) not in expected_keys for m in extra_media):
        raise ValueError("Supplement media belongs to an ineligible account")
    included_posts = [p for p in extra_posts if str(p["account_key"]) in add_keys]
    included_media = [m for m in extra_media if str(m["account_key"]) in add_keys]
    primary_ids = {str(p["post_id"]) for p in primary["posts"]}
    primary_media_ids = {str(m["media_id"]) for m in primary["media"]}
    if any(str(p.get("post_id")) in primary_ids for p in included_posts):
        raise ValueError("Duplicate post ID across unrelated source accounts")
    if any(str(m.get("media_id")) in primary_media_ids for m in included_media):
        raise ValueError("Duplicate media ID across unrelated source accounts")

    return {
        "accounts": new_accounts,
        "posts": [dict(p, collection_source="primary") for p in primary["posts"]]
                 + [dict(p, collection_source="supplement") for p in included_posts],
        "media": [dict(m, collection_source="primary") for m in primary["media"]]
                 + [dict(m, collection_source="supplement") for m in included_media],
        "_merge_meta": {
            "supplement_accounts_added": len(add_keys),
            "supplement_accounts_overlapped": len(overlap_keys),
            "supplement_accounts_restored_after_primary_failure": len(recovered_keys),
            "supplement_post_rows_included": len(included_posts),
            "supplement_post_rows_ignored_overlap": len(extra_posts) - len(included_posts),
            "supplement_media_rows_included": len(included_media),
            "supplement_media_rows_ignored_overlap": len(extra_media) - len(included_media),
            "merge_precedence": "primary_over_supplement_per_account",
        },
    }


def require_columns(rows: list[dict], required: set[str], name: str) -> None:
    if rows and not required.issubset(rows[0]):
        raise ValueError("Missing required columns in " + name)


def prepare(data: dict[str, list[dict]], latest_n: int) -> tuple[dict[str, list[dict]], dict]:
    accounts, posts, media = (data[k] for k in TABLES)
    require_columns(accounts, {"account_key", "username", "country"}, "accounts")
    require_columns(posts, {"post_id", "account_key", "timestamp"}, "posts")
    require_columns(media, {"media_id", "post_id"}, "media")
    if not accounts:
        raise ValueError("No accounts in source; refusing an uninformative handoff")
    if not posts:
        raise ValueError("No collected posts in source; refusing an empty handoff ZIP")
    account_ids = [str(a.get("account_key") or "") for a in accounts]
    post_ids = [str(p.get("post_id") or "") for p in posts]
    media_ids = [str(m.get("media_id") or "") for m in media]
    for name, keys in (("accounts", account_ids), ("posts", post_ids), ("media", media_ids)):
        if "" in keys or len(keys) != len(set(keys)):
            raise ValueError("Missing or duplicate ID in " + name)
    accounts_by_id = {str(a["account_key"]): a for a in accounts}
    all_posts_by_account: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        key = str(p["account_key"])
        if key not in accounts_by_id:
            raise ValueError("Post references missing account")
        all_posts_by_account[key].append(p)
    known_post_ids = set(post_ids)
    for m in media:
        if str(m["post_id"]) not in known_post_ids:
            raise ValueError("Media references missing post")

    # Source timestamps are Meta ISO strings; ISO lexical ordering is suitable
    # for normal Graph timestamps, with ID as tie-breaker. Preserve source rows.
    recent: list[dict] = []
    for key in account_ids:
        by_time = sorted(all_posts_by_account[key],
                         key=lambda x: (str(x.get("timestamp") or ""), str(x["post_id"])),
                         reverse=True)
        recent.extend(by_time[:latest_n])
    recent.sort(key=lambda x: (
        str(x.get("country") or ""),
        str(x.get("account_key") or ""),
        str(x.get("timestamp") or "")), reverse=False)
    recent_ids = {str(x["post_id"]) for x in recent}
    recent_media = [m for m in media if str(m["post_id"]) in recent_ids]
    status_histogram = Counter(str(a.get("status") or "unknown") for a in accounts)
    coverage = []
    for a in accounts:
        key = str(a["account_key"])
        ap = all_posts_by_account[key]
        rcount = sum(str(p["post_id"]) in recent_ids for p in ap)
        coverage.append({
            "account_key": key,
            "username": a.get("username"),
            "country": a.get("country"),
            "status": a.get("status") or "unknown",
            "coverage": a.get("coverage") or "",
            "all_posts_in_source": len(ap),
            "latest5_in_source": rcount,
            "missing_like_count_in_source": sum(
                p.get("like_count") in ("", None) for p in ap),
            "missing_comment_count_in_source": sum(
                p.get("comments_count") in ("", None) for p in ap),
            "error_code": a.get("error_code") or "",
        })
    source_countries = Counter(str(a.get("country") or "") for a in accounts)
    covered_countries = Counter(str(a.get("country") or "") for a in accounts
                                if all_posts_by_account[str(a["account_key"])])
    latest_countries = Counter(str(p.get("country") or "") for p in recent)
    summary = {
        "source_accounts": len(accounts),
        "accounts_with_posts": sum(bool(all_posts_by_account[a]) for a in account_ids),
        "source_posts": len(posts),
        "source_media_rows": len(media),
        "latest_n_requested": latest_n,
        "latest_post_rows": len(recent),
        "latest_media_rows": len(recent_media),
        "accounts_by_country": dict(source_countries),
        "covered_accounts_by_country": dict(covered_countries),
        "latest_posts_by_country": dict(latest_countries),
        "account_statuses": dict(status_histogram),
        "missing_like_count_source_posts": sum(
            p.get("like_count") in ("", None) for p in posts),
        "missing_comment_count_source_posts": sum(
            p.get("comments_count") in ("", None) for p in posts),
    }
    outputs = {
        "accounts.csv": accounts,
        "posts_all_available.csv": posts,
        "posts_latest5_per_account.csv": recent,
        "media_all_available.csv": media,
        "media_latest5_per_account.csv": recent_media,
        "account_coverage.csv": coverage,
    }
    return outputs, summary


def csv_bytes(rows: list[dict], preferred: tuple[str, ...]) -> bytes:
    # BOM supports Excel's default Korean Windows CSV detection.
    extra = sorted({key for row in rows for key in row if key not in preferred})
    columns = list(preferred) + extra
    mem = io.StringIO(newline="")
    writer = csv.DictWriter(mem, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Protect Excel/LibreOffice users against spreadsheet formula injection
        # in untrusted social text. This alters only the DELIVERY COPY.
        sanitized = {}
        for key, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(
                    ("=", "+", "-", "@", "\t", "\r", "\n")):
                sanitized[key] = "'" + value
            else:
                sanitized[key] = value
        writer.writerow(sanitized)
    return mem.getvalue().encode("utf-8-sig")


def build_bundle(source: Path, output_dir: Path, latest_n: int = 5,
                 supplement: Path | None = None) -> tuple[Path, dict]:
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == source or source in output_dir.parents:
        raise ValueError("Output directory must not be inside the source collection")
    if latest_n < 1 or latest_n > 50:
        raise ValueError("latest_n must be 1..50")
    data, origin_format = load_collection(source)
    if supplement is not None:
        supplement = supplement.expanduser().resolve()
        if supplement == source:
            raise ValueError("Supplement must differ from primary source")
        if supplement == output_dir or (supplement.is_dir() and supplement in output_dir.parents):
            raise ValueError("Output directory must not be inside supplemental source")
        # Verify both inputs independently before combining. All reads are read-only.
        prepare(data, latest_n)
        additional, extra_format = load_collection(supplement)
        prepare(additional, latest_n)
        primary_post_count = len(data["posts"])
        extra_post_count = len(additional["posts"])
        data = combine_collections(data, additional)
        merge_meta = data["_merge_meta"]
        origin_format += " + " + extra_format
    outputs, summary = prepare(data, latest_n)
    summary["source_format"] = origin_format
    if supplement is not None:
        summary["merged_from_two_sources"] = True
        summary["primary_source_posts"] = primary_post_count
        summary["supplement_source_posts"] = extra_post_count
        summary["source_directory_names"] = [source.name, supplement.name]
        summary["posts_by_collection_source"] = {
            "primary": primary_post_count,
            "supplement_in_source": extra_post_count,
            "supplement_included": merge_meta["supplement_post_rows_included"]}
        summary.update(merge_meta)
    summary["created_at_kst"] = datetime.now(KST).isoformat(timespec="seconds")
    # Never include a private filesystem path, API secret, model key or raw request logs.
    summary["source_directory_name"] = source.name
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / ("OHORA_Hongju_handoff_" + stamp + ".zip")
    if archive.exists():
        raise ValueError("Handoff already exists with this timestamp; wait before rerunning")

    readme = (
        "OHORA Trend Catcher — 홍주님 데이터 전달 안내\n"
        "생성: " + summary["created_at_kst"] + "\n\n"
        "전체 계정: " + str(summary["source_accounts"]) + "\n"
        + ("두 개의 수집 원본을 안전하게 병합한 전달본입니다.\n"
           "첫 번째 원본은 계정당 최대 5개, 추가 원본은 계정당 최대 1개를 수집했습니다.\n"
           if supplement is not None else "")
        + ("중복 계정 " + str(summary["supplement_accounts_overlapped"])
           + "개는 기존 5개 수집본을 우선하여 제외했습니다.\n"
           if supplement is not None else "")
        + "게시물이 확보된 계정: " + str(summary["accounts_with_posts"]) + "\n"
        "현재 수집 원본 게시물: " + str(summary["source_posts"]) + "\n"
        "계정별 최근 " + str(latest_n) + "개 추출: " + str(summary["latest_post_rows"]) + "\n"
        "이미지/동영상 미디어 행: " + str(summary["source_media_rows"]) + "\n\n"
        "posts_latest5_per_account.csv: 이 소스에 포함된 게시물 중 계정별 가장 최근 "
        + str(latest_n) + "건. 미수집 계정은 0건이며 294개 전체 확보로 오해하지 말 것.\n"
        "posts_all_available.csv: 선택한 수집 원본에 있는 전체 게시물.\n"
        "media_latest5_per_account.csv: 최신 게시물에 연결된 이미지 및 영상 썸네일 메타데이터.\n"
        "media_all_available.csv: 소스에 저장된 전체 미디어 메타데이터.\n"
        "accounts.csv: 수집 계정 정보 및 당시의 팔로워 수.\n"
        "account_coverage.csv: 계정별 성공/실패 및 실제 확보 건수, 결측 수.\n"
        "manifest.json: 전체 수치와 국가별 커버리지.\n\n"
        "주의: 원본은 건드리지 않았으며 분석 당시 수집 스냅샷입니다.\n"
        "like_count/comments_count의 빈칸은 0이 아니라 미수집 또는 응답 미제공입니다.\n"
        "참여율은 수집 시점 팔로워 수 기준 참고값이며 구매 전환율이 아닙니다.\n"
        "SNS 미디어 URL은 만료되거나 접근권한으로 열리지 않을 수 있습니다.\n"
        "게시물 ID는 Excel에서 숫자로 자동 변환하면 정밀도가 손실될 수 있습니다."
        " 가져오기 기능에서 텍스트 열로 지정하세요.\n"
        "악성 수식으로 시작하는 SNS 텍스트는 CSV 전달 사본에서 작은따옴표를 앞에 붙여"
        " 스프레드시트 수식 실행을 방지합니다. 원본 데이터는 수정하지 않았습니다.\n"
        "프로필과 게시물은 공개 수집 자료이며 API 자격정보는 포함하지 않습니다.\n"
        "이 묶음은 294개 전체 수집의 완료나 이미지분석 완료를 보증하지 않습니다.\n"
    )
    schemas = {
        "accounts.csv": ACCOUNT_COLS,
        "posts_all_available.csv": POST_COLS,
        "posts_latest5_per_account.csv": POST_COLS,
        "media_all_available.csv": MEDIA_COLS,
        "media_latest5_per_account.csv": MEDIA_COLS,
        "account_coverage.csv": COVERAGE_COLS,
    }
    with ZipFile(archive, mode="x", compression=ZIP_DEFLATED, compresslevel=6) as z:
        for filename, rows in outputs.items():
            z.writestr(filename, csv_bytes(rows, schemas[filename]))
        z.writestr("manifest.json", json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"))
        z.writestr("README_데이터안내.txt", readme.encode("utf-8-sig"))
    return archive, summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("experiments/results/hongju_delivery"))
    parser.add_argument("--latest-n", type=int, default=5)
    parser.add_argument("--supplement", type=Path, default=None,
                        help="optional second, disjoint partial collection for the same accounts")
    args = parser.parse_args(argv)
    try:
        archive, summary = build_bundle(args.source, args.output_dir, args.latest_n, args.supplement)
    except (OSError, ValueError, sqlite3.Error, csv.Error) as exc:
        print("Handoff not created: " + str(exc)[:180], file=sys.stderr)
        return 2
    print("Handoff ZIP: " + str(archive))
    print("Source accounts={source_accounts}, covered_accounts={accounts_with_posts}, "
          "source_posts={source_posts}, recent_posts={latest_post_rows}".format(**summary))
    print("No API calls. No changes to source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
