# OHORA Trend Catcher — RAW v2.1 전체 트러블슈팅 기록과 검증된 운영 현황
> 기준일: **2026-10-19 KST** · 대상 저장소: `hibi89/ohora-trend-catcher` · 운영 DB는 **사용자 Windows 로컬**에 있으며 GitHub에는 올리지 않는다.
>
> **이 문서의 성격:** 사용자 PowerShell 출력, 원본 Meta 오류 응답, 기존 저장소의 설계·검수 문서를 대조해 정리한 사고/해결 기록이다. 이 문서를 읽는 후속 AI/팀원은 **검증된 사실**, **당시 가설/실험**, **아직 미검증**을 혼동하지 말 것. 아래 기록은 이전 날짜의 `STATUS.md`·`HANDOFF.md`의 계획 수치보다 우선한다.

## 0. 처음 읽을 결론과 위험 경계

- **최근 사용자 실행 결과(직접 제공된 PowerShell 로그):** 공식 계정 **294**(KR 100 / US 101 / JP 93), 성공 계정 **286**, Meta 오류로 차단된 계정 **8**, 누적 고유 게시물 **1,330**, 게시물 관측 **1,350**, 미해결 API 배치 **0**. 마지막 `raw_v2/audit.py` 출력은 **PASS / integrity 0 / observation 0 / coverage 0 / exit 0**.
- 직전 감사의 `ready_for_unattended_collection: false`는 그대로다. **무인 장기 실행·1년치 전량 수집·인스타그램 전체 게시물 완전성은 승인/증명되지 않았다.** `coverage=0`은 감사기가 검사하는 기록·근거 관계에 경고가 없다는 의미이지 모든 계정의 과거 365일 데이터를 확보했다는 주장이 아니다.
- 마지막 **수동 지정 10계정 History 실수집**: 10/10 HTTP 200, 계정당 반환 4·신규 4, **40개 신규 게시물**, 1,290→1,330. 이후 `UNVERIFIED_LEGACY_COMPLETION` 관련 coverage 경고 **10→0**. 이것은 **선별된 10건의 근거 연결 문제 해결**이 중심이다.
- 8계정 `blocked=1`, `last_error='110'`. **JP_093**의 저장된 Meta 원본에 `"Invalid user id"`, subcode `2207013`, `is_transient:false`, “사용자 이름이 mio__nail_31인 사용자를 찾을 수 없습니다.”가 확인되었다. 사용자 브라우저에서 같은 URL이 “페이지를 사용할 수 없습니다”로 나타났다. **계정 삭제/변경/비공개/비활성화의 정확한 원인까지 판정한 것은 아니다.** 나머지 7개의 세부 `error_subcode`와 메시지는 이 정리에 제공되지 않아 같은 사유로 단정하지 않는다.
- 저장소 커밋 당시 API를 모델이 직접 호출한 것이 아니다. **실수집과 최신 감사는 사용자가 로컬 PC에서 실행했고 출력으로 확인**했다. GitHub 코드 수정/오프라인 테스트와 로컬의 운영 상태를 분리한다.
- **운영 불변식:** 실 DB·run 원본 JSON·기존 커서·관측 이력·`slots.ready_at`·공식 294개 목록을 임의 변경/삭제/초기화하지 않는다. 인증 파일·토큰을 GitHub/로그/채팅에 출력하지 않는다. 실호출은 사용자 명시 승인과 `--live`가 필요하며 자동 예약 작업은 없다.

## 1. 데이터와 기술 구조 — 현재 기준

