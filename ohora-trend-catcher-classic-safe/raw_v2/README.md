> **2026-10-19 사용률 로그 개선:** `daily_scheduler.py`는 각 상태 조회 및 수집 종료 후 `META API USAGE (last run observed maximum): N%; STOP THRESHOLD: 85%`를 표시한다. 값은 `runs.usage_max`에 저장된 **마지막 실행 관측 최대치**로, 실시간 Meta 잔여 할당량은 아니다. 기존 DB 쿨타임 `ready_at`·커서·API 요청 정책은 변경하지 않는다. 현재 실행 중인 프로세스에는 적용되지 않으므로 쿨타임 대기 중 Ctrl+C로 종료 후 `git pull --ff-only origin main` 및 기존 실행 명령으로 재시작한다.\n\n> **2026-10-19 실제 사용자 로컬 실수집 이후 운영 기록:** History 10계정 10/10 HTTP 200·40개 신규, 현재 누적 게시물 1,330/관측 1,350, audit PASS(무결성/관측/커버리지 0/0/0), 8계정 Meta 110 차단, 무인 운영 미승인. 아래 기존 검수 안내 중 “실제 Meta 호출 미수행” 문구는 **당시 검수 작업 자체**에 대한 설명이며, 이후 사용자 PC에서 실제 수집을 실행했다.
>
> **운영 문서:** [전체 트러블슈팅](../docs/RAW_V2_2026-10-19_TROUBLESHOOTING_CHRONICLE.md) · [오류 SOP](../docs/RAW_V2_ERROR_HANDLING_RUNBOOK.md) · [향후 과제/인수 기준](../docs/RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md)

# OHORA RAW v2.1 — 안전성 검수 후 실행 안내

최신 기준: 2026-10-19. `500523b1c18e11863c025c0418f84d6be00e80b4`의 기존 구현을 검수하고 확인된 잔여 결함만 수정했다. Windows Python 3.11 오프라인 회귀 검증이며 실제 Meta 호출·운영 DB 복구는 수행하지 않았다. 무인 대량 수집 승인 상태는 아니다.

## 고정 운영 정책

- 공식 로컬 294계정(KR100/US101/JP93), 인증 계정 1개, 게시물 4개/계정, Graph Batch 5개 하위요청, 슬롯당 최대 150개 서로 다른 계정.
- 응답에서 제공된 유효한 X-App-Usage 수치 중 최댓값이 85% 이상이면 후속 배치를 중단한다. NaN·무한대·음수는 유효 수치가 아니다. 해당 배치 전체에서 유효 수치가 없으면 자동 반복을 중단한다. 응답 후 검사하므로 85% 이하 유지나 한도 회복을 보장하지 않는다.
- 슬롯 종료 후 최소 63분, 자동 반복의 시작 간격 목표 65분: `next_start = max(finished_at + 63분, started_at + 65분, 기존 ready_at)`. 공통 `collector.slot_ready_at()`과 DB 상태로 판단한다. 기존 `ready_at`은 소급 덮어쓰거나 앞당기지 않는다. 부분 슬롯은 중복 계정을 제외하고 이어간다.
- 인증·권한·계정 식별/소유권 충돌·사용량 근거 부재는 자동 반복 중단(수집기 코드 3). #4/사용량 임계값은 안전 중단(코드 2)과 쿨타임. 저장 실패는 전체 중단(코드 1). 미해결 배치가 있으면 다음 요청을 거절한다.
- 특정 계정은 단계별 일일 최대 2회 후 예외로 분리한다. 접근 불가·재시도 소진은 성공 계정 수에 포함하지 않는다. 선택 필드 누락은 NULL/상태로 보존한다.

## 완료와 복구 근거

`backfill_done`은 과거 상태 플래그이며 완전성 증명이 아니다. `history_page_evidence`에서 최초 NULL 커서 페이지부터 모든 요청→응답 커서, 날짜 순서, 고정 기준일 도달 또는 API 종료, 최종 체크포인트를 검증한다. audit는 성공 요청·원본 JSON도 대조한다. catchup과 대기 gap이 남으면 전체 커버리지는 미검증이다.

기존 완료 플래그는 일괄 초기화하지 않는다. 근거 없는 완료+NULL 커서도 영구 제외하지 않고 history의 첫 페이지부터 새 증거를 확보할 대상으로 선택한다. 기존 게시물·관측·과거 증거는 보존한다. 프런트의 오래된 고정 게시물 때문에 순서를 입증할 수 없으면 UNKNOWN/검토 상태로 남을 수 있다. oldest/newest만으로 1년 확보율을 산출하지 않는다.

요청 전에 ID·옵션·커서/계정 상태·슬롯·일일 처리 여부를 저널에 기록하고, 전체 응답 원본을 저장한 다음 계정 단위 게시물·관측·커서·로그·슬롯·일일 상태를 원자적으로 커밋한다. 원격 호출을 정확히 한 번 실행했다고 주장하지 않는다. 원본 없는 미완료 요청은 UNKNOWN이며 자동 재호출하지 않는다.

`recover.py`는 기본 읽기 전용 preview다. `ARCHIVE_PRESENT_UNVALIDATED`는 파일이 있다는 뜻이며 복구 가능 판정이 아니다. 명시적인 `--apply`는 별도 승인 대상이다. 코드상 별도 최신 백업과 원본 목록이 필요하며, 잠금 안에서 스키마·전체 저장값·요청 상태를 비교하고 메모리 복제본에서 전체 재생을 먼저 검증한다. 옵션 없는 구형 저널·상태 불일치·기존 export 충돌은 수동 검토로 차단한다. 기존 원본과 CSV/manifest를 덮어쓰지 않는다. 인증 오류 응답을 복구하면 성공분은 보존하되 `requires_review`로 후속 수집을 차단한다.

