# OHORA: 150/144 accounts × 5 media posts, every 90 minutes until 50 unique posts

**Status: CODE + OFFLINE TESTS AUTHORED; NOT YET VERIFIED ON USER WINDOWS OR RUN LIVE. Automatic scheduling is DISABLED by default.** Existing `latest_5`, `latest_1_pending`, `latest_10_owner_slot2_151_294` and the Hongju ZIP remain untouched. New output directories must be separate.

## Why ordinary latest-5 cannot reach 50 unique posts in ten cycles

Repeating Business Discovery `media.limit(5)` from the beginning returns the same five newest posts unless content changes. The `rolling_backfill.py` collector instead reads the API `business_discovery.media.paging.cursors.after`, persists it, and requests the next five older posts using `media.limit(5).after(CURSOR)` for each account. The media cursor and unique `post_id` are stored in SQLite, never replacing earlier cycles. This must be validated with the user's current Meta Graph version first: Meta pagination can be provider/version-dependent.

Assuming all 294 accounts are accessible, each has at least 50 historical posts, each response supplies five **new** IDs, and app quota allows full 150 and 144 accounts in EVERY cycle:

- 150 + 144 = 294 official accounts (not 300 exact).
- Five posts per account per cycle, 10 cycles to 50 unique posts: 294 * 50 = **14,700**.
- 90 minutes * 10 cycles = **900 minutes of cycle cadence (15 hours)**; the first run is at the start of the first slot, so ten start slots span nine intervals = 13.5 hours. At 09:00–18:00 on weekdays, six 90-minute start slots/day would make **6 + 4 = 10** over two workdays in the ideal case. Actual business-hours window is NOT set until user decides.
- Fewer than 50 published posts, Meta 110 access errors, rate limits, absent/expired pagination cursors, and a cycle not finishing all 150 accounts make the actual duration and coverage less predictable; 10 cycles are a best-case expectation, not a guarantee.

## Files

- `rolling_backfill.py`: separate app A rows 1–150 and app B rows 151–294; five older posts per cycle, saved cursor, unique post/media rows, fair priority for least-backfilled accounts, pause on Meta rate/auth errors or 70% post-batch usage. 90-minute start-to-start and >=60-minute finish-to-start cooldown. A single scheduler invocation never requests a second page for the same account.
- `test_rolling_backfill.py`: 10 no-network tests for 5→10→50, repeated-cycle idempotency, pagination field syntax, missing cursors and failures, isolated A/B and a one-account probe.
- `run_90m_cycle.py`: a ONE-SHOT dispatcher. It does not itself run in the background; external Windows Task Scheduler or a reachable n8n execution service must invoke it every 90 minutes AFTER review.
- `test_run_90m_cycle.py`: seven no-network dispatcher tests.
- `backfill_schedule.example.json`: disabled example; copy to local-only ignored `backfill_schedule.local.json`. Do not commit actual credentials or client data.

## 1. Install the latest code and run all 17 new offline tests

```powershell
git pull origin main
python -m unittest discover -s experiments -p test_rolling_backfill.py -v
python -m unittest discover -s experiments -p test_run_90m_cycle.py -v
```

Expected 10 and 7 tests OK respectively. They use synthetic 294-account data and fake API responses and do not read real tokens or contact Meta.

## 2. Verify one account's next-page cursor with two actual 90-minute cycles

**Only after tests pass and Meta usage is comfortably low.** Use the original `$src` and `$envFile` already set in PowerShell, or declare them again. Original database stays unchanged.

```powershell
python .\experiments\rolling_backfill.py `
  --app A `
  --probe-ordinal 1 `
  --source $src `
  --env-file $envFile `
  --output-dir ".\experiments\results\cursor_probe_A" `
  --batch-size 1 `
  --max-batches 1 `
  --stop-usage 70 `
  --delay-seconds 0 `
  --live
```