| 구분 | 실제 운영 개념 |
|---|---|
| 고정 공식 소스 | 학원 제공 `account_list.csv` 294행, KR100/US101/JP93 순서; 원본 해시·계정 키·순서 유지 |
| 인증 | 별도 로컬 `.env.local`; `META_ACCESS_TOKEN`, `META_IG_USER_ID`, 선택 `META_GRAPH_VERSION`(기본 v26.0). GitHub 비포함 |
| API | Meta Graph **Business Discovery** batch; 하위요청 5개/배치, 계정당 media 최대 4개/요청(현행 프로필) |
| 주요 진입점 | `raw_v2/daily_scheduler.py`(일일 작업 정책) → `raw_v2/collector.py`(Meta 요청·원본·SQLite 영속화) |
| 단계 | `front` 오늘 최신 페이지 → `catchup` 최신화 사이 누락 페이지 → `history` 저장된 `backfill_cursor`로 과거 방향 |
| DB | `%LOCALAPPDATA%\OHORA_RAW_v2\collection.sqlite`; WAL, account/post/post_observations/history 증거/요청 로그/슬롯/일일상태 |
| 불변 증거 | `%LOCALAPPDATA%\OHORA_RAW_v2\runs\<run_id>\raw\`의 개별/배치별 정제 JSON, 각 run의 CSV, `run_manifest.json`, 해시 |
| 정책 | 슬롯당 서로 다른 계정 최대 150; `X-App-Usage` 유효 지표의 최댓값 85% 도달 시 후속 중지; 사용량 근거가 없으면 중단 |
| 대기 | `max(슬롯 종료+63분, 슬롯 시작+65분, 기존 ready_at)`; 단 **시간 경과 ≠ Meta API 사용량 회복 보장** |
| 완료 판정 | `backfill_done` 단독 불가. 최초 NULL 커서 root부터 커서 연결, 날짜 순서, cutoff/종료, 실제 JSON·request 로그·현재 checkpoint 함께 확인 |

아래 명령은 **PowerShell 저장소 루트** 기준. 실제 소스 경로·비밀파일 경로는 개인 장비에서 확인해야 하며 문서에 토큰 값을 기록하지 않는다.

```powershell
$src = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브\2차 프로젝트 데이터\account_list.csv'
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
# 인증파일 내용 출력 금지. 경로는 각자의 로컬 장비 설정에 맞춘다.
python .\tests\run_offline.py
python .\raw_v2\audit.py --output-dir $out
python .\raw_v2\recover.py --output-dir $out
python .\raw_v2\daily_scheduler.py --source $src --output-dir $out --policy daily
```

## 2. 일련의 문제 해결 타임라인 — 사실과 당시 가설 구분

### 2.1 초기 실수집과 API 제한량 판단 (10/15~10/18)

1. **초기 고민:** 294계정에서 계정당 20~50개를 단번에 가져오면 요청량과 배치 사용량 문제가 커짐. 초기 n8n Meta Batch API 시험에서는 빠르게 처리되었으나 시간 기반 제한에 걸렸음. **속도 빠름 ≠ 더 많은 API 쿼터**.
2. **설계 변경:** 계정당 최신 5건 → 4건으로 축소하고, 한 슬롯당 서로 다른 계정 최대 150, 최대 5개 하위요청/배치로 분할. 최초 최신 데이터 확보와 365일 이력 추적을 별도 cursor 경로로 분리. 2개 앱 계획은 제안/실험이었으나 **같은 토큰을 두 논리 슬롯에 넣는 것은 서로 다른 쿼터가 아님**. 두 인증 계정/앱의 독립 사용량은 검증되지 않음.
3. **실제 5계정 첫 시험:** 사용자 기록 `20261018T143306Z_2840`에서 KR_001~KR_005 5/5 성공, 신규 25개, SHA/DB 검증 PASS. 여기서 25개 중 **6개 `like_count` 미반환**, 전부 VIDEO/REELS로 관측. **조회 실패/좋아요 0이 아니라 필드 부재**로 저장. Meta 반환 조건의 정확한 원인은 미확정.
4. **쿨타임 해석 수정:** “150계정을 처리한 뒤 쉬는 것”과 “5계정 파일럿을 했다”는 다른 상황. 구버전의 70분/60분 설명이 혼재했으므로, 슬롯 상태와 부분 이어하기, `ready_at` 영속화로 수정. 현재 최종 운영 규칙은 위 **63/65분의 max**이며 과거 문서의 60분·70분을 재사용하지 않는다.
5. **진행 수치:** 중간 운영에서 630개 고유 게시물, 이후 초기 검수 시점 1,178개 등이 기록되어 있다. **서로 다른 시점의 스냅샷**이므로 단일 실행 결과나 완전 수집량으로 합산하지 않는다. 마지막 감사의 1,330/1,350을 최신 운영 수치로 따른다.

### 2.2 Windows/경로/인증 혼동

- 새 채팅방·새 터미널에서 GitHub `main` 복원과 Windows 오프라인 테스트가 PASS여도, **로컬 Meta 인증 파일은 Git에 포함되지 않아 자동 복원되지 않는다**. `--env-file`을 실제 존재하는 로컬 파일로 지정해야 한다.
- 파일 내 키는 `META_ACCESS_TOKEN`, `META_IG_USER_ID`(숫자형), 선택 `META_GRAPH_VERSION`; **토큰 본문을 출력/커밋/붙여넣지 않는다**.
- `--source`는 학원 공식 294계정 CSV. `--output-dir`은 원래 수집 DB가 있는 `$env:LOCALAPPDATA\OHORA_RAW_v2`. **다른 디렉터리를 지정하면 새 DB로 오인·분리될 수 있다.** OneDrive 프로젝트 소스와 실행 결과 DB의 경로는 별개.
- PowerShell `$src`, `$out`, `$envFile`, `$env:PYTHONPATH`는 **새 세션에서 유지된다고 가정하지 않는다**. `Test-Path`, `Resolve-Path`로 값 확인.
- 인증 실패는 파일 경로 누락과 Meta 인증/권한 만료를 분리해서 진단한다. GitHub에 인증파일이 없는 것은 정상 보안 상태다.

### 2.3 최신화/History/커서 연결의 복잡한 결함

- `front`는 최신 게시물 페이지, `history`는 과거 `backfill_cursor`, `catchup`은 최신화 중 빠진 간격의 커서를 사용. **front 재조회는 기존 history cursor를 덮어쓰면 안 된다.**
- `backfill_done=1`인 옛 데이터라도 **최초 NULL cursor 루트부터 시작되는 증거 체인**이 없으면 완료를 증명할 수 없다. 반대로 `backfill_done=1` + NULL cursor의 모순도 단순한 플래그 덮어쓰기로 해결하면 안 된다.
- 검수에서 교정한 오류: 한 장의 종료 페이지로 전체 history 확정, 원본 JSON 없는 커서 주장, 순환 cursor·상충 날짜 순서, `paging.next`만 있고 `after` 없는 응답을 정상 종료로 취급, 요청 전 journal 누락, 완료 표시와 쿨타임 저장 분리, 출처 파일 덮어쓰기 위험, 계정 ID/소유자 불일치, 잘못된 캐러셀 자식 complete 표기. 코드는 검수 시 합성 회귀 테스트로 개선했지만 **현실의 모든 Meta 응답 패턴을 보증한 것은 아니다**. 세부는 [기존 안전성 검수](RAW_V2_REVIEW_2026-10-19.md).
- 초기 History 소량 실험은 **KR_001~KR_005 5개 계정 HTTP 200, 20개 신규 게시물**. 해당 5계정의 근거 체인은 별도 증거 점검 후 `restore_five_history_roots.py`로 복구(커밋 `794f646`). 이는 **과거 증거를 기반으로 한 제한 복구**이며 모든 계정에 일괄 적용한 것이 아님.
- 오래된 완료 상태에 남은 10계정은 `KR_055, KR_078, US_019, US_022, US_023, US_059, US_072, US_075, JP_055, JP_061`. `legacy_root_preflight.py`에서 10건 모두 **PASS: candidate only (not restored)**: **적격 검토 통과이지 DB 복구 완료가 아니다**. 사용자 로그로 후보 적격을 확인한 뒤, 복구/선별 History 실험을 분리해 진행했다.
- 2026-10-19에 `history-only` 일반 선택기를 10개로 제한해 보니 **KR_006~KR_015**가 나왔고, 필요한 위 10계정이 아니었다. 그래서 **지정 대상만 선택하는 `--target-legacy-ten`** 옵션(커밋 `d7593b4`)을 추가. 옵션은 `--policy history-only --once --max-batches 2`를 요구, 당일 front 미완료/미해결 catchup 등이 있으면 거절, 쿨타임 우회와 조합 불가.
- PowerShell의 SQLite 읽기전용 `targeted_history_tasks()` 검증: **COUNT 10, TARGET_MATCH True, HISTORY_ONLY True**. 단 `--live` 없는 기본 CLI dry run만으로 실제 DB 선택 적격이 증명되지는 않는다. 코드는 두 배치 선택을 수집 실행 직전에 DB에서 확인한다.
- **실수집 결과:** run `20261018T192326Z_24616_e7638fda`(run_id UTC 표기; 실행일 KST 10/19): US_075, JP_061, US_023, US_019, KR_055, KR_078, US_022, JP_055, US_072, US_059 **모두 History HTTP 200**, 각 received=4,new=4. **10계정 ×4=40 신규**, 1,290→1,330, run 종료 코드 0, `SLOT CLOSED: no_eligible_accounts`.
- 당시 수집 시작 전 자동 생성 DB 스냅샷 `collection_20261018T192325463433Z.sqlite`, SHA256 `67bbb6bf83603fed47908c88a68eab9c41a3a383a94f57310287b8c1942cf3c8`, 백업 시점 POSTS=1290. **DB 스냅샷은 run/raw JSON을 포함하지 않는다.**
- 직후 `python .\raw_v2\audit.py --output-dir $out` 결과: `status=PASS`, `accounts=294`, `posts=1330`, `post_observations=1350`, `successful_accounts=286`, `unresolved_batches=0`, `integrity=0 / observation=0 / coverage=0`, exit=0. **이 감사에서 10개 경고가 사라짐**. API-visible coverage 범위와 무인승인 미완료는 유지.

### 2.4 8개 조회 실패 계정과 JP_093 원본 조사

| 계정 키 | 공식 입력 username | DB `last_error` | 본 기록에서 확인된 세부 근거 |
|---|---|---|---|
| KR_032 | `subling_nail` | `110` | 해당 원본 세부 메시지 미열람 |
| KR_061 | `nail_onlyyun` | `110` | 해당 원본 세부 메시지 미열람 |
| KR_100 | `soah_nailart.26` | `110` | 해당 원본 세부 메시지 미열람 |
| US_013 | `fiepedersen.dk` | `110` | 해당 원본 세부 메시지 미열람 |
| US_052 | `nail.betch` | `110` | 해당 원본 세부 메시지 미열람 |
| US_101 | `leni_nailz_24` | `110` | 해당 원본 세부 메시지 미열람 |
| JP_009 | `111nail_omotesando` | `110` | 해당 원본 세부 메시지 미열람 |
| JP_093 | `mio__nail_31` | `110` | 원본: `Invalid user id` / subcode `2207013` / `is_transient=false` / “사용자 이름이 mio__nail_31인 사용자를 찾을 수 없습니다.” |

- 이 8개는 DB의 `blocked=1`, `attempts=1`이 확인되었고 모두 `id`, `ig_id`, 수집/커서 정보가 없었다. 사용자가 말한 “7개 invalid, 나머지 1개?”는 **실제 DB에서 여덟 오류 코드가 동일함**을 재확인하게 된 계기다. 단 원본 세부 코드 동일성은 JP_093 외에 아직 확인되지 않음.
- JP_093 원본 경로: `runs/20261018T185100Z_21732_307c8ec8/raw/20261018T185100Z_21732_307c8ec8_0002_03_294_front.json`, 해당 run의 `raw/batch_0002.json`. 원본에는 오류 메시지와 trace id가 있다. **trace id는 공개 문서에 불필요**.
- 웹에서 `https://www.instagram.com/mio__nail_31/`를 사용자 본인이 열어 “죄송합니다. 페이지를 사용할 수 없습니다.” 화면을 확인했다. 이것은 API 오류와 정합적이나, **영구 삭제 판정이 아니라 당시 그 URL에 접근 불가하다는 관측**이다. 재시도 전에 계정명·접근 권한·공식 목록 최신성 점검 필요.
- 문제를 해결한다는 이유로 `blocked=0` 직접 UPDATE, username 임의 교체, 8개를 전체 성공률 분모에서 삭제, 공식 원본 CSV 변경, 전체 `--live` 재실행은 금지한다. 하나의 계정을 새로 시도할 수 있는 **계정 한정·횟수 한정·기록 보존형 진단 기능**을 별도 구현하고 승인받아야 한다.

