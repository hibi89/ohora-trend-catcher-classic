# OHORA RAW v2.1 — Astra review handoff (2026-10-19)

> **검수 후 갱신(2026-10-19):** 이 문서는 `500523b...` 이전 구현의 인수인계 기록이다. 후속 검수 결과와 93개 Windows 오프라인 테스트는 [RAW_V2_REVIEW_2026-10-19.md](RAW_V2_REVIEW_2026-10-19.md)를 따른다. 아래 구현 목록의 **65-minute cooldown은 확인된 불일치**이며, 현재 공통 규칙은 `max(finish+63min, start+65min, saved ready_at)`이다. 완료 증거는 단일 종료행 대신 최초 페이지부터 전체 연결로 검증한다. 운영 DB 읽기 전용 진단은 WARN, 운영 DB 복구와 Meta 호출은 미수행이다.

## Status
- Branch: `main`; most recent implementation commit before this handoff: `9f8657e922e0d72e6278cddbea93e56311446a20`.
- CI at that commit: **success** (GitHub Actions run 39150239533). Earlier 53 offline unit tests passed at 1750da4; confirm latest count from CI logs.
- **No real Meta API calls performed** during these changes. User's local SQLite and raw files have **not been audited**. Production-readiness is **NOT approved**.
- Existing observed results before these changes: 263 distinct accounts / 294; 1,178 posts; 3,152 media; only 10 historical backfills previously marked complete (may be unverified).
- Never erase local DB, reset cursors, or silently rerun an unknown-outcome batch.

## Implemented on GitHub
1. `raw_v2/collector.py`: verified Business Discovery username/id; history completion from actual history page with cutoff and evidence; rejects cursor cycles and cross-page timestamp regression; carousel children can be repaired on revisit and missing children are partial; batch_attempts journaling before send and archived batch response before processing; fail-closed local SQLite errors and fatal auth/identity/missing usage; 65-minute cooldown; KST fixed UTC+09.
2. `raw_v2/audit.py`: read-only SQLite and raw JSON audit, account coverage report and findings CSVs; **does not fix** DB. Use `--output-dir` and `--report-dir`.
3. `raw_v2/backup.py`: verified SQLite snapshot outside output dir; raw JSON must be preserved separately.
4. `raw_v2/recover.py`: explicit archived-batch recovery, dry-run default, `--apply` requires matching backup and source. Missing archive = UNKNOWN, no retry. **Must independently inspect this recovery logic before use on user DB.**
5. `raw_v2/daily_scheduler.py`: policy `daily`, `bootstrap-history`, `daily-front`, `history-only`; read-only audit gate, automatic preflight backup, `--max-batches 1` pilot, JSON summary; `--once` supported.
6. Regression tests: `tests/test_raw_integrity.py`, `tests/test_batch_recovery.py`, extended `tests/test_daily_scheduler.py` and original tests.

## Priority for Astra / Codex high-effort review
1. **P0** Review actual `main` code for correctness of transaction boundaries, archived response replay, crash consistency, and scheduler/audit gating. Do not trust green CI alone.
2. **P0** Validate legacy `backfill_done=1` states. New audit flags all without history evidence; scheduler currently only reselects legacy completed accounts if a backfill cursor remains. Legacy `done=1` and cursor=NULL may still be false completion; propose safe repair preserving existing data.
3. **P0** Check whether `insert_success` atomicity is sufficient: post/media/observations must roll back as one unit on invalid payload. Verify raw archive names, `request_id` collisions, batch request logs, slot accounting and recovery idempotence.
4. **P0** Verify account identity ID semantics: Business Discovery `id` is the discovered Instagram account ID; legacy `accounts.id` can be null or set. Ensure no legitimate account is falsely blocked.
5. **P1** Audit raw media coverage and carousel partial states, historical cursor completeness, time-series metric preservation.
6. **P1** Test 294-account dry-run, 5-account offline mock, 150/144 slot boundary, 65-minute cooldown, 85% usage, Windows PowerShell UTF-8 and KST day boundary.
7. **P1** Review `audit.py` false positives: request-log/raw archive alignment, legacy run accounting, no mutating PRAGMA or DB initialization.
8. **P1** Check scheduler policy and exit codes. User intends initial backfill on Oct 19, daily latest snapshot from Oct 20, then historical backfill, without wasting requests on already-observed head.
9. Document precisely which checks are PASS, WARN, FAIL, UNKNOWN; identify remaining production blockers.

## Local commands — NO LIVE collection until user approval
```powershell
git pull
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
$report = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2_audit_report'
python .\raw_v2\audit.py --output-dir $out --report-dir $report
python .\raw_v2\recover.py --output-dir $out
```
Read-only audit exit 2 on FAIL; do not interpret WARN as verified historical completeness. Run local offline unit tests before any Meta request. Never include credentials in reports.

## User preferences
- Distinct account coverage first, posts second.
- No Meta API live calls by assistant; user runs PowerShell live commands.
- Existing local data is authoritative and must be preserved.
- Goal: finish safe collection quickly, not build new product features.
- Requested external review by Astra; high-effort Codex model may be used in user's own Codex environment, but the assistant cannot select its model from GitHub tools.