## Windows: 백업 → 진단 → dry run → 사용자 수동 한 배치 → 사후 진단

아래 명령은 저장소 루트에서 실행한다. `$src`는 공식 목록이며 수정·대체하지 않는다. 비밀 파일의 내용은 출력하지 않는다. 마지막 `--live` 명령은 사용자가 직접 실행하는 제한 시험이다.

```powershell
$src = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브\2차 프로젝트 데이터\account_list.csv'
$envFile = 'C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection\.env.local'
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backup = Join-Path $env:LOCALAPPDATA "OHORA_RAW_v2_backups\manual_$stamp"
$report = Join-Path $env:LOCALAPPDATA "OHORA_RAW_v2_audit_$stamp"
python .\tests\run_offline.py
python .\raw_v2\backup.py --output-dir $out --backup-dir $backup
# SQLite 스냅샷에 원본 JSON은 포함되지 않으므로 runs도 별도 보존한다.
Copy-Item -LiteralPath (Join-Path $out 'runs') -Destination (Join-Path $backup 'runs') -Recurse
python .\raw_v2\audit.py --output-dir $out --report-dir $report
python .\raw_v2\recover.py --output-dir $out
python .\raw_v2\daily_scheduler.py --source $src --output-dir $out --policy bootstrap-history
# 보고서의 WARN 원인을 검토한 뒤, 사용자만 직접 실행:
python .\raw_v2\daily_scheduler.py --source $src --env-file $envFile --output-dir $out --policy bootstrap-history --once --max-batches 1 --acknowledge-warnings --live
python .\raw_v2\audit.py --output-dir $out --report-dir "${report}_after"
```

audit는 `mode=ro`, `query_only`, 일관된 읽기 트랜잭션을 사용하고 마이그레이션하지 않는다. 보고서는 수집 폴더 밖에만 저장한다. DB가 없으면 UNKNOWN, 무결성/논리/관측 오류는 FAIL(종료 코드 2), 근거 없는 완료는 WARN이다. 스케줄러는 FAIL을 차단하고 WARN은 원인 검토 후 `--acknowledge-warnings`가 있어야 진행한다. 이 옵션은 실패를 해제하지 않는다.

dry run은 `--live`가 없으며 공식 목록 검증·정책 안내만 한다. DB·인증 파일·API를 사용하지 않는다. 성공한 슬롯 두 개가 반드시 294/294를 뜻하지 않는다. 사용량 제한으로 더 일찍 멈출 수 있다.

## 10월 19일과 20일 이후

```powershell
# 2026-10-19: 한 번도 첫 페이지를 확보하지 못한 계정 → catchup → history
python .\raw_v2\daily_scheduler.py --source $src --env-file $envFile --output-dir $out --policy bootstrap-history --once --acknowledge-warnings --live
# 2026-10-20 이후: KST 당일 최신화. 미완료 계정부터 이어간다.
python .\raw_v2\daily_scheduler.py --source $src --env-file $envFile --output-dir $out --policy daily-front --once --acknowledge-warnings --live
# 당일 미시도/재시도 가능 대상이 없어진 후 catchup → history
python .\raw_v2\daily_scheduler.py --source $src --env-file $envFile --output-dir $out --policy history-only --once --acknowledge-warnings --live
```

`--once`는 수집 실행 최대 한 번이며 기본 최대 30배치다. 한 배치 시험에는 반드시 `--max-batches 1`을 함께 준다. 쿨타임 중 `--once`는 대기 없이 결과를 보고하고 종료한다. `--once`를 빼면 전경 반복하며 Ctrl+C로 중단한다. Windows 예약 작업/서비스와 n8n은 설치하지 않는다.

- `daily`(기존 daily-first): 오늘 최신화 → catchup → history.
- `bootstrap-history`: 기존 관측을 오늘 성공으로 바꾸지 않는다. 시작한 KST 날짜가 끝나면 다음 배치 전에 종료한다.
- `daily-front`: 당일 최신화만 수행한다. 정상 순서는 1~150, 151~294다.
- `history-only`: 당일 최신화 미시도·재시도 가능 대상이 남으면 `front_pending`, 종료 코드 4로 차단한다. 접근 불가/검토/재시도 소진은 별도 예외다. 날짜가 바뀌면 처리 중 배치를 마친 후 새 날짜 조건을 다시 검사한다.

직접 수집기의 `balanced/front/history`, `--limit 5`, `--history-days 730`은 호환 지원한다. `raw_v2/run_70m_loop.ps1`은 legacy balanced용이며 공통 DB 쿨타임을 읽는다. 운영 권장 진입점은 `daily_scheduler.py`다.

## 검증 범위와 롤백

테스트 명령은 `python .\tests\run_offline.py`이며 외부 소켓 연결을 차단한다. 최신 통과 수와 로컬 데이터 진단 결과는 `STATUS.md`, 세부 검수 결과는 `docs/RAW_V2_REVIEW_2026-10-19.md`를 따른다. 기존 `verify.py`는 실행별 manifest SHA/CSV 검사로 보조 사용한다.

실제 Meta 커서·필드 지원·권한·한도 회복·1년 커버리지와 무인 장기 운영은 미검증이다. 코드 롤백은 이번 검수 커밋을 `git revert <검수 커밋 SHA>`로 되돌린다. DB·원본 JSON·관측·슬롯·백업은 삭제/교체하지 않는다. 추가 테이블은 그대로 두어도 구형 코드가 무시한다. 구형 코드에는 확인된 안전성 결함이 있으므로 롤백 후 live는 중지한다. 운영 DB 복구 적용은 별도 승인 전까지 실행하지 않는다.
