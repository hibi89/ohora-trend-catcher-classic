# OHORA Trend Catcher — Instagram 데이터 수집 및 트렌드 분석

> **최신 상태: 2026-10-19 (사용자 Windows 로컬 실행 결과)**  
> 이 README는 프로젝트의 **현재 운영 상태와 진입점**을 설명한다. 과거 설계·실험 문서는 아래의 아카이브 링크로 구분한다. GitHub에 실수집 DB나 인증정보는 저장하지 않는다.

## 프로젝트 개요

OHORA 네일 디자인 트렌드 탐지 프로젝트. 한국·미국·일본 인스타그램 계정의 공개/권한 내 데이터를 Meta Graph API Business Discovery로 수집하고, 향후 이미지·캡션 분류, 국가·기간별 디자인 비교, 대시보드/리포트에 연결하는 것이 목표다.

**현재 검증된 것은 RAW v2.1 수집·감사 파이프라인**이다. AI 디자인 분류 정확도, 최종 대시보드의 실사용 품질, 365일 전체 게시물 확보, 무인 운영은 별도로 검증해야 한다.

## 현재 운영 스냅샷

| 항목 | 결과 | 판정 |
|---|---:|---|
| 학원 공식 대상 계정 | 294 (KR100 / US101 / JP93) | 공식 원본 |
| 수집 성공 계정 | 286 | 사용자 실수집 로그 |
| Meta 조회 실패/차단 | 8 | `last_error=110` |
| 누적 고유 게시물 | 1,330 | 마지막 사용자 감사 |
| 누적 게시물 관측 | 1,350 | 동일 게시물 재관측 포함 |
| 미해결 API 배치 | 0 | 마지막 사용자 감사 |
| 감사: integrity / observation / coverage | 0 / 0 / 0 | **PASS**, 측정 항목 한정 |
| 지정 10계정 History 실수집 | 10/10 HTTP 200, 신규 40 | 성공 |
| 무인 자동수집 | 미승인 | `ready_for_unattended_collection=false` |
| Meta-visible 365일 완전성 | 미검증 | PASS와 별개 |
| 팀 전달용 최종 통합 패키지 | 미검증 | 별도 인수 필요 |

마지막 성공 run: `20261018T192326Z_24616_e7638fda` (UTC ID). 마지막 사용자 감사: `2026-10-18T19:23:49.568097+00:00`. 위 수치는 **그 시점의 로컬 운영 DB**에서 확인된 것으로, GitHub 최신 커밋만으로 재현되는 데이터가 아니다.

### 현재 확인된 오류 8계정

`KR_032`, `KR_061`, `KR_100`, `US_013`, `US_052`, `US_101`, `JP_009`, `JP_093`.

모두 DB상 Meta `110`. **JP_093**은 원본에서 `Invalid user id / 2207013 / is_transient=false`와 해당 인스타그램 URL 접근 불가를 확인했다. 나머지 7개는 원본 세부 사유 분류가 남아 있다. 이들을 정상 수집 계정으로 계산하거나 무조건 삭제 계정이라고 단정하지 않는다.

## 먼저 읽을 문서

1. **[전체 트러블슈팅 연대기](docs/RAW_V2_2026-10-19_TROUBLESHOOTING_CHRONICLE.md)** — 수집·쿨타임·인증·커서·History 복구·오류 110·감사 결과의 실제 해결 과정
2. **[오류 분류 및 대응 SOP](docs/RAW_V2_ERROR_HANDLING_RUNBOOK.md)** — 오류별 중단/재시도/원본 보존/백업/복구/읽기 전용 진단
3. **[향후 과제 및 인수 기준](docs/RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md)** — 우선순위 T01~T11, 팀 데이터 전달, 7계정 세부 조사, History coverage, 무인 승인
4. **[RAW v2.1 실행·안전 가이드](raw_v2/README.md)** — Windows 명령, 인증/경로, 제한 실행, 감사, 백업
5. **[안전성 검수 보고서](docs/RAW_V2_REVIEW_2026-10-19.md)** · **[인수인계](HANDOFF.md)** · **[상세 이력](STATUS.md)** — 과거 검수 시점의 수치와 이후 운영 로그를 날짜로 구분

## 현재 코드 구성

| 경로 | 용도 |
|---|---|
| `raw_v2/collector.py` | Meta Graph Batch API, front/catchup/history 수집, 원본 JSON·SQLite·로그·커서 영속화 |
| `raw_v2/daily_scheduler.py` | 당일 최신화 우선 정책, 대상 선택, 슬롯·쿨타임 관리 |
| `raw_v2/audit.py` | 운영 DB/관측/History 증거 감사 (**API 호출 없음**) |
| `raw_v2/verify.py` | 실행별 manifest SHA·CSV 건수·기본 DB 무결성 검사 |
| `raw_v2/backup.py` | SQLite 일관 스냅샷 및 검증; **run/raw JSON은 별도 보관** |
| `raw_v2/recover.py` | 미해결 배치의 오프라인 preview; `--apply`는 별도 승인 대상 |
| `tests/run_offline.py` | 외부 API 호출 없는 회귀 테스트 (기존 Windows 93/93 PASS 기록) |
| `vision/` | 이미지+캡션 분류 계층의 별도 개발 자산; 운영 수집 검증과 혼동 금지 |
| `delivery/` | 기존 팀 전달용 도구/기록; **현재 1,330건 기준 최종 인수 패키지 검증과 별개** |
| `experiments/`, `kq3_294_collection/` | 과거 실험·레거시 수집기. RAW v2.1 운영 진입점으로 사용하지 말 것 |

