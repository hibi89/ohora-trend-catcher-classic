# Meta Graph Batch API probe (isolated from production)

**Purpose:** Determine whether the current Business Discovery edge works inside the Graph batch API, inspect nested carousel data, and measure wall-clock time and `X-App-Usage` with only a few subrequests. This is **not** the dashboard flow or the official 294-account collector.

Official Meta docs: https://developers.facebook.com/docs/graph-api/batch-requests/ (maximum 50 calls per batch; each subcall consumes its own API usage). This experiment deliberately caps one batch at **10 subrequests**. Batch support for this particular Business Discovery call remains **unverified until live testing**.

## Safety

- Never writes the production `accounts.csv`, `posts.csv`, `media.csv`, `collection_status.csv`, `design_tags.csv` or `manifest.json`.
- Never downloads actual photos or prints tokens, raw captions, post IDs or media URLs. Reports only counts, status codes, timings, and usage percentages.
- A dry run is the default; `--live` explicitly authorizes exactly **one batch POST**. No retries or automated stage escalation. A batch with one subrequest is still a network call consuming Meta resources.
- If `total_time` is already high, **do not run**. Check the Meta dashboard separately before the experiment. A batch returned at/above 80% is a stop signal before any subsequent experiment; do not issue repeated calls merely to check recovery.
- Tokens live in local `.env.local` and are transmitted in the HTTPS POST body as the batch API's mandatory top-level fallback `access_token`, **not in the URL or stored output**. Never paste the actual token into chat or GitHub.
- The received `X-App-Usage` is an aggregate moving-window percentage **after** the request, not the exact cost of that batch. For credible comparison, note pre-test usage from the dashboard and run independent tests only after comparable usage conditions.

## Run from PowerShell after `git pull origin main`

Change `SOURCE`/`ENV` only if your original collection folder is somewhere else.

```powershell
$BASE = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브'
$SOURCE = "$BASE\2차 프로젝트 홍주님께 제공할 수집데이터\account_list.csv"
$ENVFILE = "$BASE\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection\.env.local"
cd "$BASE\ohora-trend-catcher"

# 1) OFFLINE dry run: sends no API calls
python .\experiments\meta_batch_probe.py --source "$SOURCE" --keys KR_001

# 2) ONE live batch of ONE account (10 posts). Stop and share the JSON report.
python .\experiments\meta_batch_probe.py --source "$SOURCE" --env-file "$ENVFILE" --keys KR_001 --live
```

Only **after reviewing** the first result, compare two known accessible account keys. Do not run this line automatically:

```powershell
python .\experiments\meta_batch_probe.py --source "$SOURCE" --env-file "$ENVFILE" --keys KR_001 KR_002 --live
```

The report is written under `experiments/results/`, which should remain excluded from Git. A returning `outer_app_usage: {}` means the API did not supply the header; it is **not** 0%.

Offline tests, no API calls:

```powershell
python -m unittest discover -s experiments -p 'test_meta_batch_probe.py' -v
```

**Do not replace** the original `collector.py` or run the original CSV writer from this experiment.
