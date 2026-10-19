> **2026-10-19 p6 정책 보강:** `estimated_time_to_regain_access`를 사용률에서 제외하고 HTTP 2xx라도 Meta `error` 본문이면 저장 없이 레인 중단. `tests/test_three_api_policy_hardening.py` 2개 추가, CI 연결. **기존 Windows 66/66 PASS, 신규 포함 68개는 아직 재검증 전.** 실제 Meta API/토큰/운영 DB 미사용. 실수집 전 HTTP 클라이언트·인증 분리·API 헤더 실제 검증·쿼터 공유 여부 확인 필수.

> **2026-10-19 p6 통합:** `raw_v2/three_api_offline_runner.py`의 `envelope_fixture=True` 모드에서 A/B/C lease→모의 HTTP 응답→사용량 85% 사전 게이트→Meta 정규화→원자적 staging→검증 커서 인계까지 연결. `tests/test_three_api_envelope_runner.py` 4개 신규 및 CI 추가. **직전 56/56 Windows PASS**, 이후 신규 6+4개를 포함한 **66개 테스트는 재검증 전**. 실제 Meta API/운영 DB/토큰 미사용. 주의: 기존 `meta_fixture=False, envelope_fixture=False`는 오프라인 회귀용으로 사용량 헤더 게이트 없이 합성 데이터 저장하므로 실제 수집 경로로 절대 사용 금지.

> **2026-10-19 p6 HTTP 합성 응답 게이트:** `raw_v2/three_api_http_fixture.py`에서 모의 HTTP 상태·사용량 헤더·Meta 미디어 응답을 연결해 **쿼터 확인 후 원자적 staging 저장**하도록 구현했다. HTTP 오류/사용량 미확인/85% 이상이면 레인 쿨다운과 저장 차단. `tests/test_three_api_http_fixture.py` 6개 추가 및 CI 등록. **이전 56/56 Windows PASS 확인, 신규 포함 62개는 아직 재검증 전.** 라이브 네트워크·토큰·운영 DB 미사용. 실제 HTTP 클라이언트와 인증 검증은 미구현.

> **2026-10-19 p6 사용량 정책:** `raw_v2/three_api_usage.py`에서 `X-App-Usage`·`X-Business-Use-Case-Usage` 합성 헤더를 해석하고 사용량 미확인 또는 85% 이상이면 레인별 fail-closed 쿨다운을 적용하는 오프라인 정책을 추가했다. HTTP 429/서버 오류/인증·권한 오류 분류 포함. 신규 테스트 7개와 CI 연결, **전체 56개 테스트는 재검증 전**(사용자가 이전 실행에서 49개 실행 보고, 마지막 `OK` 확인되지 않음). 실제 Meta 호출·운영 DB 변경 없음. 라이브 HTTP 어댑터 및 에러 응답 연동은 미구현.

> **2026-10-19 p6 Meta 응답 정규화:** `raw_v2/three_api_meta_normalizer.py`에 Business Discovery 응답 정규화(허용 필드만 저장, `paging.next` URL 제거, 오류/중복 아닌 유효성 검사)를 구현하고 오프라인 실행기에 `meta_fixture=True`로 연결했다. 신규 테스트 7개 및 CI 등록. 기존 Windows 37/37 PASS, 이후 신규 12개 포함 **49개 재검증 전**. 실제 API 호출·토큰 사용·운영 DB 변경 없음. Meta 실제 응답과의 호환성은 미검증.

> **2026-10-19 p6 추가 구현:** `raw_v2/three_api_offline_runner.py`에서 A/B/C lease → 공식 294계정 intent → 주입된 합성 페이지 응답 → `PageEvidenceStore.commit_staged_page()`를 연결했다. `tests/test_three_api_offline_runner.py`에 오프라인 통합 5개를 추가하고 GitHub Actions에 등록했다. 사용자 Windows에서 기존 37/37 PASS 확인, **새 통합 포함 총 42개는 아직 재검증 전**. Meta 호출·토큰 읽기·운영 DB 변경 없음. 주입식 fetcher는 합성 테스트용이며 live adapter/일일 스케줄러는 미구현. `docs/THREE_API_COLLECTION_IMPLEMENTATION.md` 참조.

