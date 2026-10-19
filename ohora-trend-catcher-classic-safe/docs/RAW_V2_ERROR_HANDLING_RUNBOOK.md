# OHORA RAW v2.1 오류 탐지·분류·대응 Runbook (SOP)
> 적용 기준: 2026-10-19 KST · **새 Meta 실호출 없이 원인 분류 → 증거 보존 → 위험도 판정 → 승인된 범위에서만 변경**. 본 문서는 개발자·운영자·팀원·후속 AI를 위한 절차다.
>
> 관련: [실제 트러블슈팅 연대기](RAW_V2_2026-10-19_TROUBLESHOOTING_CHRONICLE.md) / [남은 작업·인수기준](RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md) / [수집기 안내](../raw_v2/README.md).

## 1. 오류 발견 직후 — 변경 금지, 재시도 금지

1. **Stop:** 원인 미상인데 새 `--live` 실행, 작업 자동 반복, 쿨타임 강제 해제, 다른 앱/토큰으로 임의 재실행하지 않는다. 이미 실행 중이면 안전하게 Ctrl+C로 중단; **종료 직후 DB/JSON 완성 여부는 반드시 audit로 검사**한다. DB 파일을 탐색기에서 직접 복사하는 것은 WAL 시점의 일관성을 보장하지 못하므로 `backup.py` 사용.
2. **Identify:** 실행 시각 **UTC/KST 구분**, `run_id`, 계정 키, phase(front/catchup/history), batch 번호, request ID, HTTP 상태, Meta `code` / `error_subcode` / `is_transient`, 원본 `error_user_msg`, `X-App-Usage`, collector exit code를 수집한다. `last_error=110` 하나로 하위사유를 확정하지 않는다.
3. **Preserve:** `collection.sqlite`의 일관된 스냅샷 + `runs/<run_id>/raw` 원본 JSON + 로그·manifest·공식 원본의 해시를 안전한 로컬 위치에 보관. API access token, client secret, 쿠키, 환경파일 본문은 공유하지 않는다.
4. **Diagnose offline:** `audit.py`, `recover.py` preview, 해당 실행 `verify.py`, DB 읽기 전용 SQL과 해당 원본만 분석. `audit FAIL`/미해결 batch는 **추가 실호출 금지**.
5. **Classify:** 아래 심각도/원인 유형과 상태 전이 규칙대로 처리. **오류 원인 미확정이면 UNKNOWN**. 코드 수정이나 대량 보정 전에 영향 범위·재현 조건·롤백 방안·테스트를 작성.
6. **Reopen only if safe:** 오프라인 테스트 PASS, DB snapshot/원본 보존, 당일 front/slot/ready_at/Meta 사용량 여유 확인, 필요한 경우 사용자에게 **계정/배치/횟수/옵션**을 특정해 별도 승인 요청. 성공 후 같은 항목 재감사.

## 2. 오류 분류표 — API, 수집 파서, 데이터 완전성, 로컬 운영

