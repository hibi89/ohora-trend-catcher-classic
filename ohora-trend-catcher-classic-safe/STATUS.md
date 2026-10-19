> **2026-10-19 p6 정책 보강:** `estimated_time_to_regain_access`를 사용률에서 제외하고 HTTP 2xx라도 Meta `error` 본문이면 저장 없이 레인 중단. `tests/test_three_api_policy_hardening.py` 2개 추가, CI 연결. **기존 Windows 66/66 PASS, 신규 포함 68개는 아직 재검증 전.** 실제 Meta API/토큰/운영 DB 미사용. 실수집 전 HTTP 클라이언트·인증 분리·API 헤더 실제 검증·쿼터 공유 여부 확인 필수.

> **2026-10-19 p6 통합:** `raw_v2/three_api_offline_runner.py`의 `envelope_fixture=True` 모드에서 A/B/C lease→모의 HTTP 응답→사용량 85% 사전 게이트→Meta 정규화→원자적 staging→검증 커서 인계까지 연결. `tests/test_three_api_envelope_runner.py` 4개 신규 및 CI 추가. **직전 56/56 Windows PASS**, 이후 신규 6+4개를 포함한 **66개 테스트는 재검증 전**. 실제 Meta API/운영 DB/토큰 미사용. 주의: 기존 `meta_fixture=False, envelope_fixture=False`는 오프라인 회귀용으로 사용량 헤더 게이트 없이 합성 데이터 저장하므로 실제 수집 경로로 절대 사용 금지.

> **2026-10-19 p6 HTTP 합성 응답 게이트:** `raw_v2/three_api_http_fixture.py`에서 모의 HTTP 상태·사용량 헤더·Meta 미디어 응답을 연결해 **쿼터 확인 후 원자적 staging 저장**하도록 구현했다. HTTP 오류/사용량 미확인/85% 이상이면 레인 쿨다운과 저장 차단. `tests/test_three_api_http_fixture.py` 6개 추가 및 CI 등록. **이전 56/56 Windows PASS 확인, 신규 포함 62개는 아직 재검증 전.** 라이브 네트워크·토큰·운영 DB 미사용. 실제 HTTP 클라이언트와 인증 검증은 미구현.

> **2026-10-19 p6 사용량 정책:** `raw_v2/three_api_usage.py`에서 `X-App-Usage`·`X-Business-Use-Case-Usage` 합성 헤더를 해석하고 사용량 미확인 또는 85% 이상이면 레인별 fail-closed 쿨다운을 적용하는 오프라인 정책을 추가했다. HTTP 429/서버 오류/인증·권한 오류 분류 포함. 신규 테스트 7개와 CI 연결, **전체 56개 테스트는 재검증 전**(사용자가 이전 실행에서 49개 실행 보고, 마지막 `OK` 확인되지 않음). 실제 Meta 호출·운영 DB 변경 없음. 라이브 HTTP 어댑터 및 에러 응답 연동은 미구현.

> **2026-10-19 p6 Meta 응답 정규화:** `raw_v2/three_api_meta_normalizer.py`에 Business Discovery 응답 정규화(허용 필드만 저장, `paging.next` URL 제거, 오류/중복 아닌 유효성 검사)를 구현하고 오프라인 실행기에 `meta_fixture=True`로 연결했다. 신규 테스트 7개 및 CI 등록. 기존 Windows 37/37 PASS, 이후 신규 12개 포함 **49개 재검증 전**. 실제 API 호출·토큰 사용·운영 DB 변경 없음. Meta 실제 응답과의 호환성은 미검증.

> **2026-10-19 p6 추가 구현:** `raw_v2/three_api_offline_runner.py`에서 A/B/C lease → 공식 294계정 intent → 주입된 합성 페이지 응답 → `PageEvidenceStore.commit_staged_page()`를 연결했다. `tests/test_three_api_offline_runner.py`에 오프라인 통합 5개를 추가하고 GitHub Actions에 등록했다. 사용자 Windows에서 기존 37/37 PASS 확인, **새 통합 포함 총 42개는 아직 재검증 전**. Meta 호출·토큰 읽기·운영 DB 변경 없음. 주입식 fetcher는 합성 테스트용이며 live adapter/일일 스케줄러는 미구현. `docs/THREE_API_COLLECTION_IMPLEMENTATION.md` 참조.

> **2026-10-19 p6 최신 상태 (아래 이전 요약보다 우선):** 3-API 오프라인 코디네이터·어댑터·커서 검증·증거 트랜잭션 코드를 GitHub `main`에 구현했다. [설계·실행 게이트](docs/THREE_API_COLLECTION_IMPLEMENTATION.md) · [증거 저장](raw_v2/three_api_evidence.py) · [Coordinator](raw_v2/three_api_coordinator.py) · [오프라인 CI](.github/workflows/three-api-coordinator.yml). 증거 저장 모드에서는 직전 페이지의 유효한 비종료 커서가 있어야 다음 페이지를 배정하고, 증거 없는 단순 완료를 차단한다. 만료 lease·잘못된 커서·중복 receipt의 커밋을 거부한다. **신규 테스트 코드는 작성되고 CI에 연결됐으나 최신 CI 성공은 아직 확인되지 않았다.** 실제 3개 API 수집 실행 경로·스테이징 저장 영수증 검증·일일 front/catchup/history 통합·앵커 연속성은 **미구현/미검증**. API A 기존 인증파일 경로는 사용자 로컬에서 존재 확인(True), B/C 파일은 사용자 바탕화면에 준비됐으나 권한/유효성/독립 quota는 미검증. **운영 `collection.sqlite`와 기존 수집기는 변경 금지; Meta API 실호출 및 운영 전환 금지(별도 승인·pilot 필요).** 코드 커밋 `f6e57ea`, 설계 상태 업데이트 `0a71bcf`.