> **2026-10-19 p6 최신 상태 (아래 이전 요약보다 우선):** 3-API 오프라인 코디네이터·어댑터·커서 검증·증거 트랜잭션 코드를 GitHub `main`에 구현했다. [설계·실행 게이트](docs/THREE_API_COLLECTION_IMPLEMENTATION.md) · [증거 저장](raw_v2/three_api_evidence.py) · [Coordinator](raw_v2/three_api_coordinator.py) · [오프라인 CI](.github/workflows/three-api-coordinator.yml). 증거 저장 모드에서는 직전 페이지의 유효한 비종료 커서가 있어야 다음 페이지를 배정하고, 증거 없는 단순 완료를 차단한다. 만료 lease·잘못된 커서·중복 receipt의 커밋을 거부한다. **신규 테스트 코드는 작성되고 CI에 연결됐으나 최신 CI 성공은 아직 확인되지 않았다.** 실제 3개 API 수집 실행 경로·스테이징 저장 영수증 검증·일일 front/catchup/history 통합·앵커 연속성은 **미구현/미검증**. API A 기존 인증파일 경로는 사용자 로컬에서 존재 확인(True), B/C 파일은 사용자 바탕화면에 준비됐으나 권한/유효성/독립 quota는 미검증. **운영 `collection.sqlite`와 기존 수집기는 변경 금지; Meta API 실호출 및 운영 전환 금지(별도 승인·pilot 필요).** 코드 커밋 `f6e57ea`, 설계 상태 업데이트 `0a71bcf`.

> **2026-10-19 인수인계 누락 재발 방지:** 기능·설계 문서만 GitHub에 커밋했다고 새 채팅방 인수인계가 완료된 것은 아니다. 변경 시 `HANDOFF.md`와 `STATUS.md` 최상단을 함께 갱신하고, GitHub 최신 `main`에서 두 문서와 원문 링크를 **재조회·검증**한 뒤에만 인수인계 완료라고 보고한다. 완료 보고는 설계 저장 / 인수인계 동기화 / 런타임 구현 / 실수집 검증을 구분한다. 규칙: [AGENTS.md](AGENTS.md) 11~14항.\n\n# 2026-10-19 최우선 인수인계 — 3개 Meta API 운영 설계 / 구현 상태 (신규 채팅방 필독)

