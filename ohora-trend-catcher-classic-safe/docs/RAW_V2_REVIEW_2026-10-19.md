# RAW v2.1 잔여 안전성 결함 검수 결과 — 2026-10-19

## 기준과 판정

시작: `main`, HEAD `500523b1c18e11863c025c0418f84d6be00e80b4`, 미커밋 변경 없음. 기존 53개 테스트와 이미 반영된 구현을 재사용했다. 검수 브랜치는 `codex/raw-v2-safety-review`다. 운영 DB 복구·Meta 요청·배포는 실행하지 않았다.

**판정: 제한된 시험만 가능.** Windows 오프라인 93/93 통과는 실수집 성공·1년 완전성·무인 대량 수집 승인 근거가 아니다.

## 재현한 결함과 최소 수정

| 결함 | 수정·검증 결과 |
|---|---|
| 종료 evidence 한 행만으로 전체 이력을 검증함 | 최초 NULL 커서 root부터 모든 요청→응답 연결, 순환, 페이지 간 날짜 순서, 종료/고정 cutoff, 현재 체크포인트 검증. audit에서 원본 응답의 커서·날짜·성공 요청도 대조 |
| 완료+NULL 커서 계정이 영구 제외됨 | 기존 플래그를 일괄 초기화하지 않고 근거 없는 계정도 history NULL 커서 요청으로 재검증 대상으로 선택. 과거 행은 보존 |
| history-only가 오늘 미시도/재시도 대상을 무시함 | 공통 pending 판단으로 front_pending/코드4. 예외는 성공으로 세지 않음. 날짜 전환 전후 다음 배치 정책 재검사 |
| 백업은 행 수만 같으면 허용됨 | 잠금 안에서 스키마·모든 행/저장값 비교. 동일 행 수의 다른 커서도 거부. Windows 연결을 명시적으로 닫음 |
| 복구가 요청 당시 커서·옵션·일일 정책을 추측함 | 사전 저널에 고유 ID, 옵션, 커서/계정 상태, daily_day, 쿨타임 저장. 복구 전 source/슬롯/실행/상태 확인. 구형 메타데이터 부족은 수동 검토 |
| 복구 중 후반 오류 전에 앞부분이 변경됨 | 모든 응답을 메모리 복제본에서 선검증. 기존 원본/CSV/manifest 충돌은 덮어쓰기 없이 거부. 이미 커밋된 요청은 중복 관측 없이 건너뜀 |
| 완료 표시 후 export/쿨타임 실패 시 즉시 재개 가능 | 제한 응답은 완료와 쿨타임을 같은 트랜잭션에 저장. 복구는 쿨타임 영속화 후 완료 처리·export. 인증/권한 오류 복구는 requires_review로 차단 |
| 종료 후65분 코드와 종료 후63분 문서 불일치 | 공통 slot_ready_at에 max(finish+63분, start+65분, saved ready_at). scheduler/collector/복구/legacy loop 공유. 과거 ready_at 덮어쓰기 없음 |
| catchup 다단계 순환, 잘못된 paging 종료 해석 | 별도 catchup 페이지 근거와 anchor별 순환 탐지. 잘못된 paging/cursors 자료형·next만 있고 after 부재는 종료로 승인하지 않음 |
| 안정 ID와 같은 계정의 정상 사용자명 변경도 거부 | 기존 discovery ID가 일치하면 유효한 반환 사용자명을 허용하고 공식 input_username은 보존. ID/소유권 불일치는 전체 중단 |
| 잘못된/중복 carousel 자식이 complete로 취급됨 | 게시물·관측값은 보존하며 불완전 자식은 partial. 재관측 시 보완, 다른 게시물 소유 자식은 전체 중단 |
| NaN/무한대/음수 usage가 후속 배치를 허용함 | 유한 비음수만 사용하며 유효 지표가 없으면 후속 배치·자동 반복 중단 |
| audit 출력이 수집 하위 경로를 덮을 수 있음 | 보고서는 수집 폴더 밖만 허용. 미선언 논리 관계·계정 관측값 대조 추가. DB 없으면 UNKNOWN, DB를 만들지 않음 |

