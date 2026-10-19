# OHORA RAW v2.1 — 오프라인 인수·복구 절차 (2026-10-19)

## 목적과 우선순위
- 목표는 가능하면 최근 1년치 게시물을 확보하는 것이지만, **최신 관측을 지속적으로 누적하고 시간별 트렌드 변화를 발견하는 것이 핵심 가치**다.
- 실행 정책 기본값은 `daily`: 당일 front → catchup → history. `history-only`를 상시 기본값으로 사용하지 않는다.
- Meta 쿨타임을 해제하거나 DB의 상태·커서를 수동 변경하지 않는다.
- 이 문서는 **오프라인 검증 및 운영 인수 문서**이며, 실수집 또는 자동 스케줄러 설치를 수행하지 않는다.

## 현재 확인된 수치
- 공식 계정 294 / 최신 수집 성공 286 / 차단 8.
- 게시물 1,270개, 관측 1,290건, 미디어 3,396건.
- 원본 대 DB 게시물/관측 비교 PASS; 미디어/캐러셀 비교 PASS (자식 2,715개, 오류 0, 경고 0).
- 10계정의 과거 완료 플래그는 증거 체인이 없어 경고 중. 10/10 Front 원본의 `paging.cursors.after`가 현재 `backfill_cursor`와 일치함을 읽기 전용 검사로 확인했으나 **증거 복구 완료를 뜻하지 않는다**.
- History 5계정 실제 시험은 쿨타임으로 실행되지 않음. 1년치 History 완결성은 미확인.

## 증거 복구 — 검증 및 안전조건
대상: KR_055, KR_078, US_019, US_022, US_023, US_059, US_072, US_075, JP_055, JP_061.

1. DB를 백업하고 원본 runs/raw JSON도 별도 보존한다.
2. 성공한 Front 요청의 `request_id`, `account_key`, `phase`, 원본 파일 경로와 요청·응답 기록을 교차검증한다.
3. 원본 `business_discovery.media.data`의 타임스탬프 존재, 내림차순, 페이지 커서와 현재 체크포인트의 일치를 검증한다.
4. 증거 테이블의 해당 `request_id` 중복 여부와 다른 History 증거 연결 여부를 확인한다.
5. **원본을 재구성한 증거가 충분한 경우에만** 별도 리뷰·백업·트랜잭션 기반 마이그레이션을 설계한다. 불일치 시 복구하지 않는다.
6. 이 마이그레이션은 아직 구현·실행되지 않았다. `backfill_done` 또는 `backfill_cursor`를 단순히 수정하여 PASS를 만드는 행위는 금지한다.
7. 수집 완료 여부는 `collector.history_chain_status` 및 `audit.py`로 재검증한다.

## 오프라인 최종 감사
PowerShell, 저장소 루트에서:
```powershell
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
$report = Join-Path $env:LOCALAPPDATA 'OHORA_AUDIT_REPORTS\final_review'
python .\raw_v2\audit.py --output-dir $out --report-dir $report
Write-Host "AUDIT_EXIT_CODE: $LASTEXITCODE"
```
**주의:** `audit.py`는 WARN이어도 종료 코드 0이다. `summary.json`의 `status`와 `findings`를 반드시 확인한다. 보고서 경로는 수집 저장소 외부여야 한다. `ready_for_unattended_collection=false`는 자동운영 승인 아님을 뜻한다.

## 실제 수집 이후 인수 기준
- `daily` 정책에서 최신 수집이 History보다 우선되는지 확인.
- 실제 5계정 History 한 배치의 요청·원본·DB·커서 증거를 비교.
- 감사 `integrity=0`, `observation=0`; `coverage` 경고는 미해결로 명시.
- 8개 차단 계정과 10개 과거 증거 미검증 계정을 별도로 추적.
- 자동 실행 설치/무인 수집은 별도 검증과 승인 후 진행.

## 판정
- **완료:** 최신 286계정 수집 및 현재 저장 원본·DB 교차검증, 오프라인 인수 절차 문서화.
- **미완료:** History 실제 5계정 시험, 10계정 증거 복구, 1년치 완결성, 자동 무인운영 검증.