> **2026-10-19 인수인계 누락 재발 방지:** 기능·설계 문서만 GitHub에 커밋했다고 새 채팅방 인수인계가 완료된 것은 아니다. 변경 시 `HANDOFF.md`와 `STATUS.md` 최상단을 함께 갱신하고, GitHub 최신 `main`에서 두 문서와 원문 링크를 **재조회·검증**한 뒤에만 인수인계 완료라고 보고한다. 완료 보고는 설계 저장 / 인수인계 동기화 / 런타임 구현 / 실수집 검증을 구분한다. 규칙: [AGENTS.md](AGENTS.md) 11~14항.

# 2026-10-19 최우선 인수인계 — 3개 Meta API 운영 설계 / 구현 상태 (신규 채팅방 필독)

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

# OHORA Trend Catcher — current implementation status

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


## 2026-10-19 — user-selected 4 posts × 150 accounts (next API window, NOT yet live-tested)

- User tested larger pages (15–25) earlier and prioritizes **150 distinct accounts per collection slot**, so a 150+144-slot scheme can cover the official 294-account first sweep if API headroom allows; 4 attempted accounts already returned Meta 110 / 2207013 and must remain reviewable, not silently deleted. The first 130 attempts already exist, with 630 cumulative unique posts.
- Live run after 5-account pilot: 125 account requests, 121 successes, 4 Invalid user id errors, 605 newly saved posts, cumulative 630, total_time_max 76%, stopped safely at configured 70% threshold. Stop after 125 does NOT imply 150 calls will fit if page size is 4; requires actual trial.
- New code sets CLI default `--limit 4` (5 remains allowed for rollback); 150 unique accounts per slot still enforced; 4 posts requested per account; current/latest front and historical backfill cursor independent; history uses persisted `backfill_cursor` and pages of 4, not a date filter. Old 5-post data preserved in existing v2.1 SQLite; no DB reset or schema version breaking change.
- Fixed `backfill_anchor_utc` persisted in config: for existing DB choose earliest prior recorded run; age threshold no longer slides with each execution. Guard front-gap when old latest ID absent, treat terminal 4-post history pages correctly and one-page accounts as done; preserve atomic posts+cursor transaction. This does NOT prove actual Meta chronological completeness; cursor time and history live navigation remain unverified.
- Run logging records actual requested limit=4 in new CSV, and 4-mode synthetic tests cover legacy 5→4 + front/history independence, terminal pages, frozen cutoff, no duplicate posts, SHA verification. **GitHub Actions Python 3.11 offline 28/28 PASS** at `aa440d7e64511d9347b6ec7e8ccc246fb474b53e` (run `39140956504`). More recent documentation/PowerShell only changes not part of that test run.
- `run_70m_loop.ps1`: `--limit 4`; when manually opted in, wait at least **60 minutes after finish** and at least **70 minutes start-to-start**; no Windows scheduled task installed. Next step: user PowerShell `git pull origin main`, offline `python -m unittest discover -s tests -p "test_raw_v2.py" -v`, then when cooldown ends explicit local 4×150 `--limit 4 --batch-size 5 --max-batches 30 --stop-usage 70 --live`, inspect runs and Meta dashboard. Do NOT call API on developer machine or set recurring user schedule without confirmation.

## 2026-10-18 late — Real 5-account validation and 150-account/60-minute policy restoration

- Windows Python 3.11: after CP949 read and SQLite test cleanup fixes, offline test 20/20 PASS (user log). User's local live pilot run `20261018T143306Z_2840`: 5/5 requests HTTP 200, 25 new posts, 25 observations, SHA/SQLite integrity PASS. `like_count` absent on 6/25 posts, all VIDEO/REELS (2 KR_001, 1 KR_003, 3 KR_004); cause still unproven; `usage_max=0.0` observed, NOT equivalent to zero request cost.
- User corrected cadence: **up to 150 distinct accounts continuously per slot, max 5 posts per account; wait 60 minutes after slot finishes** (or safely halts). ~70-minute start-to-start interval is only an estimate if collection lasts ~10 minutes. NOT a blanket 70-minute wait after a 5-account pilot.
- Implemented `slots` and `slot_accounts` bookkeeping in isolated cumulative SQLite; one partial run can be immediately continued until 150 accounts requested. Previous 5-account pilot is automatically adopted into the new slot if recent (<70 minutes) so the next run can do remaining 145. On API halt or reaching 150, cool down for 60 minutes after finish; skip until then; preserve original per-account/page checkpoints.
- Updated Windows opt-in loop to 30 batches × 5 accounts by default and 60-minute post-finish sleep; default local output under LOCALAPPDATA. Code/runner/docs/tests pushed to main. **Linux Python 3.13.5 synthetic 22/22 unit tests PASS** incl. 5→150, old-pilot adoption, slot cooldown. GitHub Actions/Windows revised tests and actual 150-account API run **NOT YET VERIFIED**.
- Next from user's existing Git repository root: `git pull origin main`, `python -m unittest discover -s tests -p "test_raw_v2.py" -v`, then explicit `--max-batches 30 --batch-size 5 --live` to resume when ready and observe actual `X-App-Usage`. Do NOT reset/move existing `%LOCALAPPDATA%\\OHORA_RAW_v2` DB, and do not commit credentials or official source CSV.

