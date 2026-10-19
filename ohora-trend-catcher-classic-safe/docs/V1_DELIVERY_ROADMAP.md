# OHORA Trend Catcher — V1 확정 설정 및 구현 순서

**결정:** 2026-10-16 사용자와 확정. **설계 기준이며 자동 실행이 활성화되었다는 뜻이 아님.** 실험/기존 수집 데이터 덮어쓰기 금지.

## P-1 — 2026-10-16 금요일 홍주님 데이터 전달 (긴급 선행 작업)

**P1보다 먼저 실행.** 오늘 학원 종료 전 홍주님에게 분석 가능한 원본/최신 5개/미디어/계정별 커버리지 ZIP을 전달한다. 도구: [delivery/README.md](../delivery/README.md), `delivery/build_hongju_bundle.py`, 오프라인 9개 테스트. 실제 Meta code4 잔여 사용량 제한으로 **294계정 최신5 수집 완료를 보장하지 않음**. 완료 불가능하면 기존 94성공계정·1,880게시물 자료를 부분 수집으로 명시하고 우선 전달한다. ZIP 생성 스크립트와 단위 테스트는 코드 반영됐지만 사용자 PC 검증/ZIP 생성은 아직이다.

## 2026-10-16 — NEW confirmed target: 2 apps × 150/144 × 5 posts × 90-minute backfill

**Latest user decision supersedes the earlier 10-post ×150 hypothesis above.** Set account-page depth **5**, split official accounts **A 1..150, B 151..294**, target **50 distinct historical posts** per account, **90-minute cycle** (not every 60 minutes). Ten *successful distinct* pages yield 50; ordinary repeated newest-five calls DO NOT. In ideal fully successful cycles the user expects ten cycles across ~two working days; rate limits, missing cursors or scarce account media may extend this.

**Implementation now committed but not Windows-verified nor running:** `experiments/rolling_backfill.py` (media.after cursor, append-only SQLite, one page/account/cycle, >50 target stop, fair priority, 70%-usage guard and 90m/60m cooldown); `experiments/run_90m_cycle.py` (one-shot A/B dispatch, explicit KST business-hour approval, real distinct appID/token validation, disabled by default); 10+7 synthetic offline tests; `experiments/backfill_schedule.example.json`; full guide `experiments/README_CURSOR_BACKFILL_90M.md`. GitHub-only code changes; **no live Meta calls, actual scheduling, or Hongju credential updates have occurred**. The previous expired Hongju token is still a blocker, as is two-page Graph pagination live verification.

Backfill output is kept distinct from existing `latest_5` (176 successes), `latest_1_pending` (15 successes), and `latest_10_owner_slot2_151_294` (95 successes) source DBs. A separately tested import/merge is required for aggregate coverage. Business Discovery may not return suitable paging cursors for every professional account; no automatic 50-post completion claim.
## 2026-10-16 — 10게시물 × 약150계정 × 2개 Meta 앱 구상 (검증 전)

**사용자 제안(운영 방향):** Meta Business Discovery에서 계정당 하나의 subrequest에 media.limit(10)을 넣고, 약 294개 공식 계정을 사용자 Meta 앱(150) + 홍주님 Meta 앱(144)으로 나눠 정기 수집. 같은 게시물을 매번 20개 가져오는 것보다 10개 스냅샷과 포스트 ID upsert가 적절할 수 있다. **운영 값 변경은 정식 계측/홍주님 앱 접근 권한 확인 후 확정.** 기존 확정 V1 최신5 및 백필5 설정을 검증 없이 강제 덮어쓰지 않음.

