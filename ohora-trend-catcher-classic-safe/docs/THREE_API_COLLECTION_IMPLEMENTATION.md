> **2026-10-19 p6 정책 보강:** `estimated_time_to_regain_access`를 사용률에서 제외하고 HTTP 2xx라도 Meta `error` 본문이면 저장 없이 레인 중단. `tests/test_three_api_policy_hardening.py` 2개 추가, CI 연결. **기존 Windows 66/66 PASS, 신규 포함 68개는 아직 재검증 전.** 실제 Meta API/토큰/운영 DB 미사용. 실수집 전 HTTP 클라이언트·인증 분리·API 헤더 실제 검증·쿼터 공유 여부 확인 필수.

> **2026-10-19 p6 통합:** `raw_v2/three_api_offline_runner.py`의 `envelope_fixture=True` 모드에서 A/B/C lease→모의 HTTP 응답→사용량 85% 사전 게이트→Meta 정규화→원자적 staging→검증 커서 인계까지 연결. `tests/test_three_api_envelope_runner.py` 4개 신규 및 CI 추가. **직전 56/56 Windows PASS**, 이후 신규 6+4개를 포함한 **66개 테스트는 재검증 전**. 실제 Meta API/운영 DB/토큰 미사용. 주의: 기존 `meta_fixture=False, envelope_fixture=False`는 오프라인 회귀용으로 사용량 헤더 게이트 없이 합성 데이터 저장하므로 실제 수집 경로로 절대 사용 금지.

> **2026-10-19 p6 HTTP 합성 응답 게이트:** `raw_v2/three_api_http_fixture.py`에서 모의 HTTP 상태·사용량 헤더·Meta 미디어 응답을 연결해 **쿼터 확인 후 원자적 staging 저장**하도록 구현했다. HTTP 오류/사용량 미확인/85% 이상이면 레인 쿨다운과 저장 차단. `tests/test_three_api_http_fixture.py` 6개 추가 및 CI 등록. **이전 56/56 Windows PASS 확인, 신규 포함 62개는 아직 재검증 전.** 라이브 네트워크·토큰·운영 DB 미사용. 실제 HTTP 클라이언트와 인증 검증은 미구현.

> **2026-10-19 p6 사용량 정책:** `raw_v2/three_api_usage.py`에서 `X-App-Usage`·`X-Business-Use-Case-Usage` 합성 헤더를 해석하고 사용량 미확인 또는 85% 이상이면 레인별 fail-closed 쿨다운을 적용하는 오프라인 정책을 추가했다. HTTP 429/서버 오류/인증·권한 오류 분류 포함. 신규 테스트 7개와 CI 연결, **전체 56개 테스트는 재검증 전**(사용자가 이전 실행에서 49개 실행 보고, 마지막 `OK` 확인되지 않음). 실제 Meta 호출·운영 DB 변경 없음. 라이브 HTTP 어댑터 및 에러 응답 연동은 미구현.

> **2026-10-19 p6 Meta 응답 정규화:** `raw_v2/three_api_meta_normalizer.py`에 Business Discovery 응답 정규화(허용 필드만 저장, `paging.next` URL 제거, 오류/중복 아닌 유효성 검사)를 구현하고 오프라인 실행기에 `meta_fixture=True`로 연결했다. 신규 테스트 7개 및 CI 등록. 기존 Windows 37/37 PASS, 이후 신규 12개 포함 **49개 재검증 전**. 실제 API 호출·토큰 사용·운영 DB 변경 없음. Meta 실제 응답과의 호환성은 미검증.

## 2026-10-19 offline runner integration milestone
- Added `raw_v2/three_api_offline_runner.py` with injectable synthetic fixture `fetch_page(intent,cursor)`; leases A/B/C, builds official 294-account intent, resolves the verified prior cursor, atomically stages normalized posts and cursor evidence. No credentials, network calls, or production DB access.
- Five new `tests/test_three_api_offline_runner.py` cover first page, A-to-C cursor chain, invalid response rollback, fixture failure, and terminal page. CI includes them. **Windows regression now totals 42 tests pending rerun** (prior 37/37 PASS).
- This is **NOT** a live 3-API engine: fixture injection is not a Meta client, and current coordinator snapshot plan does not implement daily front/catchup/history or anchoring against concurrent new posts. Do not use it to collect live data without separately approved adapter and isolated pilot.


## 2026-10-19 atomic offline staging milestone
- `PageEvidenceStore.commit_staged_page()` now writes up to four normalized post payloads to `staging_posts` **in the same coordinator SQLite transaction** as page cursor evidence and job completion. It rejects duplicate/invalid post IDs, oversized pages, invalid cursor edges and stale leases; failures roll back staged rows and job status.
- Added five synthetic staging tests to `tests/test_three_api_evidence.py`; existing CI test discovery pattern includes them. **These tests have not yet been rerun or verified on Windows/GitHub Actions.**
- `staging_posts` is an isolated proof-of-concept schema, **not** RAW v2 production data storage. There is still no Meta live-call adapter, token validation, durable cross-run snapshot anchoring, or production migration approval. No real API calls or production DB writes were made.