## 2026-10-18 — RAW v2 implementation, offline verified; Meta live not yet tested

- **Current approved direction:** 294 official accounts, account/page resume, 7-day client-side logical periods, maximum 5 media per account API page, 70-minute minimum start interval, 365 days (option 730) historical coverage, repeated likes/comments/followers observations.
- **Implemented**: raw_v2/collector.py, raw_v2/verify.py, raw_v2/run_70m_loop.ps1, raw_v2/README.md, docs/RAW_V2_SCHEMA.md, docs/OHORA_RAW_COLLECTION_EXECUTION.md (uploaded source retained), tests/test_raw_v2.py, .github/workflows/raw-v2-tests.yml. Added new-data ignore rule and README links; legacy collectors and databases untouched.
- **API cost design**: requesting both current and historical pages every cycle may double subrequests; chosen default uses at most one page per account per pass, first/newly due latest approximately every 24 hours, otherwise historical cursor. This trades per-cycle new post count for API budget. It is not guaranteed to deliver 5 unique posts every 70 minutes.
- **Data and diagnosis**: separate SQLite, run-scoped sanitized JSON/CSV/hash manifest, id-based post dedupe, immutable first-seen content, historical observations of counts, original source copy, status of incomplete carousels, field returned/null/absent/not_tested, like_missing_audit. Missing likes from a successful response remain an unresolved provider cause until controlled live test.
- **Locally verified:** Linux Python 3.13.5 20/20 synthetic unit tests PASS, py_compile collector/verify/tests PASS. Tested mocked batches/errors, missing/zero values, long IDs, Korean/unicode, repeat measurements, pagination catchup, safe quota stop, DB checksum/foreign keys, per-process lock.
- **Not verified:** real Meta token/permission/API field support, nested cursor across two real pages, independent quota, Windows PowerShell loop, GitHub Actions run status, actual missing-like root cause. No real API requests, image file downloads, Windows schedule activation or Vercel deploy.
- **Known limitations:** children extra pagination is logged partial, but not fully fetched. The 7-day range is a client-side grouping, not an assumed Meta since/until server filter. Real 1-year completeness cannot be asserted from the current data.
- **Next**: on user's Windows, pull main, offline tests, no-network dry run, check source and secure token paths, perform one approved max-batches=1 / batch-size=5 live pilot with quota headroom. Inspect field_support.csv, like_missing_audit.csv, raw JSON, manifest and verifier before increasing budget or starting user-opted 70-minute loop.

## 2026-10-18 — Planning-only long-term RAW/data asset vision (NO EXECUTION)

- User's current direction: official 294 accounts (KR100/US101/JP93), each **latest 50 posts as the initial target** (up to 14,700 if accessible), then maintain new posts while independently extending historical coverage to 1 year and ideally 2 years. This is an **aspirational target, not a collected result**.
- Future dashboard *concept*, not frozen screen specification: **tab 1** RAW explorer (period/sort/filter), **tab 2** weighted trend rankings, **tab 3** AI natural-language DB search/sort/tables/charts, **tab 4** collection coverage/attempt/success/failure/oldest-newest/status observability.
- Recommended separation under discussion: front refresh, older cursor backfill, engagement/account metric observation history; immutable per-run RAW JSON/CSV + cumulative SQLite, separate derived analysis/AI. RAW fields and source distinctions follow user-provided 2026-10-18 proposal where verified.
- **Saved design record only:** `docs/LONG_TERM_RAW_COLLECTION_VISION_2026-10-18.md`, linked from README. No implementation, unit tests, Meta live calls, scheduler activation, collection or data migration for this new plan. The document `OHORA_RAW_COLLECTION_EXECUTION(1).md` was supplied in chat and informed this discussion; it is *not* a separate executable approval. User explicitly asked to record the goals and pause for further discussion.
- Existing `experiments/rolling_backfill.py` stops at 50 and lacks continuing newest-post synchronization; its current behavior and existing collection stores **unchanged**. Existing app B credential expiry, 2-app independent budget, Graph cursor/API field support, completeness and image URL retention are **unresolved**.
- Next: listen to user's additional requirements; discuss architecture and approval boundaries first. **Do not start coding/API collection simply because this planning record is committed.**

## 2026-10-16 — Two-app five-post ninety-minute historical backfill coded

