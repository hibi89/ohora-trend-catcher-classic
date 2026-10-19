# OHORA Trend Catcher — KQ3, 294 accounts

This folder contains a new collection run isolated from earlier 115-account and 171-account work. The source list is the parent folder's account_list.csv; the original file is read-only input.

## Files

- accounts.csv, posts.csv, media.csv, design_tags.csv, collection_status.csv, and collection_summary.md are the requested outputs.
- collector.py is the resumable runner. It reads only the official source CSV and saves each account before moving to the next.
- n8n_meta_collection.json and n8n_vision_classification.json are separate, inactive workflows to import into local n8n.
- .env.example documents local-only configuration. Copy it to .env.local; keep .env.local private.

## Before the first Meta API call

1. Set META_ACCESS_TOKEN, META_IG_USER_ID, and META_GRAPH_VERSION in .env.local.
2. Use an authorized Instagram Graph API professional account as the Business Discovery caller and a token with the required Instagram and linked Page permissions. Check Meta's [Business Discovery reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery) for the current permission and account requirements.
3. Confirm the target accounts are public Business or Creator accounts. Personal, private, renamed, or unavailable accounts may fail Business Discovery; each failure is retained with its API error.
4. Import n8n_meta_collection.json into the local n8n instance and run it manually. The runner skips successful accounts on restart and retries unfinished or failed accounts.

The runner sends the Meta token only in the HTTP Authorization header. It does not print the token or raw HTTP responses. Do not include credentials in n8n node parameters or workflow exports.

## Elice image classification

The selected Elice model is helpy-v-reasoning-c (Helpy-V Reasoning Crimson), an image-to-text vision-language model. Elice currently lists it as Dedicated, so the organization must create and start its endpoint before tagging images. See the [model details](https://elice.io/en/ax/model-library/994cd13d-5347-4c64-a990-c5e88ab225de) and [ML API request guide](https://help.elice.io/help/docs/elicecloud/ml-api/api). Add the endpoint base URL and API key to .env.local, then run n8n_vision_classification.json. This is a separate manual workflow so Meta collection can finish first. Per-image results are saved as they complete; successful images are skipped when resumed.

The vision workflow analyzes image media and carousel image children. Video records stay in media.csv but are not sent to the image model.

## Resume and data handling

The runner makes at most one account request at a time, requests at most 20 latest posts, retries transient errors, and rewrites CSV files atomically after each account. collection_status.csv records pending, in-progress, successful, and failed accounts. manifest.json stores the source file hash; if the official CSV changes after initialization, the runner stops instead of mixing runs.

Collection timestamps use Korea Standard Time. Media URLs are stored as returned by Meta; the runner does not download media files. API messages are sanitized before they are written to CSV or console output.
