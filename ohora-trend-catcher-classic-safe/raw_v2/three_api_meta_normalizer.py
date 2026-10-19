"""Pure, offline Meta Business Discovery response normalization.

No HTTP, tokens, credentials or database writes. Only allowlisted media
fields are retained; paging.next URL is replaced with a harmless sentinel.
"""
from __future__ import annotations

from three_api_paging import validate_page_edge

FIELDS = ("id", "caption", "media_type", "media_url", "permalink",
          "timestamp", "like_count", "comments_count", "thumbnail_url")


def normalize_meta_page(payload, *, requested_cursor=None):
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("Meta error or invalid response")
    # Business Discovery may wrap media in business_discovery.media.
    media = payload.get("business_discovery", payload)
    if not isinstance(media, dict):
        raise ValueError("Missing media envelope")
    if "media" in media:
        media = media["media"]
    if not isinstance(media, dict) or not isinstance(media.get("data"), list):
        raise ValueError("Missing media data")
    posts = media["data"]
    if len(posts) > 4:
        raise ValueError("Response exceeds requested page limit")
    cleaned = []
    for post in posts:
        if not isinstance(post, dict):
            raise ValueError("Invalid media item")
        post_id = post.get("id")
        if not isinstance(post_id, str) or not post_id.strip():
            raise ValueError("Missing media id")
        for numeric in ("like_count", "comments_count"):
            if numeric in post and (type(post[numeric]) is not int or post[numeric] < 0):
                raise ValueError("Invalid engagement count")
        cleaned.append({key: post[key] for key in FIELDS if key in post})
    paging = media.get("paging", {})
    if not isinstance(paging, dict):
        raise ValueError("Invalid paging")
    cursors = paging.get("cursors", {})
    if not isinstance(cursors, dict):
        raise ValueError("Invalid paging cursors")
    # Validate original structure first; do not persist paging.next query tokens.
    validate_page_edge({"data": cleaned, "paging": paging},
                       requested_cursor=requested_cursor)
    normalized = {"data": cleaned}
    if paging.get("next"):
        normalized["paging"] = {
            "next": "offline-next-page",
            "cursors": {"after": cursors["after"]},
        }
    return normalized