- Updated decision: **5 posts per account × 150 account app A + 144 account app B**, 90-minute recurring **historical cursor backfill**, goal **50 unique posts/account** in ideal 10 cycles, not repeated newest-five scans. 900 minutes ≈ 15 hours of cycle cadence; for ten start ticks there are nine 90-min gaps (13.5h between first and last starts). Two ~9h working days possible only if 150/144 accounts fully processed each tick, valid media cursors/permissions and quota recovery.
- **New GitHub code** `experiments/rolling_backfill.py` (append-only posts/media via unique IDs, read Graph `media.paging.cursors.after`, next page media.limit(5).after(cursor), stops at 50 or exhausted, blocks invalid/missing cursor, fair least-pages prioritization, per-batch usage logs, fixed A/B partitions, per-slot dedupe, 90m start/60m finish cooldown, 70% quota threshold, 30-minute max). Existing original collection experiments are NEVER modified.
- **New GitHub code** `experiments/run_90m_cycle.py` one-shot approved business-hour dispatcher, explicitly OFF by default, requires two distinct authorized Meta app IDs/tokens/local credential files and business-hour window; `experiments/backfill_schedule.example.json` kept disabled and `.gitignore` excludes local config.
- **New OFFLINE tests** `experiments/test_rolling_backfill.py` (10 cases) + `experiments/test_run_90m_cycle.py` (7 cases). User Windows run NOT YET DONE; do not claim passing tests until logs confirm. One-account two-cycle live pagination probe also NOT performed. Manual probe `--probe-ordinal 1` must be tested 90m apart in a NEW directory, separate from prior DBs.
- Hongju original token expired and caller Instagram ID unavailable; app B CANNOT be enabled yet. No n8n/Windows actual 90-minute schedule created or turned on. Real two-app rate quota independence remains unverified. Detailed instructions `experiments/README_CURSOR_BACKFILL_90M.md`.
- Previous Meta latest5+latest1+latest10 collection was reported **286 of 294 success, 8 Meta110 errors** in user screenshot; raw data in separate local SQLite. Those results are not yet merged into new history-backfill DB or delivery ZIP.


## 2026-10-16 — Slot2 151..294 prepared with read-only cross-source skip

- User has their own valid local Meta token/IG ID but Hongju's earlier token was confirmed expired. User proposes reusing their own token/IG ID temporarily in two logical slots, then replacing slot2 with Hongju credentials after renewal. **Two logical slots with one token are NOT two independent API budgets**; do not perform parallel runs or assume exactly 60-minute reset.
- Implemented repeatable `--skip-collected-from` read-only snapshot filters and combined it with `--only-pending-from` and existing `--start-ordinal 151 --end-ordinal 294 --assigned-app owner_slot2_probe`. Both prior 5-post + 1-post successful/partial statuses excluded; original 5-post failed statuses also excluded by pending-only gate; own destination DB already marks completed accounts and naturally resumes without re-request.
- From user reports, predicted 144 candidate ordinals in slot2, 30 already complete +1 Meta110 failed in original, 15 complete in supplemental, therefore **98 eligible**, starting at ordinal **197**; local dry-run is authority.
- `--posts 10` in brand-new `experiments/results/latest_10_owner_slot2_151_294/` DB; own original `$envFile` temporarily used. No credentials committed and no live Meta requests made by assistant. Model only updated GitHub source and tests. Dry run first, expected **22** total offline test cases; user Windows test pending.
- Small live pilot only AFTER Meta dashboard indicates sufficient recovery, `--batch-size 10 --max-batches 1 --stop-usage 70 --require-usage`; quota threshold evaluated AFTER request. If tested and approved, rerun sans max batches, stopping on actual rate limit. `--only-pending-from` and `--skip-collected-from` flags must remain on every invocation.
- Full instructions in `experiments/README_SLOT2_151_294.md`. Later Hongju auth must use separate credential file and output DB for provenance; 3-way delivery ZIP merging remains unimplemented.


## 2026-10-16 — Two authorized Meta apps manual 10-post collector implemented (Windows acceptance pending)

- New `experiments/two_app_runner.py` assigns original rows 1–150 to haein and 151–294 to hongju (current 294, 6 spare seats before 300), configurable `--capacity 150`, `--posts 10`, `--app NAME=ENV`, per-app input credential files and separate results. Does NOT implement scheduling or automated retries.
- `experiments/full_batch_collector.py` now accepts `--start-ordinal/--end-ordinal/--assigned-app/--require-usage`; account range and app label are locked into each database manifest; per-app quota headers must be present, stop-usage default 70% in outer runner (evaluated post-batch). Supports append-only future CSV growth while refusing reordering or mutation of earlier accounts. Maintains 294-row fixed official prefix.
- `--only-app hongju` / `--only-app haein` supports separate manual resumes when one app is paused, without crossing allocated ranges. Credential preflight rejects duplicate tokens, missing keys and duplicate declared app IDs; no token values logged. Declared app IDs are not proof of real Meta independent quota. Use only properly authorized apps/access.
- New `experiments/test_two_app_runner.py` adds 14 fully offline tests to existing collector's 19 and delivery merge's 15: **48 expected**. GitHub workflow `.github/workflows/offline-collector-tests.yml` created (run status not confirmed by connector). **Do not claim tests passed yet**; user's Windows run required.
- Full Windows PowerShell instructions in `experiments/README_TWO_APP_LATEST10.md`: update, tests, locally create Hongju env file, dry-run, app-by-app 10-account quota pilot, only then manually run pending 150/144 and create combined handoff ZIP with `delivery/build_hongju_bundle.py --supplement`. 5-minute completion and independent 2x quota are not guaranteed.
- Existing 5-post/1-post data stores untouched; no assistant-run Meta API calls and no app credentials accessed.


## 2026-10-16 — User proposes 10-post, 150/144 authorized two-app division