### 2.5 테스트·감사·복구와 실제 동작 사이의 차이

- Windows Python 3.11의 `python .\tests\run_offline.py` **93/93 PASS**는 검수 시점에 확인됨. 최신 사용자 로그에서도 exit 0 확인. 단 **지정 10계정 옵션 추가 후 그 옵션만의 별도 합성 테스트가 없었다면** 기존 93개가 해당 신규 분기를 모두 검증했다고 표현할 수 없음. 향후 특정 대상 선택·2배치·중복 방지·진입 거부 회귀 테스트 추가.
- `daily_scheduler.py --source ... --output-dir ... --policy history-only --once --max-batches 2 --target-legacy-ten` (미지정 `--live`) 출력 **DRY RUN / zero DB writes, no credentials or API**: 실제 작업 가능 판정이 아니다. 별도 SQLite `mode=ro` 조회로 적격성 확인.
- `audit.py`는 DB 읽기 전용이며 원본 JSON/관측 및 근거를 검사한다. `PASS`가 전 세계 게시물 완전성을 증명하지 못하는 이유는 **API 접근 범위/비공개 콘텐츠/권한/삭제 게시물/미반환 필드**가 검증 범위 밖이기 때문.
- `recover.py` 기본은 **preview**. `ARCHIVE_PRESENT_UNVALIDATED`는 “파일 존재”일 뿐 재생 가능 승인 아님. `UNKNOWN_REMOTE_OUTCOME`이면 “서버가 요청을 받았는지” 확인되지 않아 **자동 재호출 금지**. `--apply`는 별도 최신 백업·복제본에서 먼저 검사하고 사용자의 명시 승인 없이는 운영 DB에서 실행 금지.
- `verify.py`는 run 별 manifest·해시·CSV 건수 및 DB 기본 검증용. **run 검사 PASS와 전체 audit PASS는 별개**.
- GitHub 코드 `main`에 최신 문서나 커밋이 있어도 사용자의 로컬 소스는 `git pull origin main` 이전 버전일 수 있다. 반대로 **운영 SQLite / raw JSON은 GitHub에 없다.** 이전 PowerShell 실행 로그가 없으면 실호출 성공을 추정하지 말 것.