> **최신 사용자 결정:** 현재 검증된 단일 API A 수집을 계속 유지한다. API B 토큰은 실제 인증 시 HTTP 401, Meta OAuthException `190/463`(만료)로 확인되어 재발급 대기 중이다. API C는 아직 유효 인증 검증 전이다. **B/C 인증이 확보되면 소규모 권한·실제 수집·독립 quota 테스트 후에만 3-API 전환을 검토한다. 지금 3개 수집기를 실행하지 않는다.**
>
> **설계 원문(반드시 읽기):** [3-API 수집·실행 전 안전 기준](docs/THREE_API_COLLECTION_IMPLEMENTATION.md) / **계획 전용 코드:** [raw_v2/three_api_plan.py](raw_v2/three_api_plan.py). 두 파일은 GitHub `main`에 존재하지만 **라이브 다중 토큰 수집기는 미구현**이다. 계획 출력은 실제 API/DB 호출을 하지 않는다.
>
> **사용자가 제안한 초기 배분(2라운드, 65분 간격 목표, 계정별 페이지당 4개):**
>
> | 라운드 | API A | API B | API C |
> |---|---|---|---|
> | 1 | 공식 1~150번, 페이지 1 (1~4) | 공식 151~294번, 페이지 1 (1~4) | 공식 1~150번, 페이지 2 (5~8) |
> | 2 | 공식 151~294번, 페이지 2 (5~8) | 공식 1~150번, 페이지 3 (9~12) | 공식 151~294번, 페이지 3 (9~12) |
>
> 라운드 3 이후에는 **매일 KST 최신 front 우선 → 누락 catchup → 과거 history**를 유지하고, 가용 API 용량으로 과거 6개월 이상/기존 365일 경계 확보를 지향한다. 위 페이지 숫자는 **초기 배분을 설명하는 논리적 위치**이지 실제 운영에서 고정 오프셋으로 요청해도 된다는 뜻이 아니다. 실제 Meta cursor·게시물 ID 앵커를 계정별로 보존해야 한다.
>
> **API 안전 기준:** lane별 X-App-Usage 관측값 `>=85%` 또는 신뢰 가능한 사용률 헤더 누락 시 해당 lane 후속 API 요청 중단; lane별 영속 쿨타임 및 기존 `ready_at` 보존. 단순히 토큰이 3개라고 사용량 한도가 독립인 것은 아니다. 실제 응답을 통해 앱/할당량 공유 여부 확인 후 실행. **현재 DB에는 공통 슬롯·커서가 있으므로 3개의 기존 `daily_scheduler.py`를 동일 SQLite에서 병렬 실행 금지.** 단일 coordinator, lane별 lease·쿨타임·재시작·멱등성 설계와 오프라인·소규모 실수집 검증이 선행되어야 한다.
>
> **현행 운영은 그대로:** 기존 Python RAW v2.1 `daily_scheduler.py --policy bootstrap-history --live --acknowledge-warnings`와 사용자 Windows 로컬 `%LOCALAPPDATA%\OHORA_RAW_v2\collection.sqlite`의 수집 상태·cursor·백업을 수정하거나 초기화하지 말 것. WARN을 PASS로 표기하지 말 것. DB·인증·Meta live 테스트는 사용자 승인 없이 실행하지 말 것.
>
> **후속 작업:** (1) B/C 인증 새 토큰 발급·유효기간 확인 (2) 각 인증 조회/Business Discovery 권한 검증 (3) X-App-Usage 독립성 검증 (4) 안전한 멀티-lane coordinator 구현·오프라인 테스트 (5) 별도 시험 DB 소규모 live pilot (6) 승인 후 본 수집 전환. **기존 계획 문서만 보고 '3-API 구현 완료'라고 말하지 말 것.**
>
---

> **2026-10-19 계정별 수집 현황표 추가:** 독립 읽기 전용 `raw_v2/account_collection_status.py`와 합성 테스트를 추가했다. 운영 우선순위는 KST 일일 front → catchup → 기존 커서 history, 6개월 이상은 목표이며 365일 고정 완료 정책은 변경하지 않았다. 계정별 고유 게시물 날짜 범위, 마지막 성공 front, KST 오늘 조회, catchup, history 커서 증거를 CSV/MD로 출력한다. 자세한 실행법·필드 정의: [계정별 수집 현황표](docs/RAW_V2_ACCOUNT_COLLECTION_STATUS.md). **운영 DB 실검증은 아직 수행하지 않았다.**\n\n> **2026-10-19 최신 로컬 운영 기록:** 사용자가 Windows에서 10계정 History 실수집(10/10 HTTP 200, 신규 40) 및 직후 audit **PASS** 확인. 공식 294계정 중 성공 286·조회 실패 8, 누적 고유 게시물 1,330·관측 1,350, integrity/observation/coverage 0/0/0, 미해결 배치 0. **무인 운영 미승인, 실제 365일 전량 완전성 미검증.** GitHub 문서는 사용자 로컬 DB를 대신하지 않는다.
>
> **먼저 읽을 문서:** [전체 장애·해결 기록](docs/RAW_V2_2026-10-19_TROUBLESHOOTING_CHRONICLE.md) · [오류 분류/발견 시 대응 SOP](docs/RAW_V2_ERROR_HANDLING_RUNBOOK.md) · [향후 작업 및 인수 기준](docs/RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md) · [실행 가이드](raw_v2/README.md). 기존 날짜별 60/70분 또는 이전 게시물 개수는 당시의 과거 스냅샷이다.

## 2026-10-19 RAW v2.1 검수 완료 — 아래 과거 기록보다 우선