- User revised optimization hypothesis: each Business Discovery username is one Graph subrequest even if that request returns 10 posts; propose ~150 accounts per Meta app across **two separate, properly authorized apps** belonging to user and Hongju. Official file has 294 accounts, so use 150 + 144.
- Do NOT equate 10 Graph batch operations in one outer HTTP request with one rate-limit call: they count as 10 subrequests, with processing total_time/call_count tracked by app/token, and possible user scope limits. Do NOT assume two personal logins guarantee independent app quota or treat extra apps as a workaround for rate limiting.
- Still **unverified**: Meta 10-post total_time per account, Hongju app/token and permissions, app-level quota independence and 150/144 throughput. Need at most one small authorized 10×10 trial on recovered quota for each permitted independent app; protect at most 70% usage headroom, stop on code4.
- Status of Hongju ZIP helper: original standalone 9/9 tests passed on Windows. New dual-source merge code supports five-post **primary precedence on account overlap**, skips prior one-post row duplicates, preserves earlier one-post successful data if five-post retry failed, and records source/overlap counts; 15 offline tests added but **NOT YET rerun on user's Windows**. Read-only source files. GitHub changes committed, no real Meta request or local ZIP created by assistant.
- User now prioritizes idea over previous paired 10×5 test; do not auto-run any live test or change confirmed collection settings until the new design is validated.


## 2026-10-16 — 1-post 10-account comparison; five-post follow-up prepared

- User Windows pending-only batch 2 (original ordinals 187..196) succeeded **10/10**, response 1.859s, Meta app total_time moved **75% to 79%**, call_count=43%, resulting in 15/113 supplemental successes. Original 5-post database remains 176 successes/880 posts, original errors 5 (110), original pending 113. Combined coverage 191 unique accounts, 895 posts; 98 distinct official accounts remain uncollected.
- User now requests **one 10-account × 5-post** comparison against 10×1, and expects to schedule batches with rest windows later. This run must use the existing original 5-post output directory, one batch only (`--max-batches 1`, `--batch-size 10`, `--posts 5`), with current app usage ~79%. Its likely next account ordinals are 182..191. No assistant-side live Meta calls; the Windows user must run it.
- WARNING: 182..191 were already fetched by the one-post experiment. Merely concatenating original and supplement would duplicate accounts and posts. Handoff ZIP merge now **prefers five-post primary on whole-account overlaps**, keeps any nonoverlapping one-post accounts, validates account roster/IDs, and reports skipped/added counts. Source SQLite untouched. 15 offline delivery tests authored; user's Windows run pending.
- If all requested 10 original accounts succeed with five posts, expected combined data after merge: 5-post primary **186 accounts/930 posts**, supplemental net **5 accounts/5 posts**, combined **191 accounts/935 posts**. If failures occur, recompute using actual DB counts. Existing handoff ZIP remains its earlier immutable 175-account snapshot.
- Observed 10×1 app total_time change of +4 percentage points is NOT a controlled measurement of fixed cost. 10×5 may have a different rolling-window state. Cooling 50–60 minutes may not restore quota; confirm recent app usage before each separate run.


## 2026-10-16 — 1-post pending-only pilot tested on Windows

- User's Windows run: **20/20 offline tests passed** for pending-only batch collector.
- Live request on original pending account ordinals **182..186** (5 accounts) with `--posts 1 --batch-size 5 --max-batches 1` succeeded: **HTTP 200, success=5, failed=0, 5 posts / 7 media, 0.703s**.
- Meta response snapshot: `total_time=75.0%`, `call_count=41.0%`, `total_cputime=0.0%`. Previous dashboard 75.8%; lower snapshot does **not** imply zero or negative incremental API cost; rolling-window decay can offset additional requests.
- Current combined distinct account statuses across two isolated stores: old `latest_5`: 176 success, 5 failed code 110, original 113 pending; new restricted `latest_1_pending`: 5 success (all from those 113), **108 remain pending**. Overall 181 covered accounts/885 post records (880+5); no merged delivery ZIP yet.
- Next: controlled 10-account 1-post batch (original status allowlist+new own checkpoint) with `--max-batches 1 --stop-usage 85`; reassess time and call-count usage before larger run. Ensure old `latest_5` records remain untouched. `--stop-usage` evaluated AFTER batch, not a preventative API gate.


## 2026-10-16 — Pending-only latest1 Meta quota experiment prepared (user run pending)

- User's Meta dashboard displayed app total_time 75.8% and prior latest5 database contains **176 success, 5 failed (Meta 110), 113 pending**.
- New read-only source filter --only-pending-from added to experiments/full_batch_collector.py: selects original pending/rate_limited accounts only, while storing one-post results in **independent** experiments/results/latest_1_pending. Old 880 post rows remain intact; schema/official-list hash verified, mismatch refused.
- Added three offline unit tests for pending-only targeting, source mismatches and database path collision (19 tests expected; **Windows retest pending**). No live API request was made by assistant.
- Documented cautious **5-account pilot**, --posts 1 --batch-size 5 --max-batches 1 --stop-usage 85, in experiments/README_ONE_POST_PENDING_PROBE.md. Never auto-run remaining 113 until usage delta measured.
- Hypothetical threshold: starting 75.8%, all remaining 113 require <=0.214 percentage points/account before a 100% limit, assuming no quota recovery. Observed moving app-usage rates cannot identify fixed/per-post cost from a single pilot.


## 2026-10-16 — 294-account latest-5 collection stopped safely at usage 72%

