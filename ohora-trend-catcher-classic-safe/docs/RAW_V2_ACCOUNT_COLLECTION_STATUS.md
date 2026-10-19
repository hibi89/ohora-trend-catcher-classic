# OHORA RAW v2.1 — 계정별 수집 현황표

## 운영 우선순위 (기존 스케줄러 정책 유지)
1. 공식 294계정의 KST 일일 최신 `front` 조회 및 조회 시점 반응·팔로워 관측값 누적
2. `catchup`으로 최신화 사이 누락된 구간 연결
3. 남은 API 여유로 기존 커서 기반 `history` 수집

과거 **6개월 이상**은 확보 목표이며 일일 최신화의 선행 조건이 아니다. 기존 365일 기준일·완료 판정·커서 정책을 변경하지 않는다. 과거 게시물의 반응값을 매일 모두 재조회하는 기능은 없다.

## 읽기 전용 실행 (Windows PowerShell)

수집 중인 창과 별도의 PowerShell에서, 저장소 루트 기준:

```powershell
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
$reports = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2_reports'
python .\raw_v2\account_collection_status.py --output-dir $out --report-dir $reports
```

출력 폴더 `account_status_YYYYMMDD_HHMMSS_microseconds`에 `account_collection_status.csv`와 `account_collection_status.md`가 생성된다. CSV는 UTF-8 BOM, ISO 8601 UTC 오프셋 시각이다. MD는 KST 표시다. 기존 폴더를 덮어쓰지 않는다.

SQLite는 `mode=ro`, `PRAGMA query_only=ON`, `BEGIN` 읽기 트랜잭션으로 접근한다. 원본 DB·커서·상태는 수정하지 않는다. DB/스키마가 없으면 실패한다. 인증파일, 네트워크, Meta API는 사용하지 않는다. **보고서는 자동수집과 연결하지 않았다.**

## 데이터 사전

| CSV 컬럼 | 뜻 / 판정 |
|---|---|
| account_key | 공식 계정 키 |
| country | 공식 입력 국가 |
| username | DB에 저장된 계정 사용자명 |
| unique_posts | `posts` 테이블의 고유 게시물 행 수 |
| oldest_post_at / newest_post_at | 저장된 게시물의 최소·최대 게시 시각. 연속 확보 보장 아님 |
| last_successful_front_at | `request_log`의 성공 `front` HTTP 200 종료 시각. 반환 0건도 성공으로 인정 |
| front_checked_today_kst | 보고서 기준 KST 날짜에 위 성공 기록이 있으면 yes, 과거 성공만 있으면 no, 성공 기록이 없으면 unknown |
| latest_gap_status | `catchup_cursor` 또는 대기 작업이 있으면 catchup_pending; 아니면 no_known_gap (완전성 증명 아님) |
| pending_catchup_jobs | `catchup_jobs`의 계정별 대기 건수 |
| history_status | not_started / in_progress / blocked_review / completion_flag_unverified / completion_chain_verified_raw_audit_required |
| history_evidence_status | 기존 `history_chain_status`의 rooted cursor 검증 결과. 원본 JSON 대조는 별도 audit 필요 |
| last_attempt_at | 최신 요청 시작 시각; 요청 로그가 없으면 계정 last_attempt |
| last_error_code / last_error_reason | 최신 요청의 오류 정보, DB에 남은 계정 오류 문구. 없으면 빈값 |
| report_as_of | 보고서 생성 기준 시각 |

시각이 확인되지 않으면 CSV는 빈칸, MD는 미확인으로 표시한다. 모든 계정은 게시물 0건이어도 출력된다. 수집 실패 계정도 제외하지 않는다.

## 증거의 한계

- `backfill_done=1`만으로 완료 처리하지 않는다.
- `completion_chain_verified_raw_audit_required`는 커서 체인만 확인됐다는 뜻이다. 원본 JSON의 일치까지 입증하는 전체 `audit.py` 검사를 대체하지 않는다.
- 최신 `front` 성공과 `catchup` 완료는 서로 다른 상태다.
- 계정별 최소·최대 게시일만으로 6개월 확보율을 계산하지 않는다.
- 운영 DB에서 294행 및 대표 계정 결과를 확인하는 검증은 사용자 Windows에서 별도 수행해야 한다.

## 검증

```powershell
python -m unittest discover -s tests -p 'test_account_collection_status.py' -v
python .\tests\run_offline.py
python .\raw_v2\audit.py --output-dir $out
```

위 명령은 실제 API 호출을 하지 않는다. 마지막 명령은 기존 운영 감사이며 보고서 생성에는 필수가 아니다.