- 기준 HEAD `500523b1c18e11863c025c0418f84d6be00e80b4`, 시작 브랜치 main, 미커밋 변경 없음. 검수 브랜치 `codex/raw-v2-safety-review`에서 확인된 잔여 결함만 수정.
- Windows Python 3.11: `python .\tests\run_offline.py` **93/93 PASS**. 러너에서 외부 소켓 연결 차단. PowerShell 구문 검사·Python 컴파일·공식 294계정 dry run 통과.
- 전체 rooted history 커서 증거와 원본 대조, 완료+NULL 커서 재검증 대상 선택, history-only 당일 최신화 선행 조건, 복구의 전체 백업/상태 검증 및 중단 경계 수정.
- 공통 대기 정책: `max(슬롯 종료+63분, 슬롯 시작+65분, 저장된 ready_at)`. 기존 ready_at을 덮어쓰거나 앞당기지 않음. 65분 종료 후 대기는 채택하지 않음.
- 운영 DB 읽기 전용 진단 **WARN**: 294계정, 관측263계정, 게시물1,178, 미디어3,152, 관측1,178. 무결성/관측 오류0, 미검증 완료10. 완료+NULL 커서는 실제 DB0건이며 합성 회귀로 검증.
- SQLite backup API 복제본에서만 호환 마이그레이션 시험: 기존13개 테이블의 원래 행 변경/누락0, 무결성ok, 원본 DB SHA-256 전후동일. 운영 DB 복구·Meta 호출 없음. 실제 API/장기 운영/1년 완전성은 미검증, **제한된 시험만 가능**.
- 실행·중단 조건·롤백: [raw_v2/README.md](raw_v2/README.md). 결함·검증·남은 제한: [검수 보고서](docs/RAW_V2_REVIEW_2026-10-19.md). project-book 등록 경로/대상은 확인되지 않아 갱신하지 않음.

---

# OHORA Trend Catcher — HANDOFF (2026-10-18 22:49 KST)

> **최신 기준(2026-10-19):** 아래 장의 이전 60분·70%·70분 시작 간격 등은 과거 기록이며 새 daily-first 정책은 다음 최신 항목을 따른다.

## 2026-10-19 최신 운영 정책 — DAILY-FIRST (아래 과거 기록보다 우선)

**권장 엔트리:** `raw_v2/daily_scheduler.py`. 기존 `collector.py`는 수집 엔진으로 계속 사용하며,
**사용자 로컬 `collection.sqlite`와 수집·커서·관측 이력은 삭제하거나 초기화하지 않는다.**

- **1순위** KST 오늘 공식 목록 1~150번의 최신 최대 4개, **2순위** 151~294번의 최신 최대 4개. 성공한 계정은 오늘 다시 최신 조회하지 않으며, 기존 수집기의 오늘 성공한 `front` 요청 로그도 반영한다. 한도/오류로 슬롯이 일찍 끝나면 미완료부터 재개한다.
- **3순위** 전체 정상 대상 최신화 후 `catchup` 누락 구간 회복. **4순위** `backfill_cursor` 기준 과거 365일 미완료 계정 수집. 접근 불가/일일 재시도 소진 계정은 별도 예외로 보고하고, catchup/history 반복 실패는 계정별·일별 최대 2회 후 다음 날 재시도하며, 294/294 성공이라고 표시하지 않는다.
- Graph 배치당 5 하위요청, 최대 150 **서로 다른** 계정/슬롯, Meta **X-App-Usage** 제공 수치 중 최댓값 85% 도달 또는 사용량 헤더 누락 시 후속 배치를 중단. 사용량은 요청 **후** 확인하므로 초과 가능하고, 63분 경과가 실제 API 한도 회복을 보증하지 않는다.
- 슬롯 종료 `finished_at + 63분` 뒤 재개. **기존 `slots.ready_at`은 소급 변경하지 않는다.** 신규 스케줄러는 이 DB 시각 하나로 전경 대기한다.
- DB에 `daily_account_state`·`catchup_jobs` 테이블을 호환 추가한다. 새 요청 ID에 `run_id`를 포함해 실행 간 충돌을 방지하고, 성공 게시물·관측·커서·로그·슬롯·일일 상태를 하나의 트랜잭션으로 기록한다. 이전부터 있던 catchup이 새로운 최신 조회 때문에 사라지지 않도록 대기열에 보관한다.
- **검증 범위:** GitHub Actions Python 3.11 오프라인 38/38 PASS. 기존 Windows DB를 사용한 마이그레이션·Meta 실호출·실제 1년 완전성은 **미검증**이다. 별도 Windows 예약 작업·서비스는 설치하지 않았다.