| 분류 | 증상/확인할 코드 | 우선 심각도 | 기본 조치 / 금지 |
|---|---|---|---|
| **대상 계정 불명** | Meta `110`, 특히 `2207013`/Invalid user id | 계정 단위 P2, 별도 관리 | 해당 계정만 review/blocked; 입력 username·공식 목록·수집 당시 raw·브라우저 관측 비교. **DB에서 차단 해제/CSV 임의 변경/무한 재시도 금지** |
| **인증 만료/누락** | 401, Meta 102/104/190, credential path missing | 전체 P0 | `--live` 즉시 중단, 로컬 인증 경로 존재 여부 → 토큰 갱신/권한 복구; 노출 시 키 폐기. 수집 실패를 계정 삭제로 오진 금지 |
| **권한·앱 접근 거부** | HTTP 403, Meta 10/200; 일부 400도 원문 확인 | 전체 P0 | 앱 권한, IG 전문 계정, FB 연결, Business Discovery 가능 여부 확인; 권한 없이 다른 계정으로 우회하지 않는다 |
| **요청 제한/비정상 호출** | Meta 4/17/32/613, HTTP 429, `X-App-Usage >=85%` | 슬롯 P1 | 후속 배치 정지; DB의 `ready_at`보다 이르게 재개 금지; Meta 대시보드 확인. 더 긴 대기가 필요할 수 있음 |
| **사용량 헤더 없음/이상** | `X-App-Usage` 누락, NaN/inf/음수 등 | P0/P1 | 근거 없는 반복을 멈춤; HTTP/batch 헤더 원본과 파서 검증. 값 `0.0`은 무료/무제한의 증명이 아님 |
| **네트워크 타임아웃/연결 실패** | URLError/TimeoutError, 프로세스 중단 | P1 | 실제 요청 전송 여부/원격 처리 여부가 불명일 수 있음; `batch_attempts`/원본/요청 journal 대조 후 복구 판단. 자동 재호출 금지 |
| **배치 결과 불일치** | 외부 배치 응답 개수≠요청 개수, JSON parse 실패, 미해결 batch | P0 | journal·원본 보존 → recover preview; 의도적 중복 요청 만들지 않음 |
| **ID·소유권 충돌** | `account identity mismatch`, 다른 계정의 post/child ID, numeric ID 부재 | 전체 P0 | 수집 중단, account-key/IG identity/원본 대조; ID를 맞추려고 DB 내용을 바꾸지 않음 |
| **paging/cursor 훼손** | after 없음, 순환/동일 커서, 페이지 날짜 역행, root 누락 | P0/P1 | 보수적으로 완료 미검증, 근거 검토; `backfill_done` 강제 변경 금지; 필요 시 타깃 제한 검증 설계 |
| **History 완료 증거 부재** | `UNVERIFIED_LEGACY_COMPLETION`, `COMPLETION_WITH_GAPS` | P2 또는 사용 목적에 따른 P1 | 원본/root/checkpoint 검토, history-only 적격성 확인; 전역 플래그 초기화 대신 증거 기반 제한 복구 또는 실수집 |
| **catchup 미해결** | `UNRESOLVED_CATCHUP`, queued gaps, active catchup | P1/P2 | front 이후 catchup 먼저; history가 우선이라고 임의 결정하지 않음 |
| **좋아요/선택필드 미반환** | 200이지만 `like_count` absent/null | 데이터 품질 P2 | `absent`/NULL/미지원/미실험과 진짜 0 구별; 원본/미디어 유형/필드지원 CSV로 조사; 0으로 대치 금지 |
| **캐러셀 불완전** | children 추가 페이지, `partial`, 잘못된 complete | 품질 P2 (타계정 소유 ID면 P0) | child coverage 분리; 자식 ID 무결성 확인; partial을 complete로 재라벨링 금지 |
| **DB 무결성/원본 불일치** | `audit FAIL`: SQLITE_INTEGRITY / FOREIGN_KEYS / RAW_METRIC_MISMATCH / HISTORY_EVIDENCE_* / UNRESOLVED_API_BATCH 등 | 전체 P0 | 추가 `--live` 금지, 원본/백업 대조, 복구 전 복제본 선검증. 백업만으로 raw JSON을 대체할 수 없음 |
| **감사 WARN** | integrity/observation/coverage 경고 | P1/P2 원인별 | 경고 코드를 계정·원본과 매칭하고 해석. `--acknowledge-warnings`는 경고를 삭제하지 않음 |
| **경로/환경 설정** | `--env-file` 없음, source hash changed, DB 다른 위치, 파일 잠금/WinError | P1 | 작업환경/원본/로컬 DB 위치 확인, 다른 실행 프로세스 없는지 조사; 경로 오류를 Meta 문제로 오진 금지 |
| **날짜/정책 차단** | `front_pending`, KST rollover, cooldown, `no_eligible_accounts` | 정상 안전 차단 또는 P2 | 출력 원인 확인. 강제 우회하거나 차단을 HTTP 실패로 집계하지 않음 |
| **관측 기록 중복** | 고유 post 수와 observations 수 차이 | 통상 정상 | post ID 기준 중복 저장 방지 + 관측 시점별 metric 기록은 정상. 실제 중복 PK/누락만 문제 |

