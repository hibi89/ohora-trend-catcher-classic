# OHORA — 홍주님 데이터 전달 우선 작업 (2026-10-16 금요일)

**목표:** 학원 종료 전에 홍주님께 우선 수집 결과를 전달한다. 반복 누적 DB(P1)는 이 인계 이후 개발한다. 현재 294계정의 최신 5개 수집 성공은 확인되지 않았고, Meta code 4 rate limit이 있었다. **계정 전체 수집 완료로 보고하거나 광고/구매 전환 정보라고 소개하지 않는다.**

## 1) 아침에 GitHub 업데이트 및 오프라인 테스트

PowerShell에서 OHORA 프로젝트 루트로 이동 후:

    git pull origin main
    python -m unittest discover -s delivery -p test_build_hongju_bundle.py -v

9개 오프라인 단위 테스트가 OK이면 다음으로 진행한다. 이 테스트는 Meta, Gemini, Sol API에 접속하지 않고 사용료도 발생하지 않는다.

## 2) 데이터 소스 결정

**1순위:** 사용자의 최근 5개 실험 결과인 experiments/results/latest_5/collection.sqlite. 실제 성공 계정이 있는지 같은 폴더의 summary.json 및 collection_status.csv에서 확인. 이전에 이 실험은 code 4 때문에 처음 10개 시도에서도 0건 성공했으므로 0건이라면 이 소스는 전달하지 않는다.

**2순위(오늘 반드시 확보 가능한 대안):** 이전에 이미 수집한 원본 kq3_294_collection/의 accounts.csv, posts.csv, media.csv. 사용자가 이전에 확인한 결과는 약 94개 계정 성공, 1,880개 게시물, 5,307개 미디어 행. 이 수치는 이전 실행 시점의 관측값이지 본 ZIP의 검증된 최신 수치가 아니므로, ZIP에 생성되는 manifest의 계정 수를 최종 확인한다.

**3순위:** experiments/results/full_294/collection.sqlite — 20개/계정 전수 배치 실험으로 이전 성공 계정 77개가 저장돼 있음. 원본보다 계정 커버리지가 작은 경우 우선하지 않는다.

원본 CSV가 repo 폴더가 아니라 형제 폴더에 있다면 해당 폴더 경로를 --source에 지정한다. 원본 데이터/계정 목록/API 토큰은 GitHub에 절대 업로드하지 않는다.

## 3) 이미 보유한 데이터로 전달 ZIP 생성 (API 호출 없음)

예시 A — 20개 배치 실험 데이터로 ZIP 생성:

    python .\delivery\build_hongju_bundle.py --source ".\experiments\results\full_294" --output-dir ".\experiments\results\hongju_delivery"

예시 B — 실제 기존 CSV 폴더가 프로젝트 형제 폴더에 있다면 (경로의 파일 존재 여부 먼저 확인):

    $src = "..\2차 프로젝트 홍주님께 제공할 수집데이터\kq3_294_collection"
    Test-Path "$src\posts.csv"
    python .\delivery\build_hongju_bundle.py --source "$src" --output-dir ".\experiments\results\hongju_delivery"

예시 C — 새로 성공한 294계정 최신 5개 데이터가 있다면:

    python .\delivery\build_hongju_bundle.py --source ".\experiments\results\latest_5" --output-dir ".\experiments\results\hongju_delivery"

만든 ZIP 파일은 experiments/results/hongju_delivery/OHORA_Hongju_handoff_YYYYMMDD_HHMMSS.zip이며 Git에서 무시되는 results 폴더에 보관한다. ZIP만 홍주님께 전달하면 된다. 스크립트가 표시한 covered_accounts 수를 반드시 확인한다.

## 4) ZIP 구성 및 주의사항

- posts_latest5_per_account.csv: 해당 수집본에 실제 있는 게시물 가운데 계정별 최신 5개를 선택. 계정이 누락되면 0개. 요청한 날짜 범위의 전체 게시물을 보증하지 않는다.
- posts_all_available.csv: 현재 소스에 저장된 모든 게시물. 과거 분석이나 표본 수 확보에 유용.
- media_latest5_per_account.csv / media_all_available.csv: 원본 이미지·동영상 썸네일 URL과 캐러셀 매핑. 미디어 URL은 만료되므로 영구 다운로드 파일이 아니다.
- accounts.csv: 계정별 당시 팔로워 수와 상태 등. NULL-like empty like/comment는 0으로 바꾸지 않는다.
- account_coverage.csv: 각 계정의 최근5 확보건수·전체확보건수·결측·상태.
- manifest.json: 계정/게시물/국가별 확인된 수치.
- README_데이터안내.txt: 사용하는 방법과 한계. 표기한 계정 수가 **294라도** covered_accounts가 294라는 의미는 아니다.

