#!/usr/bin/env python3
"""Merge three read-only OHORA snapshot CSVs from a raw ZIP into analysis-ready ZIP.

No Meta/API calls and no third-party Python dependencies. Input ZIP is unchanged.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

SOURCE_NAMES = ("latest5", "latest1", "latest10")
TABLES = ("accounts", "posts", "media")
PREFERENCE = {"latest1": 1, "latest5": 2, "latest10": 3}
COUNTRIES = ("KR", "US", "JP")


def read_member(zip_file, name):
    try:
        text = zip_file.read(name).decode("utf-8-sig")
    except KeyError as exc:
        raise ValueError("Missing CSV in raw ZIP: " + name) from exc
    return list(csv.DictReader(StringIO(text)))


def load_zip(path):
    with ZipFile(path) as z:
        names = [x.filename for x in z.infolist() if not x.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP member names")
        roster = read_member(z, "account_list.csv")
        datasets = {
            prefix: {name: read_member(z, f"{prefix}_{name}.csv") for name in TABLES}
            for prefix in SOURCE_NAMES
        }
    if not roster or any(not x.get("account_key") for x in roster):
        raise ValueError("Official account_list.csv is invalid")
    official = {r["account_key"]: r for r in roster}
    if len(official) != len(roster):
        raise ValueError("Duplicate account in official source")
    for source, tables in datasets.items():
        mapping = {a.get("account_key"): a for a in tables["accounts"]}
        if len(mapping) != len(tables["accounts"]) or mapping.keys() != official.keys():
            raise ValueError(f"{source}: account roster mismatch")
        for key, account in mapping.items():
            original = official[key]
            if (str(account.get("username", "")).casefold()
                != str(original.get("username", "")).casefold()
                or account.get("country") != original.get("country")):
                raise ValueError(f"{source}: official account mismatch for {key}")
        for table, pk in (("posts", "post_id"), ("media", "media_id")):
            ids = [r.get(pk) for r in tables[table]]
            if (any(not i for i in ids) or len(ids) != len(set(ids))
                or any(r.get("account_key") not in official for r in tables[table])):
                raise ValueError(f"{source}: duplicate/missing {pk} or unknown account")
    return roster, datasets


def better(old, new, old_source, new_source):
    filled = lambda d: sum(v not in ("", None) for v in d.values())
    return (filled(new), PREFERENCE[new_source]) > (filled(old), PREFERENCE[old_source])


def merge(roster, datasets):
    accounts_by_source = {label: {a["account_key"]: a for a in d["accounts"]}
                          for label, d in datasets.items()}
    posts, media, post_origin, media_origin = {}, {}, {}, {}
    by_source = {}
    for source, tables in datasets.items():
        by_source[source] = {
            "post_rows": len(tables["posts"]),
            "media_rows": len(tables["media"]),
            "accounts_with_posts": len({x["account_key"] for x in tables["posts"]}),
        }
        for table, dst, provenance, pk in (
            ("posts", posts, post_origin, "post_id"),
            ("media", media, media_origin, "media_id")
        ):
            for value in tables[table]:
                identity = str(value[pk])
                if identity in dst:
                    if dst[identity]["account_key"] != value["account_key"]:
                        raise ValueError(f"{table} ID in different accounts: {identity}")
                    if better(dst[identity], value, provenance[identity], source):
                        dst[identity] = value
                        provenance[identity] = source
                else:
                    dst[identity] = value
                    provenance[identity] = source
    if not posts:
        raise ValueError("No posts found in raw ZIP")
    for m in media.values():
        p = posts.get(m.get("post_id"))
        if p is None or p["account_key"] != m["account_key"]:
            raise ValueError("Media references missing/wrong post")

    counted = Counter(x["account_key"] for x in posts.values())
    account_rows = []
    for r in roster:
        key = r["account_key"]
        candidates = [(source, accounts_by_source[source][key],
                       sum(p["account_key"] == key for p in datasets[source]["posts"]))
                      for source in SOURCE_NAMES]
        selected_source, selected, _ = max(
            candidates, key=lambda a: (a[2] > 0, a[2],
                a[1].get("status") in ("success", "partial"), PREFERENCE[a[0]]))
        failure = next((v for _, v, _ in candidates if v.get("status") == "failed"), {})
        status = ("collected" if counted[key] else
                  "failed" if failure else "uncollected")
        account_rows.append({
            "country": r.get("country", ""),
            "account_key": key,
            "username": r.get("username", ""),
            "collection_status": status,
            "posts_available": counted[key],
            "followers_at_collection": selected.get("followers_count", ""),
            "ig_user_id": selected.get("ig_user_id", ""),
            "selected_source": selected_source,
            "error_code": failure.get("error_code", "") if not counted[key] else "",
        })
    account_map = {r["account_key"]: r for r in account_rows}
    media_for_post = defaultdict(list)
    for m in media.values():
        media_for_post[m["post_id"]].append(m)

    def image_url(post_id):
        candidates = sorted(media_for_post[post_id], key=lambda m: (
            m.get("media_role") not in ("primary", "carousel_item"),
            not bool(m.get("media_url") or m.get("thumbnail_url")),
            int(m.get("sort_order") or 0)))
        for item in candidates:
            if item.get("media_url") or item.get("thumbnail_url"):
                return item.get("media_url") or item.get("thumbnail_url")
        return ""

    flat = []
    for p in posts.values():
        a = account_map[p["account_key"]]
        flat.append({
            "country": p.get("country") or a["country"],
            "account_key": p["account_key"],
            "username": p.get("username") or a["username"],
            "post_id": p["post_id"],
            "posted_at": p.get("timestamp", ""),
            "caption": p.get("caption", ""),
            "post_url": p.get("permalink", ""),
            "media_type": p.get("media_type", ""),
            "media_product_type": p.get("media_product_type", ""),
            "likes": p.get("like_count", ""),
            "comments": p.get("comments_count", ""),
            "engagement_count": p.get("engagement_count", ""),
            "engagement_rate_pct": p.get("engagement_rate_pct", ""),
            "followers_at_collection": a["followers_at_collection"],
            "representative_media_url": image_url(p["post_id"]),
            "attached_media_rows": len(media_for_post[p["post_id"]]),
            "collected_at": p.get("collected_at", ""),
            "original_source": post_origin[p["post_id"]],
        })
    flat.sort(key=lambda x: (x["country"], x["account_key"], x["posted_at"], x["post_id"]))
    grouped = defaultdict(list)
    for post in flat:
        grouped[post["account_key"]].append(post)
    newest = []
    for r in roster:
        newest.extend(sorted(grouped[r["account_key"]],
                            key=lambda p: (p["posted_at"], p["post_id"]),
                            reverse=True)[:5])
    country_table = []
    for country in COUNTRIES:
        entries = [a for a in account_rows if a["country"] == country]
        country_table.append({
            "country": country,
            "listed_accounts": len(entries),
            "accounts_with_posts": sum(a["posts_available"] > 0 for a in entries),
            "failed_accounts": sum(a["collection_status"] == "failed" for a in entries),
            "posts": sum(a["posts_available"] for a in entries),
            "media": sum(m.get("country") == country for m in media.values()),
        })
    summary = {
        "official_accounts": len(roster),
        "accounts_with_posts": sum(a["posts_available"] > 0 for a in account_rows),
        "accounts_failed": sum(a["collection_status"] == "failed" for a in account_rows),
        "accounts_uncollected": sum(a["collection_status"] == "uncollected" for a in account_rows),
        "unique_posts": len(posts),
        "unique_media_rows": len(media),
        "latest5_available_posts": len(newest),
        "source_counts": by_source,
        "countries": country_table,
        "notes": [
            "Three read-only snapshots merged by post_id/media_id; no Meta calls.",
            "Most recent five refers to captured posts only, not full account history.",
            "Missing likes or comments mean unknown, not zero.",
            "Engagement rates use the followers value recorded with source snapshots.",
            "Media URLs may expire and the ZIP does not contain the image files.",
            "Historical 50-post backfill and trend AI classifications are not included.",
            "Import long Instagram IDs into Excel as TEXT to preserve all digits.",
        ],
    }
    tables = {
        "posts_flat_for_analysis.csv": flat,
        "posts_latest5_per_account.csv": newest,
        "accounts_coverage.csv": account_rows,
        "country_summary.csv": country_table,
        "media_merged.csv": sorted(media.values(),
                                   key=lambda r: (r.get("account_key", ""), r.get("post_id", ""))),
        "accounts_needing_review.csv": [a for a in account_rows if not a["posts_available"]],
    }
    return tables, summary


def csv_bytes(rows, cols):
    # All CSVs have headers even with no matching records.
    extra = sorted({key for row in rows for key in row if key not in cols})
    columns = list(cols) + extra
    buf = StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        safe = {}
        for k, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(
                    ("=", "+", "-", "@", "\t", "\r", "\n")):
                value = "'" + value
            safe[k] = value
        writer.writerow(safe)
    return buf.getvalue().encode("utf-8-sig")


def build(raw_zip: Path, out_dir: Path):
    raw_zip = raw_zip.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    if not raw_zip.is_file():
        raise ValueError("Input raw ZIP does not exist")
    roster, datasets = load_zip(raw_zip)
    tables, summary = merge(roster, datasets)
    summary["created_at_kst"] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = "OHORA_Analysis_Ready_" + datetime.now(
        timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S") + ".zip"
    output = out_dir / filename
    if output.exists():
        raise ValueError("Archive with same timestamp already exists")
    readme = (
        "OHORA Trend Catcher — 홍주님 분석용 통합본\n\n"
        "posts_flat_for_analysis.csv — 가장 중요한 분석 테이블: 게시물 1개당 1행\n"
        "posts_latest5_per_account.csv — 보유한 데이터 중 계정별 최신 5개\n"
        "accounts_coverage.csv — 계정별 확보한 게시물 수, 실패 및 결측\n"
        "country_summary.csv — KR/US/JP 국가별 수집 범위\n"
        "media_merged.csv — 게시물 이미지/캐러셀 미디어 연결\n"
        "accounts_needing_review.csv — 확보되지 않은 계정 검토\n"
        "manifest.json — 실제 검증된 계정/게시물/미디어 수 및 주의사항\n\n"
        "인스타그램 ID는 엑셀에서 텍스트 형식으로 가져올 것.\n"
        "URL은 만료될 수 있으며 좋아요/댓글 결측은 0이 아님.\n"
        "과거 게시물 50개 백필 및 AI 디자인 분류는 아직 포함되지 않음.\n")
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("README_분석안내.txt", readme.encode("utf-8-sig"))
        z.writestr("manifest.json", json.dumps(
            summary, ensure_ascii=False, indent=2).encode("utf-8"))
        for name, rows in tables.items():
            columns = (
                list(rows[0]) if rows else
                list(account_rows_columns()) if name == "accounts_needing_review.csv" else
                ["account_key"])
            z.writestr(name, csv_bytes(rows, columns))
    return output, summary


def account_rows_columns():
    return ("country", "account_key", "username", "collection_status",
            "posts_available", "followers_at_collection", "ig_user_id",
            "selected_source", "error_code")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        path, result = build(args.raw_zip, args.output_dir)
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
        parser.exit(2, "ERROR: " + str(exc) + "\n")
    print("분석용 ZIP 생성 완료:", path)
    print("검증:", result["official_accounts"], "계정 중",
          result["accounts_with_posts"], "계정 수집,", result["unique_posts"], "고유 게시물,",
          result["accounts_failed"], "오류 계정")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