## 3. 이번 단계 완료 정의

- [x] 294개 공식 목록 인식과 대상 국가 구분
- [x] 사용자 로컬 286개 계정의 최초 관측과 8개 오류 계정 분리
- [x] 최신 프로필 4건/계정 수집 + History/Catchup 분리 설계 및 실제 제한 수집
- [x] 5개 History root/이어받기 증거 관련 별도 점검
- [x] 레거시 10계정 지정 History 실호출 10/10 성공
- [x] 마지막 **audit PASS, 3분류 0건, unresolved batches 0**
- [x] JP_093의 원본 Meta 110/2207013와 사용자 브라우저 접근불가 관측
- [ ] 미실패 7계정 각각 **Meta 원본 세부 오류 + 계정 현황 분류** (후속)
- [ ] 정확한 365일/730일 기간 범위와 계정별 coverage 품질 판정 (후속)
- [ ] 무인 스케줄러·지속 운영 승인/모니터링 (후속)
- [ ] 팀 인수용 CSV/JSON 추출물·컬럼 계약·개인정보/비밀값 제거·SHA256 전달 검수 (후속)

후속 작업은 [오류 분류·대응 SOP](RAW_V2_ERROR_HANDLING_RUNBOOK.md), [우선순위별 남은 과제](RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md)를 따른다. 오프라인 진단으로 해결 가능한 일을 불필요한 Meta 호출로 해결하지 않는다.

## 4. 참조/근거 고정

- 직접 실행된 최종 run: `20261018T192326Z_24616_e7638fda`; 사후 audit `checked_at_utc=2026-10-18T19:23:49.568097+00:00`.
- JP_093 실패 run: `20261018T185100Z_21732_307c8ec8`, batch `0002`.
- 중요 코드 커밋: 5개 root 복구 `794f64630917da5cb7ef4279107188023b0fb4b0`; offline acceptance `97a705fc8cf720df61eeb8247cb87fbffd5cd953`; 지정 10계정 대상 `d7593b4ded857ecac40f65b28572cb7ce634b12f`.
- 소스 문서: [RAW v2.1 실행 매뉴얼](../raw_v2/README.md), [RAW 안전성 검수](RAW_V2_REVIEW_2026-10-19.md), [핸드오프](../HANDOFF.md), [상태 로그](../STATUS.md).
- 수치나 기한이 충돌하면 **날짜/실행 ID/데이터 출처**를 함께 적고 가장 최근 **사용자 운영 로그를 해당 시점의 기준**으로 삼는다. 임의로 과거 수치를 고치거나 “전량 완료”라고 써서는 안 된다.