### Windows PowerShell 실행

```powershell
git pull origin main
python -m unittest discover -s tests -p 'test_*.py' -v
$src = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브\2차 프로젝트 데이터\account_list.csv'
$envFile = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection\.env.local'
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
Test-Path $src
Test-Path $envFile
python .\raw_v2\daily_scheduler.py --source $src --output-dir $out
# 실수집을 시작하기로 결정한 경우에만 아래 명령을 직접 실행:
python .\raw_v2\daily_scheduler.py --source $src --env-file $envFile --output-dir $out --live
```

- `--live` 없이 실행하면 공식 목록 검증 및 정책 출력만 하며 DB/Meta를 변경하지 않는다.
- `--live`는 전경에서 **계속 동작**하며 63분 쿨타임 동안 대기한다. 창을 열어두고 PC가 켜져 있어야 하며, Ctrl+C로 안전하게 중단한다.
- `--once --live`는 요청된 수집 실행을 최대 한 번 수행하고 대기하지 않는다. 사전에 API 사용량/인증 상태를 확인한다.
- 최초 실수집 전 `collection.sqlite`를 **일관된 SQLite 백업**으로 저장할 것. 과거 이력의 실제 이상 여부는 로컬 DB로 별도 검사해야 한다.
- 예전 `run_70m_loop.ps1`은 남겨둔 **legacy balanced 모드**이므로 일일 최신화 정책 운영에는 사용하지 않는다.


---


## 2026-10-19 — Important: Next trial is four posts × 150 accounts

**User explicitly chose 4×150, not 5×150 or 25/50 large-page experiments.** 294 official accounts → 150+144 ideal per complete first account sweep, but limited by actual Meta quota. Current live local DB has 630 unique posts from 130 attempts (126 successful, 4 invalid-target). Never reset or overwrite it. User wants next API limit-window experiment **after actual cooldown**, not now. No background API calls or scheduled task created.

- Collector CLI defaults `--limit 4` and allows `--limit 5` for compatibility/rollback; run request and response-length validation follow selected page size; account slot cap still 150, 60min cooldown from finish.
- Maintains two independent paths: front latest & catchup vs history cursor. FRONT never overwrites established backfill cursor, and 4-post page rollover correctly resumes prior 5-post checkpoints. Page terminal/noncursor and one-page account guards improved.
- `config.backfill_anchor_utc` is inserted additively in same `raw-v2.1` SQLite; for legacy DB equals `MIN(runs.started_at)`, for new DB initial connection timestamp. `--history-days 365` cutoff now pinned to that anchor. Existing posts/observations/slots/cursors unchanged.
- New `collection_log.csv` requested_post_limit is dynamic from `request_log.usage_json` via SQLite JSON extract (no schema version change). Old run files remain untouched.
- Loop script now defaults 4 posts, waits max(60m since prior finish, 70m since prior start), is foreground/manual only. No scheduler installed.
- CI **28/28 Python 3.11 synthetic PASS**: run `39140956504` (push SHA `aa440d7e64511d9347b6ec7e8ccc246fb474b53e`). Windows tests and live new 4x150 API calls NOT VERIFIED. User must `git pull origin main` then test locally.
- When next Meta usage window permits, run one test (do NOT auto-run unless user explicitly instructs): `python .\\raw_v2\\collector.py --source $src --env-file $envFile --output-dir "$env:LOCALAPPDATA\\OHORA_RAW_v2" --mode balanced --limit 4 --batch-size 5 --max-batches 30 --stop-usage 70 --live`. Compare usage_max, per-account posts, 4 error accounts; only later examine true history pages and actual quota recovery.

## 2026-10-18 — Corrections after first live run (read first)