- Batch outer HTTP 한 번에 10계정 조회를 실어도 Meta 제한 계산상 내부 Business Discovery 10개 subrequest는 개별 호출로 집계된다. 즉 150계정 ≈150 조회(subrequests), 15 outer Batch HTTP 요청이다.
- 사용량이 계정당 기본 처리 비용 위주라는 정황은 있지만, 10게시물일 때 총시간이 5게시물과 같다는 증거는 없음. 1개/5개 교차 실험에서 이동창 효과가 혼합됨. 첫 번째 앱의 실측은 5개×180계정 요청 무렵 total_time 72%, 1개×10계정 요청 시 75→79%였음. 오늘 10개 대량 수집을 무검증 실행하지 않음.
- 다른 Meta **개인 로그인**만으로 두 개 독립 사용량이 보장되지 않음. 승인된 별도 앱 ID, 각각의 유효한 토큰과 Instagram professional source·연결 Facebook Page·필요 권한을 확인해야 함. 동일 개인 토큰/공유 사업체나 사용자 수준 quota 가능성 확인. 새 앱을 단지 Meta 사용량 제한 우회 목적으로 복제·운용해서는 안 됨.
- 운영 제안: Meta app A 계정1..150, app B 계정151..294, each distinct independent DB and no overlapping account range; nightly/weekly cadence and target depth configurable. 각각 별도 호출 로그, 실패 로그, x-app-usage 및 정상 권한 검증. 마지막에 account_key/post_id/media_id 기준 병합, NULL likes 보존.
- 구현 전 acceptance: 계정당 10개, Batch 10계정 소규모 실측, 앱별 usage/call_count/total_time 비교, Meta Business Discovery 접근 가능여부 및 권한 확인, 150/144 분할/중복금지 단위 테스트, 자격증명 분리 보관, 장애 시 그 앱만 중단하고 성공 데이터를 보존.
- 현재 전달 마감 우선과 과거 latest5 176계정/880개, latest1 15계정/15개 + 회복 대기 98계정은 별도 관리. 2앱 체계 검증 전 기존 수집기는 안전 가드 유지.
## 1. 확정한 운영 설정

```yaml
timezone: Asia/Seoul
schedule_enabled: false           # 실제 가동 시간과 사용량 검증 후 활성화
operating_windows: []             # 사용자 미지정; 구현 때 별도 확정
official_accounts: 294           # KR 100 / US 101 / JP 93
latest_per_account: 5
backfill_per_account: 5
backfill_depth_target: 50        # 고유 게시물 수; 삭제·보관 상한이 아님
max_collection_run_minutes: 30
min_cooldown_after_finish_minutes: 60
min_interval_between_starts_minutes: 90
insights_cadence: weekly         # GPT-6.1 Sol 별도 유료 API
insights_live_on_dashboard: false
meta_batch_accounts: 10         # 현재 검증된 배치당 계정 수, 추후 재측정 가능
```

- 공식 294계정이 모두 50건에 도달하면 **최대 14,700개 고유 게시물**을 확보한다. 이는 보장이 아닌 목표치다.
- 백필은 계정당 고유 50건을 확보하면 종료. 정기 최신 수집에서 새 게시물이 나오면 50건을 넘더라도 이력은 보존한다.
- 5개→4/3/2개 축소는 요청 데이터 형식/용량 관련 오류 또는 명시적 설정을 위한 것. **Meta 오류 4의 앱 단위 quota 우회로 간주하지 않는다.**
- 스케줄 조건: 가동 시간에 속하고 실행에 필요한 잔여 시간이 있으며, 수집 프로세스가 0개이고, `now >= max(previous_started + 90 min, previous_finished + 60 min)`. Meta 사용량 회복 근거가 부족하면 실행하지 않는다. **1시간 후 사용량 완전 초기화를 전제하지 않는다.**
- 수집 요청은 30분 만료 시 체크포인트에 저장하고 종료. 배치 중단점에서 일관되게 재개한다. 인증·quota 오류는 자동 무한 재시도하지 않는다.
- 이미지 분류는 Gemini 3.8 Flash OpenAI 호환 게이트웨이. 주간 텍스트 추론은 **별도 GPT-6.1 Sol API** (추론 3단계 설정은 제공자에서 실제 확인 후 적용). ChatGPT 대화 모델로 호출하는 뜻이 아니다.
- 개발: 사용자 + ChatGPT 직접. Codex나 Luna Extra High를 개발 워크플로에서 사용하지 않는다.

## 2. 목표 아키텍처

```text
n8n Scheduler + Guard (운영 시간/90분/쿨다운/사용량)
    ├─ 최신 5개 / 294계정 ──┐
    └─ 과거 5개 / 계정별 ──┤
                           ▼
                     Raw DB (upsert)
            account | post | media | account_state
                           ▼
                    New/Changed queue
                           ▼
                Gemini 3.8 Flash image+caption
                 validate → 1 format retry → log
                           ▼
           design_tags + analysis_runs + failure_queue
                           ▼
          SQL deterministic aggregates + data coverage
             ├── Dashboard (DB read only)
             └── Weekly Sol API (bounded aggregated input)
                      ▼
               Cached weekly insight report
                      ▼
                 Dashboard shows cached report
```

