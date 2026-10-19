# OHORA — 두 개 이상 Meta 앱, 계정당 최근 10개 수동 수집

## 핵심 설계

- 공식 `account_list.csv` 첫 294계정은 그대로 보존한다. **행 번호**가 기준이다: Haein 담당 1–150(150계정), Hongju 담당 151–294(144계정). 300개가 아님.
- `--capacity 150`은 사용자 프로젝트가 정한 계정 할당 숫자이며 **Meta 공식 할당량이 아님**. 별도 로그인이나 서로 다른 토큰만으로 독립적 한도 또는 승인된 사용 권한을 증명하지 못한다.
- 앱당 별도의, 정상 승인받은 Meta 앱/Instagram professional 소스/토큰이 필요하다. 두 앱의 계정 조회 권한과 Instagram Business Discovery 이용 조건을 Meta 개발자 도구에서 확인하자.
- 각 앱은 **별도 SQLite·CSV·checkpoint**로 저장. Batch 최대 10계정 × 계정당 최대 게시물 10개(캐러셀 미디어 별도 행). `--live`가 없으면 아무 API 요청/출력이 없다. 예약 실행·자동 리트라이는 아직 없다.
- 기존 `experiments/results/latest_5`와 `latest_1_pending`은 변경하지 않는다. 아래 실행은 완전히 새로운 `dual_app_latest10` 디렉터리만 사용한다.

## 0. 학원 도착 후 GitHub 업데이트, 오프라인 테스트

```powershell
git pull origin main
python -m unittest discover -s experiments -p test_full_batch_collector.py -v
python -m unittest discover -s experiments -p test_two_app_runner.py -v
python -m unittest discover -s delivery -p test_build_hongju_bundle.py -v
```

예상 테스트 19 + 14 + 15 = **48개**. 새 두 앱 수집 코드는 GitHub에 올렸지만 **사용자 PC 실환경 검증은 아직 필요**하다. 모두 OK인 경우에만 `--live` 사용.

## 1. 앱 두 개의 로컬 자격정보 준비

프로젝트 루트 PowerShell:

```powershell
$src = '..\2차 프로젝트 홍주님께 제공할 수집데이터\account_list.csv'
$myEnv = '..\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection\.env.local'
$hongjuEnv = '..\2차 프로젝트 홍주님께 제공할 수집데이터\meta_hongju.env.local'
Test-Path $src
Test-Path $myEnv
Test-Path $hongjuEnv
```

앞의 둘은 과거 성공 경로다. 세 번째는 **새 예시 경로**이므로 홍주님이 승인한 토큰을 별도 파일에 저장해야 `True`가 된다. 토큰 값을 ChatGPT나 GitHub에 업로드하지 말 것. env 파일은 아래 항목:

```text
META_ACCESS_TOKEN=본인만_보관하는_액세스_토큰
META_IG_USER_ID=그_앱의_프로페셔널_인스타그램_사용자_ID
META_GRAPH_VERSION=v26.0
META_APP_ID=해당_앱_ID
```

`META_APP_ID`를 두 파일 모두 적는 걸 권장한다. 두 파일에 같은 토큰 또는 같은 선언된 앱 ID가 있으면 코드가 멈춘다. 그러나 **서로 다른 문자열이라고 한도가 독립적인 것은 아님**. Meta 개발자 대시보드에서 권한·앱 연결을 검증할 것. 두 env 파일 모두 외부로 공유하지 말 것.

## 2. 호출 없는 사전 계획 검토

```powershell
python .\experiments\two_app_runner.py `
  --source $src `
  --app "haein=$myEnv" `
  --app "hongju=$hongjuEnv" `
  --posts 10 `
  --capacity 150
```

예상 행 범위: haein **1..150**, hongju **151..294**. HTTP Batch는 각각 약 15번이지만 내부 하위 API 요청은 대략 150회와 144회이며, 서버 처리 시간도 별도 소모된다. 오프라인 미리보기에는 환경변수/토큰 노출과 API 호출이 없다.

## 3. 권장: 우선 각각 10계정 실측

Meta 대시보드에서 두 앱의 현재 사용량 및 접근 권한을 확인한 다음:

```powershell
python .\experiments\two_app_runner.py `
  --source $src `
  --app "haein=$myEnv" `
  --app "hongju=$hongjuEnv" `
  --posts 10 `
  --capacity 150 `
  --batch-size 10 `
  --max-batches-per-app 1 `
  --stop-usage 70 `
  --live
```

