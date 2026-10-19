# OHORA — 294계정 전수 Meta Batch 실험

목적: 공식 `account_list.csv`의 **전체 294개 계정을 1번부터 순서대로** 조회하면서 Meta Graph API Batch의 소요 시간, 데이터 수집 성공률, `X-App-Usage` 사용량, 최초 제한 오류 위치를 실측한다. 기존 94개 성공 계정을 포함해 **이번 실험 전용 데이터베이스는 처음부터 별도로 생성**한다.

## 기존 데이터 보호

- 기존 `kq3_294_collection/collector.py`, CSV, 인증정보를 읽거나 수정하지 않는다. 원본 계정 목록은 입력으로만 읽는다.
- 실험 결과는 Git에서 무시되는 `experiments/results/full_294/`에만 저장한다.
- 기본 동작은 드라이런이다. `--live`를 붙이기 전까지 **Meta 호출이나 파일 생성이 없다.**
- 실제 실행하면 계정당 **최근 게시물 최대 20건**, 배치당 **10계정**, 정상적으로 모두 응답할 때 총 **30회 HTTP POST / 294개 하위 조회**다.
- 각 배치가 끝날 때마다 SQLite 트랜잭션으로 데이터를 확정한 뒤 CSV를 내보낸다. 재실행 시 `success`/`partial`/`failed`는 재호출하지 않고 `pending`/`rate_limited`만 순서대로 선택한다.
- API 사용률 `total_time`은 **응답 시점의 누적 스냅샷**이며 각 항목을 합산하지 않는다. 기본 설정은 인위적인 80% 조기 중단 없이 Meta의 실제 제한을 관측한다. `#4`, `#17`, `#32`, `#613`, 인증/권한 오류 또는 HTTP 429 등으로 판단되면 해당 배치 결과까지 저장하고 더 이상 호출하지 않는다.
- 한 배치 안에서 여러 하위 요청이 실패하더라도 성공한 계정의 결과는 보존한다. 전송 실패나 배치 응답 형식 오류 시 자동 재시도하지 않는다.
- 실험용 인증 토큰은 기존 로컬 `.env.local`에서만 읽고 코드·Git·리포트에 저장하지 않는다.

## 실행 — Windows PowerShell

GitHub 저장소를 이미 Clone한 컴퓨터에서:

```powershell
$BASE = "C:\Users\haein\OneDrive\Desktop\2차 프로젝트 아카이브"
$SOURCE = "$BASE\2차 프로젝트 홍주님께 제공할 수집데이터\account_list.csv"
$ENVFILE = "$BASE\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection\.env.local"
cd "$BASE\ohora-trend-catcher"
git pull origin main

# 1. 인증/API 요청 없는 사전 검사
python .\experiments\full_batch_collector.py --source "$SOURCE"

# 2. 294개를 처음부터 배치 수집 (실제 Meta API 호출 최대 30개 배치)
python .\experiments\full_batch_collector.py --source "$SOURCE" --env-file "$ENVFILE" --live
```

동일한 명령으로 **중단 후 재개**한다. 성공 계정을 다시 조회하지 않는다. 기존 Meta 수집 프로세스가 동시에 실행되지 않도록 종료하고 수행한다.

안전 중단을 선택하려면 `--stop-usage 80`을 추가한다. 한 배치가 요청된 뒤 응답에서 80% 이상이 관측될 때만 멈추므로 선제적 보장은 아니다. 성능 비교만 원하면 `--max-batches 1`을 추가해 최초 배치까지만 실행할 수 있다. 이 경우에도 같은 출력 폴더에 재실행하면 이어서 진행한다. 기본 배치 간 지연은 1초이며 `--delay-seconds`로 변경할 수 있다.

## 실험 저장물

모두 `experiments/results/full_294/` 안에 생성된다.

| 파일 | 내용 |
|---|---|
| `collection.sqlite` | 복구/재개 기준이 되는 트랜잭션 DB |
| `accounts.csv` | 공식 294개 계정 정보, 수집 상태, 팔로워 등 |
| `posts.csv` | 게시물 ID·본문·게시 시각·좋아요/댓글·URL |
| `media.csv` | 단일 이미지·영상 썸네일·캐러셀 각 장의 URL/관계 |
| `collection_status.csv` | 1~294번 처리 여부, 오류 코드/HTTP 응답, 배치 번호 |
| `batch_log.csv` | 각 배치 시간, 성공/실패 수, 제한 여부 및 앱 사용량 스냅샷 |
| `summary.json` | 마지막 저장 시점의 전체 상태 요약 |

`like_count` 누락은 빈 값(NULL)으로 유지하며 **0으로 치환하지 않는다.** `coverage=partial`은 반환된 게시물이 20개보다 적고 계정의 총 게시물 수 등으로 추가 데이터 가능성이 확인되거나 캐러셀 구성 누락이 있는 경우다. `partial`, 기타 계정별 실패는 자동으로 재요청하지 않으며 추후 원인 분석 뒤 별도 정책으로 처리한다.

현재는 **메타데이터와 이미지 URL만 저장**한다. 사진·동영상 원본 다운로드, AI 디자인 분류, 대시보드 반영은 이 실험에 포함되지 않는다. URL은 Meta의 정책에 따라 만료될 수 있다. 294개 조회가 완료되어도 게시물/좋아요/이미지 필드가 모두 완전하다는 의미는 아니다.

## 오프라인 검증

```powershell
python -m unittest discover -s experiments -p "test_full_batch_collector.py" -v
```

오프라인에서만 실제 API 결과처럼 가짜 응답을 만들어 테스트한다. `--live` 없이 Meta API를 호출하지 않는다.

### 종료 코드

- `0`: 대상 계정 모두 성공 (미확인/미수집 없음)
- `1`: 전수 시도를 마쳤지만 계정별 실패·부분 수집·미수집이 남음, 또는 `--max-batches`로 일시 중단
- `2`: 입력/환경/파일/DB 설정 문제
- `3`: 전송 오류 후 자동 재요청하지 않고 중단
- `4`: Meta 제한·권한 오류 또는 해석할 수 없는 배치 응답으로 중단
- `5`: 사용자가 설정한 `--stop-usage` 사용률 기준 도달

실험 종료 또는 제한 발생 후에는 `summary.json`, `batch_log.csv`, `collection_status.csv`를 확인한다. 계정 이름·토큰이 포함될 수 있는 원본 파일을 공유하기 전 데이터 취급 권한을 확인한다. 통계나 오류 정보만 공유해도 성능 판정이 가능하다.