**심각도 정의:** **P0** 운영 중단·수동 검토·새 API 요청 불허. **P1** 해당 슬롯/작업 중지 및 원인 해결 후 승인된 제한 재개. **P2** 계정·필드·품질 예외로 표기하고 다른 정상 데이터는 보존. 심각도는 운영 SOP상의 우선순위이며 코드가 자동 생성하는 등급은 아니다.

### 2.1 Meta 110 해석의 주의점

`110`은 이 프로젝트에서 차단 플래그를 세우는 코드다. **API 코드만으로 “실제 삭제 계정”을 뜻하지 않는다.** 프로젝트가 직접 확인한 JP_093 원본에는 `OAuthException`, `message=Invalid user id`, `error_subcode=2207013`, `is_transient=false`, `error_user_msg`가 있다. 이는 **지정 사용자명을 Business Discovery 호출로 조회하지 못했다**는 사실까지만 확정한다. 사용자가 동일 URL에서 “페이지를 사용할 수 없습니다”를 본 것도 시점 한정 근거다.

**8개 실패 목록:** KR_032 `subling_nail`, KR_061 `nail_onlyyun`, KR_100 `soah_nailart.26`, US_013 `fiepedersen.dk`, US_052 `nail.betch`, US_101 `leni_nailz_24`, JP_009 `111nail_omotesando`, JP_093 `mio__nail_31`. 전부 SQLite `last_error=110`; 다른 7개의 subcode 및 브라우저 확인은 아직 미검증.

**다시 접근 가능해질 때의 처리:** 공식 목록 관리 책임자에게 계정 변경 여부 확인 → 이전 키/원본 username/새 username을 별도 매핑 기록 → 기존 수집 기록·ID 충돌 검사 → 타깃 한정 재시도 기능을 **코드로 설계·테스트** → Meta 사용량/쿨타임/당일 front 선행 조건 확인 → 사용자 **명시 승인을 얻어 1회** 실행 → 새로운 raw·DB·감사 확인. **현재 CLI에 임의 계정 1개 강제 재시도를 지원하는 안전한 검증 완료 옵션이 있다는 뜻은 아니다.**

## 3. 읽기 전용 진단 명령 (Windows PowerShell)

작업 폴더는 저장소 루트, `$out`은 **기존 수집 DB 위치**. 아래 명령에는 `--live`가 없다.

```powershell
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
python .\raw_v2\audit.py --output-dir $out
Write-Host "AUDIT_EXIT_CODE: $LASTEXITCODE"
python .\raw_v2\recover.py --output-dir $out   # preview only, --apply 사용 금지
python .\raw_v2\verify.py --output-dir $out --run-id 20261018T192326Z_24616_e7638fda
python .\tests\run_offline.py
```

### 3.1 차단 계정 확인 (read-only SQLite)

Python 3.11, PowerShell here-string. `mode=ro`에 `query_only=ON`을 사용하며 계정 상태를 변경하지 않는다.

```powershell
@'
import os,sqlite3
from pathlib import Path
path=Path(os.environ['LOCALAPPDATA'])/'OHORA_RAW_v2'/'collection.sqlite'
db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
db.execute('PRAGMA query_only=ON')
for row in db.execute("""SELECT account_key,input_username,blocked,
                               attempts,last_error,last_attempt,
                               backfill_done,backfill_cursor,catchup_cursor
                        FROM accounts WHERE blocked=1 ORDER BY ordinal"""):
    d=dict(row)
    d['backfill_cursor']=bool(d['backfill_cursor'])
    d['catchup_cursor']=bool(d['catchup_cursor'])
    print(d)
db.close()
'@ | python -
```

### 3.2 실패 코드·원본 로그를 정확히 짝짓기

`request_log`에서 **시각, account_key, run_id, request_id, raw_response_path**를 묶어 조회한다. 원본의 JSON 토큰이 제거됐는지 확인하고, 오류 메시지에는 URL/개인정보가 포함될 수 있으니 공개 공유 전에 마스킹한다.