- User Windows resumed `experiments/full_batch_collector.py --posts 5 --batch-size 10 --stop-usage 70` in `experiments/results/latest_5`. Last shown batch 19 (account ordinals 171..180) completed with HTTP 200 and usage **72%**; collector stopped per configured safety threshold.
- **Verified from shown console log:** 175 accounts `success`, 114 `pending`, 5 `failed` (individual Meta error `110` / HTTP 400); sum 294, zero `rate_limited` accounts shown. At most 875 successful-account posts, **actual total posts must be read from `summary.json`**. Existing successes saved transactionally; failed account statuses preserved.
- Meta code `110` commonly corresponds to invalid/not found target user ID on Business Discovery, but this is **not confirmed for these five accounts**; inspect `collection_status.csv` `error_message` and verify usernames/professional eligibility before considering any retry. The collector only resumes pending/rate_limited statuses; it does not auto-retry the 5 failed accounts.
- **Do not immediately restart at 72%.** Wait for documented usage headroom / rolling quota recovery. Keep `--stop-usage 70` and resume with same source/env/output once headroom is demonstrated. A 60-minute wall clock delay is not proof of quota reset.
- Friday deadline: while waiting, test delivery ZIP exporter (Windows SQLite closing fix pending user retest) and generate partial handoff ZIP from latest_5 with actual country/account coverage. If further collection becomes available before handoff, rebuild ZIP once final collection is done. Do not mistake 175/294 for complete official coverage.


## 2026-10-16 — Collector blocked by missing local Meta env; delivery test Windows lock fixed

- User confirmed official 294-account CSV path exists (`Test-Path $src=True`), but suggested local `kq3_294_collection/.env.local` does **not** exist (`False`). The collector therefore cannot authenticate without locating another secure env file or configuring `META_ACCESS_TOKEN`, `META_IG_USER_ID` and optional graph version locally.
- User ran Friday handoff test: `Ran 9 tests ... FAILED (errors=1)` on Windows with `PermissionError [WinError 32]` for the temporary `experiment.sqlite` file. Cause: `with sqlite3.connect(...)` is a transaction manager but not an explicit connection closer. Fixed **both** fixture and exporter with `contextlib.closing` in commits `5602e192adda3488f5ae16a4e2597c24815d2207` and `2b61b77b81ef03a304a454ba95c0b2557535f813`. Windows user retest pending.
- Urgent next action: find existing .env.local by **file path only** and run one guarded latest-5 batch, then resume remaining batches when safe. Do not paste API token. Delivery tests can be rerun before packaging after collection; no need to block Meta collector on unrelated ZIP test failure.
- No new Meta run was performed by assistant; real API collection must run on user's Windows PC.


## 2026-10-16 — P-1 Friday Hongju delivery prioritized over P1

- Deadline-driven priority: send analysis-ready Instagram collected data to Hongju during Friday classes before building incremental P1.
- Added delivery/build_hongju_bundle.py: **offline only**, read-only SQLite or CSV source, creates timestamped ZIP with both all available posts and most recent 5 per account, media, account coverage, dataset manifest and instructions. No source mutation, credential collection or image model call. Refuses empty datasets. Protects against spreadsheet formula injection in handoff copy.
- Added 9 offline tests in delivery/test_build_hongju_bundle.py (still **pending user Windows execution**), and delivery/README.md handoff runbook.
- Existing 294 latest-5 collection is not known to have succeeded (Meta code4 exhausted usage); preferred existing fallback legacy snapshot is ~94 covered accounts/1,880 posts, and another experimental snapshot ~77 covered accounts/1,540 posts. Exact current counts must come from manifest, not assumptions.
- Next user action after rest: git pull; run `python -m unittest discover -s delivery -p test_build_hongju_bundle.py -v`, select valid data source; generate ZIP; confirm coverage and deliver. If the Meta app actually recovered, optionally test one latest-5 batch before expanding; never let the full 294 goal prevent same-day partial handoff.
- P1 latest-refresh, P2 historical expansion and scheduled n8n remain unchanged in architecture but temporarily postponed until handoff.


## 2026-10-16 — P0 verified on user's Windows PC

- **User Windows offline suite:** `Ran 27 tests in 0.806s`, final `OK` (27/27 tests pass) after `git pull origin main`. In-test log messages including `provider_http_403`/`invalid_schema`/`Provider stopped safely` come from deliberately mocked adverse conditions, **not live model calls**.
- **Previously failed real image post:** User's earlier live exact-post rerun reported `attempted=1, success=1, failed=0` for `17994612878841451`, and local CSV row `status=success`, blank error code, model confidence 0.90.
- **P0 completed for functional/incident regression scope only:** one actual error recovered + offline suite all green; **not** proof of accuracy, high-volume reliability, or zero future failures. Do not pay to retry the already successful post.
- **Next P1:** durable append-only/UPSERT DB and recurring latest-5 collector; preserve original existing 20-post result set and make no live Meta calls without user approval and usage headroom checks.


## 2026-10-16 — Vision failed post recovered; one mocked test corrected

- **User-verified live recovery:** `--post-id 17994612878841451 --retry-failed --limit 1 --live` reported `attempted=1, success=1, failed=0`. The exported `post_analysis.csv` row for that exact post is now `status=success`, `error_code` empty, model confidence 0.90, visual summary about the 'Muffler II' gel collection display. This establishes technical recovery, not ground-truth image accuracy.
- **Windows test status:** prior 27-test suite yielded `FAILED (errors=1)` in `test_format_error_retried_once_and_cached`. Its final mock used an untargeted `--limit 1` run; the worker therefore correctly processed a *different* uncached post but received a `MagicMock` result, which `json.dumps` cannot serialize.
- **Fix:** `vision/test_vision_runner.py` now specifies `--post-id P1` for the final cache assertion and verifies that `analyze()` was never called. Production runner unchanged. Code committed as `170c8f3e6f0f7d11261c29f9addfbe684f375899`.
- **Next:** `git pull origin main` and `python -m unittest discover -s vision -p test_vision_runner.py -v`. Target: 27/27 tests OK. No further paid API retry is required for this recovered post; do not run the live retry again.