앱마다 최대 10계정(각 10개 게시물) 1배치만 진행한다. Meta `total_time`의 변화를 확인하고 다음 진행 여부를 결정할 것. **70% 안전선은 배치 완료 뒤 평가**되므로, 70%를 넘지 않는다는 보증은 아니다. Meta 응답에 사용량 헤더가 누락되거나 인증/제한 오류가 있으면 현재 앱을 즉시 멈추고 다음 앱도 자동 실행하지 않는다. 예전에 79%로 보였던 본인 앱이 회복되지 않았다면 시험부터 기다려야 한다.

## 4. 실측 이후 두 앱 범위 전량 이어받기 (수동)

3단계에서 사용한 명령에서 **`--max-batches-per-app 1`만 제거**하고 실행한다. `--stop-usage 70`은 그대로 둔다. 이때 이전 성공 계정은 DB에서 건너뛰므로 앱별 남은 계정만 이어서 수집한다. Meta 제한이나 중단 오류가 있으면 원본 데이터를 보존한 채 멈춘다. 고정된 시간(예: 5분 완료, 50~60분 휴식 후 복구)은 보장되지 않는다.

본인 앱 사용량 제한에 먼저 걸렸고 홍주님 앱만 별도로 호출 가능하다면 동일 명령에 `--only-app hongju`를 추가하면 된다. **범위 배정은 그대로 151..294를 유지**하며, 본인 앱을 우회 호출하지 않는다. 반대로 본인 앱만은 `--only-app haein`.

### 결과 데이터 위치

```text
experiments/results/dual_app_latest10/
  haein/collection.sqlite, posts.csv, media.csv, summary.json, collection_status.csv
  hongju/collection.sqlite, posts.csv, media.csv, summary.json, collection_status.csv
```

두 DB는 한 번 수집 후 자동 재시도하지 않는다. 실패한 계정은 `collection_status.csv`에서 구체적 오류를 확인한 뒤 검토한다. 완료한 계정은 재실행해도 중복 호출하지 않는다.

## 5. 두 앱의 데이터를 홍주님 전달용 ZIP 하나로 합치기

두 앱의 결과가 있는 상태에서, 전부가 완료되지 않아도 부분 스냅샷으로 생성할 수 있다.

```powershell
python .\delivery\build_hongju_bundle.py `
  --source '.\experiments\results\dual_app_latest10\haein' `
  --supplement '.\experiments\results\dual_app_latest10\hongju' `
  --output-dir '.\experiments\results\hongju_delivery'
```

`accounts.csv`의 `collection_source`는 `primary`/`supplement`로 수집 출처가 구분된다. `account_coverage.csv`/`manifest.json`에서 국가별 성공·미수집·오류 수를 확인해야 한다. 어떤 ZIP도 자동으로 294계정 완수라고 표기하지 않는다. 파일과 데이터베이스는 읽기 전용으로 유지한다.

## 6. 계정 수 증가

`account_list.csv`에 기존 294개 행을 **수정·재정렬하지 않고 아래에 추가**하면 수집 DB는 새 행만 `pending`으로 등록한다. 추가 범위 규칙:

- 295..300: 기존 홍주님 앱 슬롯 151..300에 자동 귀속(최대 6계정 추가).
- 301..450: 제3 Meta 앱과 유효한 권한을 확보하고 `--app "third=$thirdEnv"`를 세 번째로 추가해야 새 계정에 배정된다.
- 451..600: 네 번째 앱 필요. 무제한 앱 생성이나 제한 우회는 정책 검토 없이 가정하지 않음.
- 이미 저장한 DB의 `--capacity`나 앱 순서를 변경하면 명시적으로 오류가 발생한다. 수집 범위 이동은 별도 승인된 이관 작업으로 진행할 것.

검증 전제: 앱별 `META_APP_ID`, 실제 토큰과 접근 가능한 IG 계정, 수집 대상과 목적이 Meta 약관상 허용되는지, 두 앱이 독립 quota를 갖는지는 Meta 대시보드에서 개별 확인이 필요하다.