```powershell
@'
import os,sqlite3
from pathlib import Path
base=Path(os.environ['LOCALAPPDATA'])/'OHORA_RAW_v2'
db=sqlite3.connect((base/'collection.sqlite').as_uri()+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
db.execute('PRAGMA query_only=ON')
for r in db.execute("""SELECT account_key,run_id,request_id,phase,http_status,
                              error_code,error_subcode,error_message,raw_response_path
                       FROM request_log WHERE status!='success'
                       ORDER BY finished_at DESC LIMIT 30"""):
    x=dict(r)
    x['raw_exists']=(base/str(x['raw_response_path'])).is_file()
    print(x)
db.close()
'@ | python -
```

**중요:** 기존 `accounts.last_error`는 요약 코드만 담을 수 있다. subcode와 사람이 읽을 원문은 `request_log` 및 run 원본 응답까지 추적한다. 메타 응답의 `is_transient`는 원본 파일에서 확인.

### 3.3 JP_093 사건을 재현 없이 재검토하기

```powershell
$folder = Join-Path $out 'runs\20261018T185100Z_21732_307c8ec8\raw'
Get-ChildItem $folder -Filter '*.json' |
  Select-String -Pattern 'mio__nail_31|JP_093' -Context 3,8 |
  Format-List Path,LineNumber,Line,Context
```

**관측 결과(기록됨):** `Invalid user id`, code 110, subcode 2207013, `is_transient=false`, `error_user_msg`에서 사용자를 찾을 수 없다고 반환. 다만 Meta의 trace id는 내부 기록만 유지하고 팀 공유 문서에 과다 노출하지 않는다.

## 4. 운영 흐름별 진단·대응

### 4.1 실행 이전

- `git status`로 로컬 변경/스태시 확인; 기존 수집기 파일의 stash를 임의로 `pop`하지 말 것. `git pull origin main`은 충돌 위험을 보고 판단.
- `Test-Path $src`, `Test-Path $envFile`, `Test-Path (Join-Path $out 'collection.sqlite')`; 어떤 DB를 열고 있는지 먼저 확정.
- `python .\tests\run_offline.py`, `audit.py`, `recover.py` preview. `audit FAIL`이면 종료; `audit WARN`이면 원인 검토. `--acknowledge-warnings`는 사유를 이해했다는 명시 플래그이며 복구가 아님.
- **백업이 필요하면:** `python .\raw_v2\backup.py --output-dir $out --backup-dir (Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2_backups')`. 별도로 `runs` 복사 및 원본·사본 SHA 점검. run 원본이 누락된 backup은 포렌식 완전체가 아니다.
- `daily_scheduler.py`는 `--once`가 **한 배치**라는 뜻이 아니다. 최대 **한 실행**이며 기본 30배치가 가능. 한 배치 시험이면 `--once --max-batches 1`을 같이 명시.
- 쿨타임은 `slots.ready_at`과 Meta 실제 사용량을 둘 다 확인. **시간만 지나도 할당량이 회복될 것이라고 가정하지 않는다**.
- 반드시 실제 수집 대상 키와 phase를 미리 DB에서 검토. dry-run 출력만으로 DB 대상 검증 불가.

### 4.2 실행 중

- `HTTP=200`인데 필드 없음 → 성공과 품질 경고를 따로 기록. `new=0`은 중복 게시물 재관측일 수 있다.
- `HTTP=200`인데 `invalid_payload`이면 파서·스키마·ID/게시물 순서 먼저 조사. 무조건 재시도하지 않는다.
- rate/usage 차단이면 다음 배치를 멈추고 `SLOT CLOSED` 및 `next_ready_at_utc` 저장 확인.
- 네트워크 예외라면 원격 호출 결과를 모른다는 사실을 기록한다. **같은 요청을 재보내면 중복 과금/중복 처리 가능성**이 있다.
- 하루 날짜 변경 시 KST 정책 재검사가 있어야 하고, front가 남아 있으면 history를 강행하지 않는다.
- 강제 Ctrl+C·노트북 절전·네트워크 전환은 실패 시점 판단을 어렵게 하므로 실행 전 예상 배치 범위와 로그 폴더를 기록.

### 4.3 실행 이후