# Three-API collection — implementation gate (2026-10-19)

## Status
**Offline planner, coordinator, cursor validator and transactional evidence state are implemented** (`raw_v2/three_api_plan.py`, `three_api_coordinator.py`, `three_api_adapter.py`, `three_api_checkpoints.py`, `three_api_paging.py`, `three_api_evidence.py`). **Live three-token execution NOT implemented or authorized.** The existing foreground `daily_scheduler.py` remains unchanged and is the only currently validated live path. Do not launch three copies of it against the same SQLite store.


## 2026-10-19 offline implementation checkpoint (supersedes planner-only status)
- Coordinator distributes 294 × 3 logical jobs; per-lane persisted cooldown and leases. Evidence-aware leases require a nonterminal, committed predecessor page. Bare `Coordinator.complete()` is blocked when a `PageEvidenceStore` is active.
- `PageEvidenceStore.commit_page()` validates actual Meta cursor-edge shape and lease expiry; stores the predecessor cursor, next cursor, nonterminal flag and opaque receipt in one transaction with job completion. It rejects stale leases, missing/terminal predecessors, duplicate receipts and cursor cycles. **Receipt is supplied by the caller and is NOT independently proven to reflect a completed external data write.**
- `tests/test_three_api_evidence.py` includes simulated rollback, expired lease, direct-completion bypass, terminal boundary and page-2 chain cases; GitHub CI workflow includes these tests. **CI result for the latest commit is not yet verified.** All tests are synthetic and make no Meta requests.
- **Remaining blockers:** fully integrated staging writer and receipt reconciliation, account-level post/head anchor continuity, cross-app quota confirmation, daily-first/catchup/history scheduler, live B/C credential validation, supervised isolated-DB pilot, and user approval before any production DB switch.
- A's historical `.env.local` path was found on the user's PC; user prepared B/C credential files on Desktop but neither was validated in this stage. Never upload or expose tokens. Original single-API operation is unchanged.

## Requested schedule
- Three separately credentialed Meta identities A/B/C, subject to verification that quota limits are actually independent.
- Round 1: A accounts 1–150 page 1; B 151–294 page 1; C 1–150 page 2.
- Round 2: A 151–294 page 2; B 1–150 page 3; C 151–294 page 3.
- Round 3 onward: prioritize pending catchup, then history toward 365-day boundary; never overwrite history cursor with front cursor.
- Four media records per page; stop each lane at observed X-App-Usage >=85% or when usage header unavailable; each lane has its own persisted cooldown.
- A daily first pass must check *new* posts for all 294 accounts. Page numbers 1–3 describe initial snapshot positions only; a moving feed cannot safely be indexed by offset. Track observed post IDs, prior head anchor and real Meta cursors; if anchor not found, enqueue catchup until connected.

## Safety requirements before any live activation
1. Validate all three Meta credentials without storing tokens in GitHub, logs or DB; confirm their X-App-Usage counters are independent. Token count alone does not imply quota multiplication.
2. One **single coordinator** must hold the existing cross-process DB lock while leasing accounts and persisting page progress; concurrent `collector.run` calls cannot safely share the current `slots` table (single global slot) or current `accounts.backfill_cursor`.
3. Add per-lane cooldown and run/slot identifiers; preserve legacy global cooldown and all existing checkpoints during migration. A restart must never reset `ready_at`.
4. Persist account + phase + page lease and expected cursor before API call; commit sanitized response and new cursor atomically; recover unknown responses via idempotent post IDs and request IDs.
5. Reconcile page 2/3 requests with anchor IDs so newly posted content cannot shift offsets. Preserve all queued catchup gaps and never mark historical completion without rooted cursor evidence.
6. On any failure, missing usage header, identity mismatch or WARN audit without explicit approval, halt safely. Do not auto-bypass safeguards.
7. Offline tests: exact 294 × 3 page coverage, overlapping workers, interrupted writes, usage 84/85/missing, day rollover, cursor shift, new >12 posts/day, 8 blocked accounts, partial pages, quota sharing, existing DB migration. Then single-lane live pilot and independent lane pilot before full rollout.

## Plan-only command
```powershell
python .\raw_v2\three_api_plan.py --source $src
```
This only reads the official CSV and prints a JSON schedule. It makes no API requests or DB writes.

## Existing collector
Keep the existing live scheduler running until a separate tested implementation has been approved. Do not alter the 4-post limit or 85% stop rule in the current live process.
