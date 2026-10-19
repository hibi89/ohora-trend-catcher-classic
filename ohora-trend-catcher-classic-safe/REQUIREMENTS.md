# OHORA / Trend Catcher — customer questions and scope

> Source: user-provided customer presentation/notes and project discussions, not a verbatim transcript. The official client presentation remains the ultimate authority; do not invent missing requirements.

## Important: KQ3 is NOT the third quarter of 2026

- **KQ1**: Which nail designs are trending now in South Korea, the United States, and Japan?
- **KQ2**: Which nail designs trended within a chosen date range?
- **KQ3 (Key Question 3)**: Among social-media posts about a **specific nail design**, which posts have the highest engagement by **country and date range**?

KQ3 is a **business key question**, not a fixed July–September (2026 Q3) date window. User-selected periods may include 7/30/90 days, constrained by available source coverage.

## Audience and intent

Likely users: OHORA product-planning, design and marketing teams. Focus on early nail trends and their support in observable content; no claim that likes alone are product demand. Instagram first, TikTok as a potential extension, Pinterest optionally considered. Account-list source of truth is the supplied official list **294 accounts**: KR 100 / US 101 / JP 93 (no user-name substitutions without review).

## Current pipeline

1. **Before presentation:** first acquire up to **5 latest posts per account** via Meta Batch and preserve IDs, timestamps, engagement fields when available, media metadata and permalinks. The older **20-post** setting was an internal experiment target, **not a verified customer-mandated minimum**. Future backfill by 5 posts at a time is planned, subject to rate limits.
2. **Before presentation:** classify accessible IMAGE and carousel images (and evaluate VIDEO thumbnails separately) into canonical nail-design dimensions: color, technique, texture, motif, season, use-case and whether content is about nail designs.
3. **During presentation:** read stored DB data; filter by country, user-selected date window and design, compute comparable engagement results, visualize and export CSV/XLSX. Target end-to-end within **2–3 minutes** (engineering target, not measured performance). Do not run a full Meta scrape or batch vision analysis on dashboard refresh.

- `like_count` may be absent; **NULL is not zero**.
- `comments_count` is available in the 2026-10-15 snapshot but must be checked for future data.
- Engagement count (likes + comments) is calculated only when both fields exist. Relative engagement rate can use current followers but must disclose that it is not necessarily contemporaneous with a post.
- A **latest-5 snapshot** (or historical latest-20 experiment) is not a complete date interval; explicitly show coverage and absence/limitations when users select historical ranges.
- Design tagging was not complete in the dated snapshot (0 rows). A post-level offline-tested vision runner is now available; provider authentication, model acceptance, image URL access, actual classification quality, and cost **remain unverified until a real one-post test**.
- Official Business Discovery generally does **not** disclose third-party post saves/shares or proprietary insights; do not claim to collect them.
- Existing program does not download original image bytes; it stores URLs and metadata. Video direct URLs can be blank and available thumbnails may not represent the whole video.

## Verified snapshot, not live truth (2026-10-15 21:58 KST)

- 94 successful accounts: KR 89, US 4, JP 1; 12 failed; 188 pending.
- 1,880 posts and 5,307 media rows (no duplicate IDs in snapshot).
- 743 posts missing likes; 338 video rows missing direct media URL; all 1,880 have comments, as checked then.
- Meta `X-App-Usage` `total_time` was the dominant observed limit. One independent light Business Discovery call later reported 22%, not a guarantee that collection can proceed indefinitely.

Source details can be found in the dated `analysis/` reports. Revalidate from locally held CSVs before each milestone.