**Never** call Meta, Gemini or Sol to render dashboard filters, refresh or charts. DB aggregation may be updated after new data commits.

## 3. 다음 개발 단계 및 완료 기준

### P0 — 바로 실행: Gemini JSON 안정화 확인

- 현재 사용자 검증 실측: 21건 시도 중 20건 성공, 1건 `invalid_json`.
- JSON 추출 및 1회 한정 포맷 오류 재요청 패치가 GitHub에 반영되어 있음. **사용자 PC 최신 25개 오프라인 테스트 및 재시도 1건 라이브 검증은 아직 필요**.
- 검증 명령: `git pull origin main`, `python -m unittest discover -s vision -p test_vision_runner.py -v`, 이후 사용자 승인으로 `python vision/vision_runner.py --retry-failed --limit 1 --live`.
- 합격: 25개 오프라인 테스트 OK, 성공 20건 캐시 그대로, 형식 오류 재시도 최대 1회, 실패별 원인·상태 남김.

### P1 — 누적형 원본 DB 및 최신 5개 갱신기

- 기존 20개 및 첫 5개 실험 결과는 원본 보존. **별도 통합 DB** 생성과 안전한 읽기 전용 이관 절차 작성.
- 엔티티: `accounts`, `posts`, `media`, `account_state`, `collection_runs`, `batch_logs`, `design_analysis`, `failed_jobs`. `post_id`/ `media_id` 고유 키, 실측·결측 구분.
- 기존 초기 collector는 성공 계정을 skip하며 최신 5개 재조회 시 delete-and-replace 하므로 **운영 누적 DB에 그대로 재사용하면 안 됨**. 새 upsert 갱신기 필요.
- 최신 5개 조회 시 `last_seen_post_id` 기준 중복 제거; 새 5개보다 게시물이 더 많이 올라온 경우 경계 도달할 때까지 제한적 추가 페이지 조회. 못 채우면 coverage gap 표시.
- 완료 기준: 같은 계정 2회 수집, 새 게시물 2개 유입, 필드 결측, 캐러셀 미디어 변경, 강제 중단/재개 테스트에서 기존 이력이 사라지지 않음.

### P2 — 계정별 과거 5개 백필

- Business Discovery `media.paging`의 실제 다음 5개 커서를 **별도 소규모 실호출**로 먼저 검증하고 과거 커서·앵커 저장.
- 1회당 계정별 5개씩 고유 중복 제거, 이미 50개 이상인 계정은 백필 중지, 이전에 수집한 원본 데이터는 절대 삭제 금지.
- 무효 커서는 계정별 post-ID 앵커 재탐색으로 복구 시도하되 상한을 둔다.
- 완료 기준: 한 계정을 5→10→15개로 확장, 같은 작업 재실행 시 고유 게시물 수 불변, 재개 후 50건 도달 시 추가 백필 없음.

### P3 — Gemini 비동기 분석 작업 큐

- 새로운/갱신된 post만 작업 큐로 이동. 이미 성공한 `post_id + model + prompt_version + input_fingerprint`는 재분석 안 함.
- 캐러셀 자식 이미지 대표 1~3개, 비디오 썸네일만 사용하며 한계 명시. 태그: `is_design_post, color, technique, texture, motif, season, use`.
- JSON 검증, 실패 유형, 요청 시각, 안전한 오류 메타데이터, 시도 횟수, 재시도 가능 시각 저장. 인증·quota는 중지/대기, 반복 오류에 무한 재시도 없음.
- 완료 기준: 100개 모의 데이터에서 1개 실패해도 99개 결과 보존; 재실행 시 성공 건 API 0회; 실패 건만 별도 재처리 가능. 실제 품질은 원본 이미지 샘플과 수작업 비교 필수.

### P4 — SQL 통계와 발표용 기본 대시보드