- The user's intended unit is **150 accounts continuously × limit(5) per account, then 60-minute rest counted from the FINISH of that unit**. The earlier 70-minute timer was a start-to-start estimate only, assuming ~10 minutes to collect. The previous global 70-minute lock after just 5-account pilot was incorrect and has been replaced in `raw_v2/collector.py`.
- The existing live pilot on user's local Windows: `20261018T143306Z_2840`, KR_001..005, 5/5 API success, 25 new posts; `verify.py` PASS; 6 missing `like_count` fields, all VIDEO/REELS, exact provider reason undetermined; `usage_max:0.0` is not proof of no quota expense.
- New `slots`/`slot_accounts` tables handle partial continuation and per-slot unique account counting to 150. If last run from legacy v2.1 is recent, adopt its 5 accounts into current slot (145 remain); otherwise start a new quota slot after elapsed interval. Once 150 done or API halts, cool down **60 minutes after finished_at**. No external task scheduler installed. Per-account page/backfill checkpoints and existing data preserved.
- Updated `raw_v2/run_70m_loop.ps1` defaults to MaxBatches 30, 60min sleep *after* completion; despite legacy filename it no longer has start-to-start 70m behavior. Default output is `%LOCALAPPDATA%\\OHORA_RAW_v2` (not OneDrive). GitHub Actions is now available at user's discretion, but not required.
- Local synthetic **22/22 tests PASS** on Linux Python 3.13.5 (including 5→145 continuation and old pilot adoption). New Windows test run & first full live 150-account slot remain outstanding. Run local Windows offline unittest again after `git pull`, then explicit single-run CLI with `--max-batches 30` and inspect diagnostics before enabling repeated foreground loop. Do not commit tokens or RAW data.
- Latest collector tested Git blob SHA `6e89ea7796aeea06c2f49a8bef4d5cc7459d88f1`; tests blob SHA `df4cf10248e331a91b87b48b02393b37dbf4d681`. Last collector fix commit `87742d9830372111ab04713aed8ee73cff79d4ed`.

## ① 목표·용도·확정 요구·기술
- KDT 2차 OHORA Instagram Trend Catcher. Official 294 accounts KR100/US101/JP93; immutable source account keys; prospective 4-tab dashboard concept (raw explorer / weighted trend / AI assistant / collection observability), not developed here.
- Newly approved collection intent: from most recent toward historical 1 year (ideally 2), five media items maximum per account API request, 7-day client-side logical periods, 70-minute cycles, resumable account+page checkpoints, time-stamped likes/comments/followers observations.
- Python 3.11 stdlib, Meta Facebook Graph API Business Discovery Batch, SQLite WAL, CSV, sanitized JSON; source docs/RAW_V2_SCHEMA.md and docs/OHORA_RAW_COLLECTION_EXECUTION.md.

## ② 완료 기능·변경·결정
- Opt-in isolated raw_v2/collector.py added. Do not modify experiments/rolling_backfill.py, full_batch_collector.py, legacy DB/CSV or stored data. Separate output raw_v2_results/ excluded by .gitignore.
- For one app, prioritizes due latest front pages (roughly daily) and otherwise older cursor; per-account queue fairness and post ID overlap/catchup, blocked known #110 accounts. Max one account subrequest per pass, API usage halts after batch; real throughput not guaranteed.
- Separate persisted posts/post_media, per-observation likes/comments/metric NULL flags, account snapshots, field status, per-run original-list copy, raw JSON and file hashes. Carousel additional children pages flagged partial; no silent completion.
- raw_v2/verify.py offline read-only SHA/row-count/SQLite-integrity checker; run_70m_loop.ps1 bounded foreground opt-in Windows runner. Add tests/test_raw_v2.py and CI workflow. Original user instructions preserved at docs/OHORA_RAW_COLLECTION_EXECUTION.md.

## ③ 테스트 명령·결과/미검증
- PASS: Linux Python 3.13.5 local python -m unittest discover -s tests -p test_raw_v2.py -v => 20/20 OK; py_compile all three Python files OK; no real Meta HTTP.
- Fake client proves 5 subrequests mocked success, repeat likes changes, missing/null/0/not_tested, 7-day bucket metadata, carousel partial, checksum tamper failure, account blocked/tested errors, safe post-request 70% stop, 70-minute cooldown and lock.
- NOT VERIFIED: Windows PowerShell runner/test, Meta live field support/rate/cursor/like root cause, 1/2 year completeness, CI workflow actual run status. None of this should be called production-successful.

