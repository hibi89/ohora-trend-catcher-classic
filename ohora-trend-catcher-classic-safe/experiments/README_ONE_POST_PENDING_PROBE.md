# OHORA — 2026-10-16 Meta pending-only 1-post usage experiment

Goal: The app-level total_time was 72%, then about 75% on a 1-account test, and the Meta dashboard displays 75.8%. The first source has 176 success + 5 failed (Meta 110) + 113 pending accounts. Only test NEW pending accounts with one post. Do not touch 880 collected posts in experiments/results/latest_5/collection.sqlite.

## Step 1. Offline tests (no API calls)

    git pull origin main
    python -m unittest discover -s experiments -p test_full_batch_collector.py -v

Expected: 19/19 tests OK. New option --only-pending-from reads original SQLite read-only and restricts a separate new run to original pending/rate_limited account keys; it does NOT retry successes or five failed account IDs.

## Step 2. Guarded 5-account pilot (paid Meta API request)

Use existing $src and $envFile PowerShell variables from earlier; never share token contents.

    python .\experiments\full_batch_collector.py `
      --source $src `
      --env-file $envFile `
      --posts 1 `
      --batch-size 5 `
      --max-batches 1 `
      --stop-usage 85 `
      --only-pending-from ".\experiments\results\latest_5\collection.sqlite" `
      --output-dir ".\experiments\results\latest_1_pending" `
      --live

One small batch is the only planned call. The --stop-usage percentage acts AFTER the current batch; it cannot prevent overshoot. Do not start when dashboard usage has already risen near 85%. A successful batch must be reviewed before resuming more accounts.

## Step 3. Interpretation

- With 113 pending accounts and total_time 75.8%, to finish before 100% requires average additional usage <= (100-75.8)/113 = 0.2142 percentage points per account. For a conservative 90% stop, <=0.1257 points per account.
- Previously 180 five-post requests were associated with 72% observed use (0.4 percentage points per attempted account). It is NOT a per-call billing rate, because Meta reports a cumulative rolling metric.
- Hypothetically, if a one-post request uses 0.4*(f+(1-f)/5) points/account, where f is the fixed-cost fraction of a five-post request, the all-113 case requires f<=0.419 to stay under 100%. This f is unknown.
- Five account 1-post sample at two different times is informative, but NOT a controlled estimate of fixed cost. Previous calls and moving-window decay can move reported percentages.
- Do not change --posts from 5 to 1 in the original latest_5 directory; its manifest rejects mismatches to protect prior data. New latest_1_pending directory is intentionally separate.

## Handoff

Current existing Hongju ZIP is earlier snapshot of 175 accounts. latest_5 now has 176 success; latest_1_pending is separate. Do not claim the partial 1-post experiment covers all 294 accounts. Merging sources safely into a final combined ZIP is a follow-up step once 1-post results are proven.