복구 구형 코드의 8개 선택 회귀를 기준 HEAD 파일로 재현하여 모두 실패함을 확인했다. 코드의 잘못된 paging와 제한 응답/복구 export 중단 경계도 합성으로 재현했다. 이미 수정된 정상 기능을 새로 구현하지 않았다.

## 실제 로컬 데이터 — 읽기 전용

- 최종 audit: **WARN**. 물리 무결성·외래키·논리 관계·원본 관측값 대조 오류 0, 미해결 batch 0.
- 공식 계정 294, 관측 계정 263, 게시물 1,178, 미디어 3,152, 게시물 관측 1,178. 성공 요청 수×4로 계산하지 않았다.
- 미검증 과거 완료 10계정. 실제 완료+NULL 커서는 0건이며 그 경로는 합성 회귀로 확인했다. 로컬 데이터를 정상·완전으로 승인하지 않는다.
- SQLite backup API로 별도 복제본과 runs 사본을 만들고 복제본에서만 호환 마이그레이션을 실행했다. 기존13개 테이블의 원래 모든 행 변경/누락 0, 복제본 integrity_check=ok. 추가5개 테이블. 원본 DB SHA-256 전후 동일.
- 복제본 recover preview는 미해결 배치 없음. apply 재생 시험은 합성 임시 저장소/백업에서만 수행했다. 운영 DB apply는 실행하지 않았다.

전체 진단·복제본·로그는 gitignored `raw_v2_results/review_20261019/`에만 있다. 원본 목록·DB·JSON·토큰은 GitHub에 포함하지 않는다. 보고 시각은 도구가 UTC로 기록하며 사용자 기준 날짜는 KST 2026-10-19다.

## 테스트 명령과 결과

```powershell
python .\tests\run_offline.py
python -m py_compile raw_v2/collector.py raw_v2/daily_scheduler.py raw_v2/audit.py raw_v2/backup.py raw_v2/recover.py raw_v2/verify.py tests/run_offline.py
git diff --check
```

Windows Python 3.11 전체 **93/93 PASS**: 기존 수집기28, 커서/콘텐츠25, scheduler20, recovery16, audit4. runner는 테스트 로드 후 socket connect/connect_ex/create_connection을 차단한다. 테스트의 `--live`는 주입한 합성 클라이언트만 사용한다. 실제 공식 294계정 dry run, PowerShell AST 구문 검사도 PASS.

초기 제한된 샌드박스 TEMP에서는 os.replace WinError5가 발생했다. 환경 제한은 테스트 실행 권한으로 분리 검증했고 제품 저장 로직을 우회하지 않았다. 이와 별개인 실제 SQLite 연결 미종료/WinError32는 코드·테스트에서 수정했다.

## 실행·중단·롤백

정확한 PowerShell의 **백업 → 진단 → dry run → 사용자 수동 한 배치 → 실행 후 진단**, 10월19일 bootstrap-history와 20일 이후 daily-front/history-only 명령은 [raw_v2/README.md](../raw_v2/README.md)를 따른다. 초기 시험은 `--once --max-batches 1`이다. `--once`만으로 한 배치가 되지 않는다.

자동 반복은 인증/권한/ID·소유권 충돌/사용량 근거 부재에서 종료한다. DB/원본 저장 오류도 전체 종료한다. #4/85%는 안전 중단과 최소 쿨타임을 적용한다. 원본 없는 unknown 요청과 requires_review 복구는 후속 수집을 차단한다. 어떤 대기값도 Meta 사용량 회복을 보장하지 않는다.

롤백: 이 검수 커밋을 `git revert <검수 커밋 SHA>`로 되돌리고 live를 중단한다. 로컬 DB/원본/관측/슬롯/백업은 삭제·복원·초기화하지 않는다. 추가 테이블은 구형 코드가 무시하지만 구형 코드의 확인된 결함 때문에 실수집을 재개하지 않는다. 운영 DB 복구는 별도 사용자 승인 대상이다.

미검증: 실제 Meta 연속 커서/한도/필드·권한, 1년 실제 커버리지, 무인 장기 실행, Windows legacy loop의 실 API 실행. project-book 대상/경로는 확인되지 않았다. GitHub 최종 SHA와 PR은 작업 완료 보고에서 재조회해 제공한다.