## 2026-10-16 — Target exact failed image post before proceeding to P1

- User correctly flagged that **one live `invalid_json` error remains unresolved**. A code patch for malformed JSON is not equivalent to successfully reclassifying the failed post.
- Discovered safety bug in prior CLI advice: `--retry-failed --limit 1` can bill an unrelated, newer *unanalyzed* post instead of the known failed post, because normal selection is newest-first.
- GitHub commits `2d72562296f7efe9578e5c5d5170582558fae86a`, `ceed2256e47874c1fab8aff6dbd36d2eac011ba0`: add `--post-id` to restrict all analysis to the exact post, and two mock regression tests for targeted recovery/unknown IDs. Expected offline suite **27 tests; user Windows execution pending**.
- **Recovery command AFTER offline suite passes:** `python .\\vision\\vision_runner.py --post-id 17994612878841451 --retry-failed --limit 1 --live` (uses local MLAPI key, may make up to two paid calls if malformed output persists). Do NOT claim the error is solved until the post row becomes `status=success` and is visually reviewed.
- Leave previous 20 cached successes untouched. Pause P1 until P0 user live retest verified.


## 2026-10-16 — V1 settings formally locked (design only)

- User confirmed **latest 5**, **backfill 5**, **50 unique posts/account target**, **max 30-minute collection session**, **>=60-minute cooldown after finish**, **>=90-minute gap between starts**, and **GPT-6.1 Sol API insights weekly**.
- Delivery roadmap: [docs/V1_DELIVERY_ROADMAP.md](docs/V1_DELIVERY_ROADMAP.md). Operating windows and Sol vendor API model/reasoning parameters are **not specified/verified yet**; no n8n scheduler or weekly AI job is active.
- Development: user + ChatGPT directly; Gemini 3.8 Flash API for image/caption tags; GPT-6.1 Sol separate paid API in n8n for cached weekly narrative interpretations, NOT the ChatGPT model or Codex. No Codex/Luna EH.
- Current phase: offline 25-test vision retest + single malformed-output retry validation, then durable post-ID-based upsert/latest refresh, backfill and analysis queue, DB-only dashboard, weekly Sol and n8n schedule. Existing initial 5-post collector alone **cannot** repeatedly refresh without replacing or skipping successful account data.


## 2026-10-16 — vision JSON safety improvements (Windows + live retest pending)

- Observed user live paid MLAPI vision results: 21 post attempts, 20 success and 1 `invalid_json` (post ID stored locally); image-and-caption model service works, but output reliability needs improvement. This is a small sample, not a measured production failure rate.
- Code commit `d4de3e4f6d7abbb53c94b1dde20ec71771365641`: recover a SINGLE complete JSON object when prose surrounds it; never fabricate truncated JSON. Detect model finish_reason length; allow exactly ONE extra model call on limited schema/format errors with larger max_tokens; no auto retry on 401/403/429 or transport faults; preserve cached successes and failed rows.
- Test commit `d253ee456b9079cf37d85804f5072f65b306afa6`: 4 new offline tests for wrapped/duplicate/truncated JSON and bounded retry, and updated old two-invalid-output expectations. **25 total tests must be rerun on user's Windows PC; not yet verified after the new patch.**
- Next user actions: `git pull origin main`, `python -m unittest discover -s vision -p test_vision_runner.py -v`, then one explicit real retry: `python .\vision\vision_runner.py --retry-failed --limit 1 --live`. Only if those pass consider larger analysis in batches.
- Demo safeguard: PRECOMPUTE and store all classification before presentation; dashboard should only read cached success rows, disclose coverage/failures and operate without model/API availability. **Actual dashboard interface remains unimplemented**.


## 2026-10-16 — Image+caption vision pipeline ready for local provider validation

**Code added:**
- `vision/vision_runner.py`: read-only import from full_294/latest_5 SQLite or original posts/media CSV; select representative image/carousel/video thumbnail plus caption; schema-validated `is_design_post` and color/technique/texture/motif/season/use labels; one SQLite transaction per post; CSV exports and caching; manual provider switch; safe stop on auth/rate/format errors; explicit paid `--live` only.
- `vision/test_vision_runner.py`: **21/21 offline tests passed** in the development environment. No external provider requests.
- `vision/setup_env.ps1` prompts for endpoint/model/key and writes *only local* gitignored `vision/.env.local`. The actual user-supplied API key is **not** in GitHub, Library or outputs.
- `vision/README.md`: PowerShell morning runbook; run one paid API call only after user reviews provider setup.
- Real legacy source dataset **1,880 posts / 5,307 media records** was parsed offline; mocked model integration processed three posts, exported analysis rows, and SHA-256 of original CSVs was unchanged.
- External `mlapi.run` endpoint authorization, accepted model ID, remote image URL fetch behavior, *actual AI inference quality*, cost, and Windows user run are **not yet validated**. Do not call this completely done.
- Already observed: user's Windows original 16/16 collector tests passed after SQLite closing fix. First live latest-5 Meta test hit code 4 due to lingering 101% usage; no successful new posts from that test.
- Next: user pulls GitHub code, runs vision tests locally, configures fresh API key securely, offline preview from `experiments/results/full_294`, then one small `--live --limit 1` check before any bulk analyses. Collector runs only after Meta usage sufficiently recovers.
- 90-minute n8n scheduling, recurring latest upserts and cursor backfill, dashboard UI remain *separate future work*.


