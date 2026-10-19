# RAW v2 데이터 사전 및 불확실성

- 입력: `input_accounts.csv` 원본 바이트·SHA256 보존. 국가명은 사용자 제공 분류이며 위치 검증값이 아니다.
- `accounts`: 계정 고정 키, 공식 username, 최근 ID, oldest/newest 게시시각, backfill/catchup 커서, 7일 논리 창, 최근 오류, 차단 상태. 계정의 성공/실패는 run별 `request_log` 참조.
- `posts`: `post_id` 문자열 PK, 원본 caption·timestamp·permalink·media_type·media_product_type·URL 보존. `like_count`와 `comments_count`는 관측 테이블에 있다.
- `post_media`: `post_id` FK, single 1개 혹은 carousel_child 여러 개. 컨테이너는 미디어 행에 넣지 않는다.
- `post_observations`: post_id, 관측 시각, run_id, `like_count`, `comments_count`, 각각 존재 여부, request_id. 같은 게시물의 여러 시점 데이터를 덮어쓰지 않는다.
- `account_observations`: 계정 팔로워·팔로잉·게시물 수와 관측 시각. 팔로워 수는 해당 게시물이 올라왔을 때의 수가 아니다.
- `carousel_status`: children 개별 구성 완전 수집/추가 페이지 또는 불확실성. 완전성을 과장하지 않는다.
- `request_log`: Meta Batch **내부 하위 응답별** HTTP/오류/원본 경로·커서·사용량. 외부 Batch HTTP가 성공해도 내부 하위 실패는 실패다.
- `field_observations`: 필드의 `returned` / `null` / `absent` / `not_tested`; 원인(미지원, 권한, 실제 미반환 등)은 별도 검증 전까지 단정할 수 없음.
- `runs`: 시작/종료 시각·성공·실패·중단·사용량. `run_manifest.json`에는 입력 해시, 실행별 행 수/파일 SHA, 전체 294계정별 누적 개수·기간·실패 상태를 기록한다.

## `like_count` 누락 진단 해석

1. 요청 불발 또는 내부 HTTP 오류: 필드 미반환이라고 분류하지 않고 **API 호출 실패**로 둔다.
2. 성공 응답에서 `like_count` 키가 없음: `absent`; 값이 `null`: `null`; 값이 0: `returned`.
3. `media_type`과 `media_product_type`, 국가/계정, 호출 시각/API 버전을 비교해 누락 패턴을 확인한다.
4. 패턴이 발견돼도 서버 정책/권한/미디어 유형 등 **원인은 검증 전 미확인**.
5. 추가 필드 실험 실패의 영향이 본 수집 전체를 중단시키지 않도록 요청을 분리한다.

## 현행 버전의 유보

- `shortcode`, `view_count`: 반환 가능성 검증 전 요청하지 않음. 필드는 `not_tested`로 기록.
- 별도 원본 이미지 다운로드/고품질 AI 분석/4탭 UI: 미구현, 이번 수집기 범위 외.
- 완료된 주간 시간 구간을 실제로 서버 필터링했다는 뜻이 아니다. 현재는 커서 페이지 조회 후 `timestamp`와 7일 구간을 관리한다.
- 커서 만료, 정렬·삭제로 인한 불확실성은 보수적으로 보고한다. 모든 게시물을 빠짐없이 수집했다는 주장은 검증 전 금지.
