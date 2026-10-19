# AI development working agreement

1. The source of truth for client objectives is `REQUIREMENTS.md` and the user's actual customer materials. **KQ3 means Key Question 3, not 2026 Q3.** Resolve ambiguous labels rather than guessing.
2. The **official local** `account_list.csv` (294 entries) is authoritative for target account identifiers. Never silently edit, overwrite or substitute identities.
3. Never log, upload, commit or quote access tokens or `.env.local`. Scan staged changes and keep real source data local unless the user specifically approves another destination.
4. Preserve successful collection states and run history. Never overwrite or reset `posts.csv`, `media.csv`, `accounts.csv`, `collection_status.csv`, `manifest.json`, and logs without explicit confirmation and a verified backup.
5. `collector.py` currently rate-limits itself with configurable interval but has hit Meta error #4. Never issue live Meta requests as part of synthetic tests or just to diagnose code; check any API execution with user first. Stop on #4 instead of rapid repeated retries.
6. Understand that previous failures (KR_032 etc.) are not always retried on resume; consult code for the exact CLI and eligibility criteria. Distinguish tested behavior from claims made only in docs.
7. Keep data ingestion and image classification separate from dashboard retrieval. Dashboard reads DB; no mass re-analysis on refresh.
8. Distinguish raw collection completeness, field completeness, analysis eligibility, and customer claim validity. Keep absent values NULL.
9. With each code edit: run offline tests, report affected files, tested checks, untested live integrations, exact run commands and rollback steps. Avoid repeating the same failed troubleshooting technique more than twice without a new diagnosis.
10. GitHub tracks code and reviewed documentation. Use ChatGPT Library/locally held files for user-approved large dataset exchange; consider container working directories temporary rather than persistent storage.

## Mandatory cross-chat handoff synchronization (2026-10-19 incident prevention)

11. **A feature or operational design is not fully handed off merely because a code or docs file was committed.** Whenever a material plan, API lane assignment, implementation status, operational policy, known blocker, or next action changes, update **both root `HANDOFF.md` and `STATUS.md` in the same work session**, with a top-of-file dated summary and direct links to the authoritative design/code. Include what is implemented, tested, not implemented, and what must not be run.
12. Before reporting 'GitHub reflected', 'handoff complete', or telling the user a new chat can restore the project, **fetch the latest `main` versions of `HANDOFF.md`, `STATUS.md`, and the linked source document back from GitHub** and verify that the current decision is discoverable from the top sections. Provide the commit SHA and explicitly distinguish **design committed / handoff synchronized / runtime implemented / live verified**. If any step is missing, report it as missing; never imply completion.
13. For handoffs, prefer a short **current-state index** at the top of both documents over buried historical notes. Older contradictory information must be marked superseded, not silently trusted. New chat restoration should read the index and follow the links before acting.
14. **Incident record:** On 2026-10-19, three-API planner and implementation-gate docs were committed, but `HANDOFF.md`/`STATUS.md` were not simultaneously updated; a new chat therefore missed the plan. Later handoff synchronization fixed the omission. Prevent recurrence using rules 11-13. This is a documentation/workflow failure, **not evidence that live three-API collection was implemented**.