## Windows test fix — 2026-10-16

- User's Windows Python 3.11 run of `test_full_batch_collector.py` reported 16 tests, 2 errors: WinError 32 when `TemporaryDirectory` tried to unlink `collection.sqlite`.
- Root cause in tests: `with sqlite3.connect(...)` commits/rolls back but does **not** close the SQLite connection. Two occurrences replaced by `with contextlib.closing(sqlite3.connect(...))` in GitHub commit `dd375a18bb9b0cdb8354e98ba88cc0b97dab60de`.
- GitHub file content verified after patch; **user's subsequent Windows retest passed 16/16** (observed 2026-10-16 chat log).
- User's `--posts 5` dry run succeeded: 294 accounts, 10 per batch, 30 batches; no API requests or file writes.
- Next: `git pull origin main`; `python -m unittest discover -s experiments -p test_full_batch_collector.py -v`; only proceed to live 5-post acquisition if tests pass and Meta app usage has recovered.


## 2026-10-16 — latest-five acquisition preparation

- **Decision:** Build latest 5 initial acquisition now; postpone hourly-window scheduling, recurring post-ID upsert, older-page backfill, and vision until staged verification. Plan: `docs/INCREMENTAL_V1_ARCHITECTURE.md`.
- **Implemented:** `experiments/full_batch_collector.py` now supports `--posts 1..20`; 20 remains the default. `--posts 5` MUST use `--output-dir experiments/results/latest_5` or another empty isolated output path. Original 20-post database and old collector remain untouched. Resume skips completed accounts; no periodic refresh implemented yet.
- **Verified offline:** 16/16 tests, including 5-post mocked live batch and changed-manifest rejection; actual official 294-row source accepted with dry-run 5 posts/10 accounts x 30 batches, no writes/no calls. This is **not** a live five-post API validation.
- **Observed live prior:** user reported real 20-post full-list run hit HTTP 403 / Meta code 4 at batch 9 with 77 successful accounts (13 failed; 204 unattempted). Do not assume a fixed 60-minute cooldown resets quota; confirm recovery and run a small staged batch before large collection.
- **Next:** after app usage safely recovers, user runs `git pull` and offline test then the 5-post dry run and optionally one explicit live batch for confirmation. Reusable latest-refresh/backfill must be implemented later on a non-destructive upsert schema, followed by image analysis endpoint testing.



Updated: 2026-10-15 KST

## Business scope
- KQ3 is *Key Question 3*, not calendar quarter Q3.
- Official account list: 294 targets, KR 100 / US 101 / JP 93.
- Goal: preserve latest 20 posts/account (up to 5,880) and child media, followed by separate vision classification and DB-backed dashboard queries.

## Confirmed collection history
- Existing original sequential collector succeeded for 94 accounts (1,880 posts, 5,307 media rows) in the previously inspected snapshot, with Meta usage/limit issues. Original raw datasets remain on the user's PC; they are **not** committed.
- User-operated Meta Graph Batch probe: one target in 1.265s; two targets in 2.063s; five targets x10 posts in 2.703s; same five x20 in 5.797s; ten targets x10 in 2.828s. All tested subrequests returned HTTP 200. Usage header percentage readings are **snapshots** and not per-call costs.
- No 294-account live batch collection has been executed or verified yet.

## Code
- `kq3_294_collection/collector.py`: original legacy collector, unchanged.
- `experiments/meta_batch_probe.py`: original stat-only single-batch probe, unchanged.
- `experiments/full_batch_collector.py`: isolated full 294-target batch collector (10/account batch, 20 latest posts/account), SQLite transactions + CSV exports, no automatic retries, recorded usage/errors, resume after interruption and stop upon Meta rate/auth errors. Dry run is default; **only --live sends API requests**.
- `experiments/test_full_batch_collector.py`: 15 network-free unit/integration tests passed during development.
- `experiments/FULL_294_README.md`: exact PowerShell instructions, operational limits, file map, and exit codes.
- A separate fully mocked 294-target run verified 30 batches ending with four accounts, 5,880 unique posts and 8,820 media rows (fabricated fixtures, not real Meta records).

## Decisions / non-goals
- Full experiment intentionally starts at the beginning of the official list, including 94 previously collected accounts, but saves under `experiments/results/full_294/`; **never overwrite legacy CSV data**.
- Default run has no speculative 80% cutoff because the user wants to observe the actual Meta limit. First recognized limit/auth error stops future batches after preserving the successful subresponses. Optional `--stop-usage 80` is available.
- URLs and metadata are stored; image binaries, AI vision tags, n8n automation of this new collector, and frontend/DB dashboard integration are outside this experiment.
- Any runtime incident or errors should be diagnosed from `summary.json`, `batch_log.csv`, and `collection_status.csv`; avoid rerunning same method blindly. Never share real access tokens.

## Next step
User: `git pull origin main`, run the full collector dry run then its explicit `--live` command locally, and share sanitized logs / summary. Assistant: review quota progression and exact stop point, decide whether to retain 10-subrequest batches or optimize further based on real 294-run evidence.
