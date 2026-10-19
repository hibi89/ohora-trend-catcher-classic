# OHORA Trend Catcher — 5-post incremental collection design (decision record)

Status: **Latest-5 first acquisition and standalone post-level vision pipeline implemented offline. Recurring latest refresh, historical backfill, 90-minute scheduling, production dashboard and real vision endpoint checks NOT implemented/verified.** Updated 2026-10-16 KST.

## Why two phases?

Meta Graph Batch 10x10 fetched 100 posts in 2.828s; 10x20 was efficient in elapsed time but the real 294-account experiment hit the app usage limit after 77 successes (reported Meta error 4 / HTTP 403, usage above 100%). Batch parallelism saves wall time but **does not eliminate quota consumption**. A 60-minute break is NOT proof of quota recovery.

Two architectures considered:
- A: every run requests 20–50 recent posts per account; simple but wasteful, more expensive and easy to reprocess
- B (**selected**): acquire 3–5 most recent posts/account, store unique IDs, then deepen back-history by 5 while quota permits, with a separate read-only dashboard

## Release stages (do not skip)

**Stage 0 — first acquisition (implemented):**
- Run `experiments/full_batch_collector.py --posts 5 --output-dir <NEW_SEPARATE_DIRECTORY>`, starting from the original 294-row account CSV, with 10 accounts per batch.
- The existing original 20-post results remain untouched.
- In this stage, the collector deliberately skips completed accounts on resume. It does **not** yet perform repeat latest-5 refresh or historic backfill. Never represent it as an ongoing incremental collector.
- Start with dry run and one live batch, inspect `summary.json` and usage. Follow with additional batches only after evidence that app usage is safely recovered. Do not run a second simultaneous collector.

**Stage 1 — incremental latest collector (NEXT):**
- Parameter `latest_n` initially 5, optionally 4/3/2 for **data-volume-related** errors, not to bypass Meta error 4.
- Read newest posts by Business Discovery, identifying each with stable `post_id`. Upsert accounts, posts, and media transactionally: never delete historical posts when refreshing an account.
- Refresh likes/comments where Meta returns them; do not change a missing value to zero. A newer request returning missing fields must not erase a previously observed count without policy.
- Store `last_seen_post_id`, `last_seen_timestamp`, run info and field-completeness flags.
- If >latest_n posts have appeared, paginate until the prior boundary is reached or a per-account safety budget is hit. Mark history gaps explicitly; do not claim the latest sample is exhaustive.
- Continue past individual access/parameter errors with a failed-account record; stop on app-level error 4/17/32/613 etc.
- Ensure live run cannot start while another collection is active; idempotent reruns.

**Stage 2 — historic backfill collector (NEXT):**
- Each account stores an independent Business Discovery `media.paging.cursors.after` and a stable oldest-known post-ID anchor.
- Request older groups of up to 5; deduplicate on `post_id`, preserve children and carry forward progress in DB transactions.
- First test a 5+next5 API request on an individual account before relying on nested Business Discovery cursor pagination. Tokens and cursors may become invalid, requiring anchored boundary recovery.
- Configurable `backfill_depth_target` (e.g. 50 unique posts/account), not a license to delete existing historical data. New latest posts can increase the lifetime archive above this target.
- The absence of more pages or an invalid cursor must be recorded, not interpreted as zero historical content.

**Stage 3 — vision and dashboard (user live MLAPI test: 20 successes/1 invalid_json; dashboard pending):**
- `vision/vision_runner.py` chooses up to 3 representative images per post, analyzes the **post** from images plus caption, and deduplicates by `post_id + model + prompt_version` with a media-ID/caption fingerprint. `selected_media` records source media IDs/basis but does not claim separate per-media tags. The runner reads existing SQLite or CSV without modifying source data. Provider connection has been validated on a small live sample; output reliability, costs and large-scale quality are not validated.
- Feed visual content plus post caption and categorize `is_design_post`, color, technique, texture, motif, season, use. Image endpoint authentication, price and output validation must be proven on a small sample first.
- Dashboard only queries stored DB; country + date range + design filter, ranking and export. Show data coverage limitations; user date filtering does not request Meta again.

## Optional schedule (DEFER activation until Stage 1+2 tested)

**Confirmed V1 operating values (2026-10-16; user can later revise):** Full implementation milestones and completion criteria: [V1_DELIVERY_ROADMAP.md](V1_DELIVERY_ROADMAP.md).
```yaml
timezone: Asia/Seoul
enabled: false
operating_windows: []  # user must provide actual start/end hours
latest_n: 5
backfill_n: 5
backfill_depth_target: 50  # unique-post target, NOT deletion/retention cap
accounts_per_batch: 10
max_run_minutes: 30
sol_insights_cadence: weekly
minimum_gap_start_to_start_minutes: 90
minimum_cooldown_after_finish_minutes: 60
usage_guard_total_time_percent: 70
modes: [latest, backfill_if_capacity]
```
Trigger can be n8n Schedule Trigger with a guard. A run is allowed only if:
1) current time is within the configured operating window, with enough time left to finish;
2) no prior run is active;
3) `now >= max(previous_started_at + 90 min, previous_finished_at + 60 min)`;
4) Meta rate-limit recovery and safe usage headroom can be verified. If usage status is unknown, do not infer that 1h cooldown reset the quota.
Exit gracefully on time, usage, transport, auth errors; persist cursor and batch-level outcomes. No automated retry loop after code 4.

## Safety and acceptance tests

- Unit mocks for latest 5, 4/3/2 data-pressure fallback, new-content overlap, account with >5 new posts, video, carousel children, missing likes, invalid cursor, duplicate media, partial batch, 403/code4, crash-restart.
- One real cursor pagination test and one small vision sample only after explicit approval for API calls and any model cost.
- Use separate test outputs; back up the existing 20-post run and never mutate it.