## ④ 상태와 중단 지점
- Implemented + offline-tested, GitHub feature branch reviewed. Main promotion only when commit SHA and docs validated.
- Live pipeline remains STOPPED: user's local account_list.csv and .env.local are not available to this environment, so cannot honestly start collecting. New scheduler is not installed or running.

## ⑤ 오류·근거·시도·재시도 금지·대안
- Prior verified snapshot in REQUIREMENTS.md 743/1880 posts missing like_count; old API quota error4/110 may be separate. New field_observations distinguishes requested and absent/null/returned vs not_tested, and request_log distinguishes subrequest API failure. Missing key with HTTP 200 does not prove quota, permission, media-type or Meta policy as root cause.
- Existing historical cursor support is code-level only; a real two-page continuation test is necessary. If Meta refuses embedded after, do not silently advance or repeatedly call with same failing cursor.
- Alternative designs considered: two subrequests per account per 70m (more history but greater cost) versus adaptive one subrequest per pass (selected until measured). Stop at 70% post-response, no quota bypass or automatic exponential retries.

## ⑥ GitHub 브랜치·SHA·경로
- Repo: hibi89/ohora-trend-catcher; implementation branch: feature/raw-v2-20261018, based on pre-work main afc6e01c7c5490cf9003c09e2709416522d70901.
- Core files: raw_v2/collector.py, raw_v2/verify.py, raw_v2/README.md, raw_v2/run_70m_loop.ps1, tests/test_raw_v2.py, docs/RAW_V2_SCHEMA.md, docs/OHORA_RAW_COLLECTION_EXECUTION.md, .github/workflows/raw-v2-tests.yml; README, STATUS.md, HANDOFF.md, .gitignore.
- Latest pushed SHA and main promotion must be checked from GitHub rather than inferred from documentation; refer to BOOK.md for verified SHA.

## ⑦ 실행 명령·환경·Production
- Runbook: raw_v2/README.md; Python -m unittest discover -s tests -p test_raw_v2.py -v; python raw_v2/collector.py --source account_list.csv (DRY RUN).
- Live after real credentials and quota approval only: python raw_v2/collector.py --source account_list.csv --env-file <local-secret-file> --output-dir raw_v2_results --batch-size 5 --max-batches 1 --stop-usage 70 --live.
- Vercel Production URL: not applicable; dashboard was not built/deployed, this work only adds local RAW collector.

## ⑧ 원본·백업·인증 관리
- Authoritative source official account_list.csv and older latest5/latest1/latest10 SQLite/CSV remain user-held on Windows. These are not in GitHub; content/source bytes unverified remotely. No migration/overwriting.
- Actual token, IG ID, Meta app ID stored only in user's local credential file, never print/commit. New raw_v2_results/ local separate SQLite+run JSON/CSV; backup DB consistently including WAL/SHM after stopping process.
- This implementation uses network solely in opt-in --live runs; no media image binary downloads or external AI requests.

## ⑨ 우선순위·절차·완료 기준·승인 사항
1. GitHub pull main, test 20/20 on Windows (API free) and dry run source roster. Inspect that the source path and token file exist, without printing secrets.
2. Check Meta dashboard quota and caller professional account permissions. Pilot --live with batch size5/max-batches1 only. Inspect raw payload, field_support, like_missing audit, usage header, exact missing-field cases and verify.py.
3. Test two different cycles / nesting after cursor without skipping or refreshing old data incorrectly; scrutinize Reel/carousel like_count absence and field-specific controlled probes; do not assert causal diagnosis before controlled evidence.
4. Only after pilot success set a bounded 70m loop on user's PC and adjust MaxBatches by observed total_time; hourly recovery is not guaranteed. Track date coverage, per-account count, blocked states and archive results locally.
5. Feature completion requires actual Meta results and Windows runtime/credential/permission evidence; if unavailable status = partial, not done.

## ⑩ 갱신 일시(KST)·확인 시점·검증 범위
- Drafted 2026-10-18 22:49 KST. Local Python tests PASS; GitHub source files re-read confirmed; actual Windows/Meta access is unavailable here. Last remote commit to be verified after recording BOOK.