- `COLLECTION_EXIT_CODE`, `run_status`, `SLOT CLOSED`, `next_ready_at_utc`, 계정별 HTTP 상태 수, **고유 신규 게시물 수**를 저장.
- `python .\raw_v2\audit.py --output-dir $out` 다시 실행; integrity/observation/coverage와 unresolved batches 비교.
- 방금 실행한 run을 `verify.py --run-id <run-id>`로 검사. **기존 DB 총건수 = 이번 실행 신규건수**로 착각하지 않는다.
- FAIL이면 export·팀 전달·다음 --live 중지; WARN이면 코드별 영향·해결 계획 기록; PASS이면 **측정 가능한 범위**만 합격 선언.
- 원본 JSON·실행 CSV·manifest·SHA와 별도 DB 스냅샷을 적절히 보관하되, **GitHub에 Meta 원본 사용자정보·로컬 DB·토큰을 자동 업로드하지 않는다**.

## 5. 복구 정책과 롤백의 금지선

| 발견 상태 | 자동 재호출 | 기본 처리 |
|---|---|---|
| `batch_attempts` 완결 | 불필요 | run/audit/manifest 검증 |
| 미완결, 전송 전 취소가 입증됨 | 원칙적으로 별도 승인 필요 | 저널 상태·원본 검증 |
| `response_saved` + 원본 JSON 존재 | 금지 | `recover.py` preview → 복제본에서 유효성 테스트 → 필요한 경우 별도 승인 `--apply` |
| `prepared`인데 원본 없음 / UNKNOWN_REMOTE_OUTCOME | **금지** | 서버 처리 여부 모름; 포렌식·수동 대조 우선 |
| `requires_review` / 로그인·권한 오류 | **금지** | 인증·권한 조치 후 승인된 신규 실행 설계 |
| audit FAIL | **금지** | DB 스냅샷·원본·로그 대조, 코드 테스트 후 통제된 복구 |
| audit PASS / 8계정 110 | 전역 재시도 금지 | 대상 계정 보류, 원본 subcode 분류 후 제한된 확인 |

**롤백:** 코드 문제는 변경 커밋을 좁혀 `git revert` 검토. 사용자 **운영 DB를 이전 스냅샷으로 즉시 덮어쓰지 않는다**. 그러면 이후 성공한 게시물 40건과 관측·history cursor·slot 정보가 사라질 수 있다. 되돌리기 전 원본 현재 상태와 백업을 모두 검증하고 운영자 승인을 받는다.

## 6. 사고 보고 템플릿 — 새 채팅방/팀원에게 그대로 전달

```text
[OHORA RAW v2.1 Incident]
발견 시각 (KST/UTC):
Git HEAD / 로컬 미커밋 변경:
대상 DB 경로 (토큰 경로와 내용 제외):
run_id / batch_no / request_id / account_key:
phase / username (공식 목록 기준):
HTTP / Meta code / subcode / is_transient:
원본 메시지(비밀값·trace 마스킹):
기존 DB 상태 및 cursor (실제 cursor 값은 외부 공유 금지):
Meta X-App-Usage / 슬롯 ready_at:
audit 결과 integrity / observation / coverage:
raw JSON 및 run manifest 존재/해시:
로컬 테스트 명령과 실제 exit code:
수정/재실행한 작업과 승인 근거:
현재 영향 범위와 미검증 사항:
다음 1회 안전 작업 및 합격/중단 기준:
```

### 반복하지 않을 실수

- 경고 10건을 없애려고 **대상 선택을 검증하지 않은 전체 294계정 History** 실행
- dry-run “success”를 실제 API/DB 검사 PASS로 오인
- 오류 110을 모두 계정 삭제로 단정
- `--once`를 1개 배치로 오해하거나 `--acknowledge-warnings`를 무결성 실패 우회로 오용
- 지난 버전의 60/70분 규칙과 최신 63/65분을 혼용
- 동일 실패 방법을 무한 반복. 같은 방식으로 1~2회 실패하면 **원인/제약/대안**으로 전환
- 최종 audit PASS로 “1년 전량 수집/자동운영 가능”을 선언
