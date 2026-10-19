# 2026-10-16 — 2nd logical collection slot, rows 151..294

**Planned but NOT executed on the user's Windows machine.** Two logical slots pointing to the same Meta token and Instagram IG user ID share the same actual app/user budget; do not claim separate independent quota. The user's screenshot showed Hongju's earlier provided token had expired. Use the owner's known-working local `$envFile` only for this temporary validation. When Hongju provides a valid authorized token, separate its credential file and collection output folder; do not relabel or silently overwrite prior owner's results.

## Expected source state

- Official original roster: 294 target accounts (not 300), ordinal range owner slot1 = 1..150, trial slot2 = 151..294.
- Snapshot 1 `experiments/results/latest_5/collection.sqlite`: 176 successes, 5 failed Meta-110, 113 pending (post limit 5).
- Snapshot 2 `experiments/results/latest_1_pending/collection.sqlite`: 15 successes among those 113 pending (post limit 1).
- Slots 151..294 have 144 accounts, **30** successes and **1 failed** in snapshot1, and 15 previously collected in snapshot2, leaving **98** eligible (based on observed logs; local dry-run is definitive). The first eligible ordinal is **197**.

## 1. Update code and confirm offline tests

    git pull origin main
    python -m unittest discover -s experiments -p test_full_batch_collector.py -v

Expected **22 tests OK** (additional tests cover partition, skip-two-snapshots and resume). No Meta call is made during tests.

## 2. Preview. No Meta calls and no writes.

    python .\experiments\full_batch_collector.py `
      --source $src `
      --env-file $envFile `
      --posts 10 `
      --batch-size 10 `
      --start-ordinal 151 `
      --end-ordinal 294 `
      --assigned-app owner_slot2_probe `
      --only-pending-from ".\experiments\results\latest_5\collection.sqlite" `
      --skip-collected-from ".\experiments\results\latest_1_pending\collection.sqlite" `
      --output-dir ".\experiments\results\latest_10_owner_slot2_151_294"

Expected preview: `144/294 assigned accounts, 98 eligible AFTER cross-DB skip ... First eligible ordinal(s): 197, 198, ...`. The old DBs are read-only. The new 10-post trial has its own SQLite manifest. It cannot mix with old 5-post or 1-post output directories.

## 3. Guarded first live run AFTER dashboard usage has sufficiently recovered

Do not assume the app usage window fully resets after 60 minutes; inspect the actual Meta app usage dashboard. Both logical slots use the same physical app/token and therefore share its quota. **No unattended automatic retry**; never run both in parallel. The `--stop-usage` guard only checks after the batch, so it cannot prevent a mid-batch overshoot. Do not run the batch if usage is still high.

Same preview command, plus the following options at the end:

      --max-batches 1 `
      --stop-usage 70 `
      --require-usage `
      --live

Once a successful single 10-account x 10-post batch returns, inspect actual total_time / call_count. If safe and the user approves, rerun the same command WITHOUT `--max-batches 1` to continue toward the 98 missing accounts. Already successful accounts in the new output DB are automatically skipped. Old success/partial and known 110-failed accounts are filtered from original; successes in the supplementary one-post DB are independently filtered, preventing duplicates across all three. No API request occurs in preview mode.

## 4. Later replace with Hongju authorization

Use Hongju's renewed authorized Meta user token and its own IG professional user ID in a **different local env file and different output directory**, after verifying scopes. Keep independent provenance and access permissions. Never commit tokens into GitHub. Never assume a second Meta app doubles usable rate budget until app-level and user-level quota are checked.

## 5. Data output caveat

The current Hongju ZIP dual-source helper supports primary five-post + secondary one-post. Combining a future third 10-post source for handoff is a separate tested task. Keep all three collection.sqlite files safe; do not copy one database over another or claim ZIP already contains third source.