- 선택 기간·KR/US/JP·디자인 태그 별 게시물, 참여도 순위, 변화 추이, 디자인 조합 TOP5를 DB에서 집계.
- `like_count = NULL`은 0으로 대체하지 않음. 팔로워 수는 수집 시점 기준이며 게시 시점 팔로워로 오인시키지 않음.
- 샘플 분모, 계정 커버리지, 기간 공백, 분석 성공/실패/미실행을 표시. 최신 5개만 있다고 그 기간 전체 트렌드를 대표한다고 주장하지 않음.
- 완료 기준: 인터넷이나 두 AI가 꺼진 상태에서도 같은 조건의 대시보드/필터/차트/CSV가 재현됨.

### P5 — GPT-6.1 Sol API 주간 고급 인사이트

- 매주 1회, **SQL의 집계 숫자와 근거 게시물 ID/URL/표본 수만** 선별해 GPT-6.1 Sol API에 전달. 원본 이미지 전체를 중복 전송할 필요 없음.
- 실제 모델 ID, reasoning 3단계 설정, 요금·응답 JSON 스키마는 MLAPI 또는 제공업체에서 실측 확인 후 n8n 인증 변수에 설정. **추측한 API 파라미터로 구현 완료 선언 금지**.
- Sol은 숫자·순위·참여율을 만들어 내지 않고 해석과 가설·상품기획 제안만 생성. `observed_fact`, `interpretation`, `hypothesis`, `limitations`, `source_post_ids`를 분리.
- 주간 결과 `week+country+source_data_version+model_version`별 캐시. 실패 시 이전 보고서 또는 '이번 주 생성 실패' 표기하고 대시보드 정상 동작.
- 완료 기준: 주간 1회 실행/동일 입력 재실행 캐시 확인, Sol 비가용 시 기존 차트·리포트로 발표 가능.

### P6 — n8n 90분 스케줄 + 통합 장애 복구

- n8n Schedule Trigger는 주기적 확인을 수행하고 DB 가드가 **실제 실행 가능 여부**를 판단. Windows 개인 노트북이 꺼지거나 n8n 서버가 로컬 파일을 읽을 수 없는 배치 환경이면 실행되지 않으므로 배포/DB 접속 경로를 먼저 검증해야 함.
- 최신 우선 수집, 여유 있으면 과거 백필, 신규 분석 큐, 주간 Sol 리포트를 분리. 최신 수집을 위해 반드시 지난 백필 전체를 완료할 필요는 없음.
- 경고·로그: 작업 ID, 계정/게시물 ID, 오류 종류, 사용량 관측, 재시도 가능 시점, 처리 상태만 저장. 비밀 키/원본 응답/서명 이미지 URL 저장 금지.
- 사용자 미지정 `operating_windows`는 실제 스케줄 활성화 전에 별도 확정.
- 완료 기준: 2회 연속 중복 스케줄 경합 없이 차단, 30분 상한 준수, 최소 90분 시작 간격/종료 후 60분 휴식 준수, Meta code4 및 모델 429에서 안전 중단/다음 기회 재개.

## 4. 현재까지 검증한 것 / 아직 미구현

- **실증:** Meta 20개×10계정 배치는 빠르지만 9번째 배치에서 앱 쿼터 초과; 기존 77성공/20포스트 실험은 로컬 보존. Gemini 게이트웨이는 20건 실제 성공, 1건 invalid_json. 이미지 분석 초기 21개 오프라인 테스트 이전에 통과.
- **이미 있음:** `experiments/full_batch_collector.py`의 초기 5개 전수 수집기와 체크포인트; `vision/vision_runner.py`의 CSV/SQLite 로드, 단독 JSON 분류, 캐시/저장.
- **아직:** 지속형 수집 upsert, nested pagination 검증, 주간 Sol 연결, 정식 SQL 대시보드, n8n 스케줄, 비용·속도 측정, 실제 25개 업데이트 테스트.

## 5. 우선순위 판단

**P0 → P1 → P2 → P3 → P4 → P5 → P6**를 기본 순서로 진행. 단, 내일 전수 5개 데이터 확보는 별도 준비된 collector로 사용자 PC에서 먼저 수행 가능하고, API 사용량 회복이 확인될 때에만 실제 호출. 목표가 발표 시연이면 **P4 DB-only 대시보드**를 최소 동작으로 먼저 확보하고 AI 주간 보고서/스케줄을 뒤에 붙여 위험을 줄인다.