## 운영 정책과 데이터 위치

- 공식 계정 CSV: 로컬 학원 제공 **294행**(KR100/US101/JP93), 해시·순서·계정키 불변. 원본을 GitHub에 올리거나 임의로 변경하지 않는다.
- 인증: 로컬 `.env.local`의 `META_ACCESS_TOKEN`, `META_IG_USER_ID`, 선택 `META_GRAPH_VERSION`. GitHub에 토큰·인증파일을 저장하지 않는다.
- 운영 DB: `%LOCALAPPDATA%\OHORA_RAW_v2\collection.sqlite`; 원본은 같은 출력 폴더의 `runs/<run_id>/raw/`.
- 권장 실행기: `raw_v2/daily_scheduler.py`. **front → catchup → history**, 일일 최신화 우선.
- 배치 5 하위요청, 기본 4개 게시물/계정, 슬롯당 **서로 다른 계정 최대 150**, 사용량 최대 관측값 **85%** 도달 시 후속 배치 중단.
- 대기: `max(슬롯 종료+63분, 슬롯 시작+65분, 저장된 ready_at)`. **로컬 대기는 Meta 쿼터 회복의 보증이 아니다.**
- `--once`는 한 번의 실행이며 **한 배치가 아니다**. 단일 배치 실험은 `--once --max-batches 1`.
- `--live` 없는 명령은 실제 API 호출이 아니다. 무인 예약 작업은 설치·승인되지 않았다.
- History 완료 플래그는 실제 원본·root cursor chain·cutoff 증거와 함께 검증한다. `audit PASS`는 Meta에 보이는 전체 게시물의 완전성을 보증하지 않는다.

### Windows: 안전한 읽기 전용 확인

저장소 루트에서 실행. 아래는 **Meta API를 호출하지 않는다.**

```powershell
$out = Join-Path $env:LOCALAPPDATA 'OHORA_RAW_v2'
python .\tests\run_offline.py
python .\raw_v2\audit.py --output-dir $out
python .\raw_v2\recover.py --output-dir $out
python .\raw_v2\verify.py --output-dir $out --run-id 20261018T192326Z_24616_e7638fda
```

**실수집 전에:** 로컬 공식 CSV와 인증파일의 존재, 운영 DB 위치, 현재 `slots.ready_at`, Meta 사용량, 미해결 배치, 당일 front 우선 조건을 확인한다. `audit FAIL` 또는 미해결 배치면 새 `--live` 금지. 실호출은 사용자 명시 승인과 제한된 대상·횟수·사후 감사가 필요하다. 실제 인자/사전 검증 절차는 [실행 가이드](raw_v2/README.md) 참고.

## 다음 작업

**즉시:** (1) 현재 SQLite와 `runs/raw` 전체를 각각 백업하고 해시 고정, (2) Meta 110 나머지 7개 원본 세부 오류 분류, (3) 팀 전달용 CSV/JSON·스키마·SHA 패키지 검증.

**후속:** (4) 한 계정만 안전하게 재조회하는 격리 기능과 합성 테스트, (5) 실제 365일 History coverage 및 누락/좋아요/캐러셀 품질 검증, (6) 반복 운영 테스트·무인 승인, (7) AI 디자인 분류와 대시보드 통합. [세부 작업·합격 기준](docs/RAW_V2_NEXT_TASKS_AND_ACCEPTANCE.md).

## 과거 설계와 레거시 아카이브

다음 자료는 **개발 당시 계획·실험**이며 현행 수집 명령이나 최신 수치가 아니다. 기록 보존을 위해 유지한다.

- [요구사항](REQUIREMENTS.md) · [AI 작업 안전 지침](AGENTS.md) · [초기 RAW 수집 요청](docs/OHORA_RAW_COLLECTION_EXECUTION.md)
- [장기 RAW 수집·대시보드 구상](docs/LONG_TERM_RAW_COLLECTION_VISION_2026-10-18.md) · [V1 로드맵](docs/V1_DELIVERY_ROADMAP.md) · [증분 V1 구상](docs/INCREMENTAL_V1_ARCHITECTURE.md)
- [구형 2앱/150+144 계정 실험](experiments/README_TWO_APP_LATEST10.md) · [구형 90분 cursor 설계](experiments/README_CURSOR_BACKFILL_90M.md) · [초기 전달 가이드](delivery/README.md)

이전 문서에 남은 “실수집 미실행”, “70분”, “90분”, “최대 5개/계정”, “게시물 1,178건” 등은 **해당 작성 시점의 설명**이다. **현재 RAW v2.1의 정책과 마지막 사용자 운영 로그는 이 README 및 위 운영 문서를 우선한다.** 새 운영 수치가 확인되면 날짜·run ID·audit 결과를 함께 갱신한다.