게시물 ID는 Excel에서 **텍스트 열로 가져오기**를 선택해 자리수가 잘리지 않도록 한다. 전달본에서는 위험한 수식 시작 캡션에 작은따옴표를 붙여 스프레드시트 수식 실행을 막는다. 원본 데이터는 그대로 유지한다.

## 5) 새 294계정 최신 5개 API 수집 — 사용량 회복 확인 후만 수행

코드는 experiments/full_batch_collector.py에 이미 있다. **오늘 새로 구현할 필요는 없다.** 이것은 기존 결과를 건드리지 않는 별도 실험 수집이다.

1. experiments/results/latest_5/summary.json에서 현재 성공, rate_limited 계정과 마지막 usage를 먼저 본다.
2. Meta app usage가 실제로 회복되었다는 근거가 있을 때만 사용자 PC에서 --source 공식 account_list.csv, --posts 5, --output-dir experiments/results/latest_5, --max-batches 1, --stop-usage 70, --live 설정으로 **최초 1배치만** 확인.
3. 10개 성공과 사용량이 안전한 것으로 검증되면 동일 옵션에서 --max-batches 1을 제거해 남은 계정 계속 수집(기존 성공한 계정은 스킵).
4. code 4/HTTP 403이면 **즉시 중지**. 오래된 원본 데이터를 부분 데이터임을 명시해 전달하고 P1 개발은 그다음에 진행한다.

**API 호출은 이 문서가 자동으로 수행하지 않으며, 실제 수집 전 사용자가 명시적으로 명령을 실행해야 한다.** 재사용 가능한 Meta quota가 없으면 294계정 성공은 약속할 수 없다.

## 6) 전달 전 최소 검수

- ZIP 목록에 실제 posts_latest5_per_account.csv와 manifest.json이 있으며 .env.local, API 키, batch 원본 응답 로그가 없는지 확인한다.
- manifest의 source_accounts, accounts_with_posts, latest_post_rows, 국가별 covered_accounts 수를 전달 문구에 반영한다.
- 홍주님께는 '*오늘 전달 데이터는 전체 계정 목록 중 N계정에서 확보한 M개 게시물이며, 미확보 계정 및 좋아요 결측은 별도 표시했습니다*'라고 정확하게 안내한다.

## 7) 2026-10-16 — 5개 + 1개 실험 결과를 한 번에 전달

실측: 기존 latest_5 DB는 성공 176계정/880게시물. 별도 latest_1_pending DB는 원래 미수집 대상 중 성공 15계정/15게시물. 두 자료를 합치면 191계정/895게시물이며, 오류 110은 5계정, 미수집은 98계정이다. 이것은 전체 294계정 전수 수집이 아니다.

최신 코드가 추가된 뒤 Windows PowerShell에서:

    git pull origin main
    python -m unittest discover -s delivery -p test_build_hongju_bundle.py -v

**기존 9개에서 6개 추가한 15개 테스트가 OK일 때만** 실제 병합 ZIP을 만든다. 두 원본 데이터베이스는 읽기 전용이며, 서로 다른 계정이 성공했는지 확인 후 안전하게 메모리에서만 합쳐 ZIP을 생성한다.

    python .\delivery\build_hongju_bundle.py `
      --source ".\experiments\results\latest_5" `
      --supplement ".\experiments\results\latest_1_pending" `
      --output-dir ".\experiments\results\hongju_delivery"

**예상 결과:** 5개 방식 재수집 *전*이라면 `Source accounts=294, covered_accounts=191, source_posts=895, recent_posts=895`. 10계정×5개 성공 *후*에는 `source_posts=935`, `recent_posts=935` 예상. 실제 출력으로 판단하고 실패·미수집 98개를 구분한다. 결과가 다르면 원본 DB 상태를 비교한다. 생성 ZIP은 타임스탬프가 붙으므로 기존 175계정 ZIP은 자동 덮어쓰지 않는다. ZIP 안의 `collection_source` 열은 각 행이 primary 또는 supplement에서 왔는지 표시한다. `account_coverage.csv`에는 계정별 5개 또는 1개 확보 여부가 보존된다. `manifest.json`에 병합 원본별 원시 게시물 수와 중복 계정 제외량/최종 포함량을 구분해 기록한다.

현재 API 사용량 79% 이후 별도 10계정 × 최신 5개 실험을 진행할 수 있다. 이때 수집한 10계정과 기존 1개 수집 계정이 겹쳐도 **5개 원본이 우선**이다. 기존 1개 쪽에서 겹치는 게시물은 ZIP 생성 단계에만 제외되고 실제 두 SQLite는 그대로 유지된다. 10계정 ×5개 성공시 예상 통합 결과는 **191계정 935게시물**(기존 5개 880 + 신규 50 + 겹치지 않는 1개 방식 5), 단 실제 결과에 따라 달라질 수 있다. CSV 생성과 테스트에는 Meta/OpenAI/Google 호출이 없다.