Check stdout and `experiments/results/cursor_probe_A/collection.sqlite`: five distinct posts and a nonempty `backfill_state.next_cursor`. **Do not supply a manual `--cycle-id` in live requests.** Wait at least 90 minutes from the previous start AND 60 minutes after its end, and run the same command again. This must yield TEN unique post IDs and two pages in `backfill_state`; if not, stop and diagnose, do not run all 294 accounts.

Inspect the result without exposing the token:

```powershell
@'
import sqlite3
from contextlib import closing
p = r'.\experiments\results\cursor_probe_A\collection.sqlite'
with closing(sqlite3.connect(p)) as db:
    print('Unique posts:', db.execute('SELECT count(*) FROM posts').fetchone()[0])
    print('Pages:', db.execute("SELECT pages_fetched FROM backfill_state WHERE account_key='KR_001'").fetchone()[0])
    print('Cursor present:', bool(db.execute("SELECT next_cursor FROM backfill_state WHERE account_key='KR_001'").fetchone()[0]))
'@ | python -
```

## 3. Activate proper two-app operation ONLY when app B is renewed

App B's old Hongju token was expired as of the last check. **Do not put the user's token or IG ID in the B slot to imply two independent API budgets.** Both slots must have separately authorized, active Meta app/token credentials and correct, distinct `META_APP_ID` values. Adding another app does not guarantee independence of all Meta app/user/platform limits.

```powershell
Copy-Item .\experiments\backfill_schedule.example.json .\experiments\backfill_schedule.local.json
notepad .\experiments\backfill_schedule.local.json
```

Set working-hour `business_hours_kst.start/end` (exact hours to be chosen), the official source path, the two actual local env paths, and both distinct output directories. Add numeric `META_APP_ID=<your actual app ID>` to each LOCAL env file if missing. Confirm actual app IDs, app permissions, and usable valid tokens. Then set `apps.A.enabled=true`, `apps.B.enabled=true`, `separate_authorized_apps_confirmed=true`, and **finally** `schedule_enabled=true`. The example remains disabled and does not create cron/Task Scheduler jobs.

Inspect without API calls:

```powershell
python .\experiments\run_90m_cycle.py --config .\experiments\backfill_schedule.local.json
```

Invoke one authorized production tick from the working PC:

```powershell
python .\experiments\run_90m_cycle.py `
  --config .\experiments\backfill_schedule.local.json `
  --live
```

Only after a successful A/B controlled trial, schedule that exact one-shot command **every 90 minutes** during the user's approved working hours in Windows Task Scheduler or through an n8n host that can access this project's local source, Python executable and two local DB/credential files. A remote n8n server cannot directly execute files on the user's Windows PC unless a separate secure execution bridge exists. Schedule remains OFF until explicit setup.

## 4. Safety and output semantics

- Both apps each get their own `collection.sqlite`, tables `accounts/posts/media/backfill_state/backfill_runs/batches`, CSV exports and per-batch `X-App-Usage` snapshots. Original experimental source DBs remain untouched.
- Source rows 1..150 and 151..294 never overlap. Use only officially provided target professional accounts with authorized Business Discovery access; Meta error 110 accounts stay flagged, never represented as successes.
- Each requested page is at most five posts/account. A successful post ID is inserted once using SQL uniqueness; same cycle is blocked from additional pages. At 50 unique posts (or when an account has fewer historical posts), that account stops. It **does not automatically continue refreshing newly published posts after historical 50**; latest-new-post synchronization is a separate module.
- A single outer Graph batch includes up to 10 inner Business Discovery requests. `--stop-usage 70` is a **post-request** safety threshold; it can be crossed within a batch. Meta's moving-window rate metrics must be observed; 90-minute scheduling does not guarantee full reset.
- If a cursor is missing/unchanged or malformed, this implementation blocks that account and records `cursor_or_payload` or `cursor_blocked`, rather than repeatedly requesting the same first five.
- For now, prior historic datasets and the new A/B databases are separate. A verified multi-source archive/data migration is still required before declaring a consolidated 14,700-row handoff or a complete dashboard.
