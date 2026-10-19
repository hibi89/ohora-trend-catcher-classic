# OHORA 2차 프로젝트 신규 RAW 수집 실행 지시서

작성일: 2026-10-18 KST
대상: 이 파일을 전달받은 GPT-6 Sol / 개발·수집 담당 에이전트
상태: 사용자 요청으로 확정한 수집 스키마 및 실행 지침. 실제 신규 수집은 아직 수행하지 않았다.

## 1. 지금 해야 할 일과 승인 범위

이 문서를 읽고 기존 OHORA 수집 프로젝트를 복원한 뒤, 문서를 GitHub에 기록하고 수집기를 보완·검증하여 신규 원본 수집을 진행하라. 설명이나 계획 제시만 하고 끝내지 마라. 이미 정한 아래 구조를 다시 설계하거나 같은 승인을 반복해서 요청할 필요는 없다.

사용자의 목적은 국비지원 2차 프로젝트에서 실제 젤네일 회사 OHORA의 국가별 네일 디자인·트렌드를 분석하기 위한 원본 확보다. 제공받은 공식 표본은 294계정이다. 이번 작업은 기존 CSV의 병합·분석이 아니라 API를 통한 신규 RAW 데이터 수집이다.

승인 범위: 기존 저장소 확인, 이 설계와 코드·검증 문서의 기존 비공개 GitHub 반영, 기존 인증 경로를 이용한 시험 조회와 확정 범위 내 본 수집, 실행별 결과 보존이다. 공개 저장소 전환·새 서비스 생성·결제·권한 변경·데이터의 새 외부 서비스 전송·기존 원본 덮어쓰기는 포함하지 않는다. API 호출은 사용 가능한 인증정보와 실행 환경이 실제 확인된 경우에만 수행한다.

## 2. 먼저 프로젝트와 수집 범위를 확인

1. 비공개 `hibi89/project-book`의 `main/BOOK.md`에서 기존 OHORA 수집 프로젝트를 확인한다. 저장소 이름이나 p번호를 추측하지 않는다. 실험용 대시보드 프로젝트와 실제 배치 수집 프로젝트를 구분한다.
2. 확인된 저장소의 최신 브랜치와 `HANDOFF.md → STATUS.md → AGENTS.md → REQUIREMENTS.md → 실제 수집 코드` 순으로 읽는다. 문서와 코드가 다르면 확인된 사실을 우선하여 차이를 기록한다.
3. 기존 작업 트리·브랜치·인증 경로·토큰 관리·API 버전·테스트·배치/재개 기능을 확인한다. 사용자 변경을 덮어쓰지 않고 기준 커밋을 복구 지점으로 확보한다.
4. 294개 공식 입력 목록을 보존한다. 입력 목록과 수집 결과의 사용자명을 구분한다. 계정명 불일치를 임의로 교정하지 않는다.
5. 계정당 목표 게시물 수와 기간은 최신 문서·사용자 지시의 확정 설정을 사용한다. 과거 1/5/10개 시험 수집이나 이전 대화의 12개월 제안은 이번 실행의 자동 승인값이 아니다. 확정값이 없거나 서로 충돌하면 개발·오프라인 검증·문서 기록까지 마친 뒤 본 수집 전에 그 항목만 질문한다.
6. 두 API 계정이나 배치 설정이 기존에 있으면 최신 검증된 설정을 확인해 사용한다. 계정/토큰이 둘이라는 이유로 독립 한도나 처리 속도를 보장하지 않는다. 한도 우회를 목적으로 계정 회전하지 않는다.

## 3. 참고 자료와 이미 확인된 사실

- `OHORA_20261016_RAW_286(1).zip`: 공식 입력 목록과 latest1/latest5/latest10 계정·게시물·미디어 CSV 묶음. API 응답 JSON 및 실제 이미지 파일은 없었다.
- `OHORA_Analysis_Ready_20261016_084112(1).zip`: 위 자료를 합친 분석용 가공본. 이번 신규 원본의 대체 자료가 아니다.
- 기존 파일에는 게시물 1,845개와 캐러셀 하위 미디어가 포함되어 있었다. `media_product_type`에 FEED/REELS 값도 있었다. 이는 과거 파일의 사실이며 현재 API 실호출 성공을 뜻하지 않는다.
- 분석용 캡션 13개는 기존 RAW와 문자열이 달랐다. 새 RAW에는 엑셀용 작은따옴표 추가·공백 정리·번역 등 문자열 변형을 하지 않는다.
- `OHORA_Instagram_API_수집가능범위_공유용_2026-10-16 (1).pdf`는 9쪽 참고자료다. 외부 Business Discovery와 소유자 승인 계정의 Insights를 구분하며, 자료 자체에 실제 오호라 토큰 실호출 미검증이라고 명시되어 있다.
- 작성 시 최신 Meta 공식 문서 조회는 429로 제한되었다. 아래 필드 목록은 목표 스키마이며 현재 버전의 모든 필드가 보장된다는 뜻이 아니다. 실제 토큰·경로의 응답으로 확인한다.
- 위 참고 파일이 없어도 아래 명세로 구현할 수 있다. 단 공식 294계정 입력 목록과 실행 가능한 인증정보는 필요하다.

## 4. 원본 저장 구조

```text
data/<run_id>/
  input_accounts.csv
  accounts.csv
  posts.csv
  post_media.csv
  collection_log.csv
  field_support.csv
  run_manifest.json
  raw/
```

날짜·실행마다 새 폴더를 만든다. 기존 원본과 시험 수집을 본 수집에 조용히 섞지 않는다. 필드명은 아래로 고정하며 API 필드와 관리값을 구분한다. 실제 이미지 다운로드는 별도 확정 범위가 있을 때만 수행하고 URL 확보와 파일 확보를 구별한다.

### 4.1 accounts.csv — 계정

| 컬럼 | 뜻 / 출처 |
|---|---|
| run_id | 실행 식별자, 관리값 |
| account_key | 공식 입력 목록 고정 번호 |
| input_username | 공식 입력 사용자명 |
| input_profile_url | 실제 제공된 프로필 URL, 없으면 빈값 |
| source_country | 공식 입력 국가 분류, API 검증 국가가 아님 |
| id | API 계정 id |
| ig_id | API ig_id, 시험 조회 후 반환 시 보존 |
| username | API가 반환한 현재 사용자명 |
| name | 프로필 표시 이름 |
| biography | 소개글 원문 |
| website | 프로필 웹사이트 |
| profile_picture_url | API 프로필 이미지 URL |
| followers_count | 수집 시 팔로워 수 |
| follows_count | 수집 시 팔로잉 수 |
| media_count | API가 반환한 계정 게시물 수 |
| collected_at | 해당 계정 응답을 받은 시각 |

API 후보: `id,ig_id,username,name,biography,website,profile_picture_url,followers_count,follows_count,media_count`

입력 URL이 없으면 만들어서 input_profile_url에 넣지 않는다. 필요하면 constructed_profile_url을 명시적으로 추가한다. 계정 조회 실패 대상도 input_accounts.csv와 로그에서 반드시 추적한다. 실패한 계정의 API 정보를 만들어 채우지 않는다.

### 4.2 posts.csv — 게시물

| 컬럼 | 뜻 / 출처 |
|---|---|
| run_id | 실행 식별자 |
| account_key | 공식 입력 계정 연결 번호 |
| ig_user_id | accounts.id를 연결한 값, accounts.ig_id가 아님 |
| id | API 게시물 id |
| username | 게시물 응답의 작성자명, 지원 확인 후 보존 |
| caption | 본문 원문 |
| timestamp | API 게시 시각 |
| permalink | 원본 게시물 링크 |
| media_type | 이미지·영상·캐러셀 유형 |
| media_product_type | FEED/REELS 등, 현재 경로에서 지원 검증 |
| media_url | 대표 이미지·영상 URL, 반환 시 |
| thumbnail_url | 영상 썸네일 URL, 반환 시 |
| like_count | 응답 시 좋아요 수, 반환 시 |
| comments_count | 응답 시 댓글 수, 반환 시 |
| shortcode | 선택 검증 필드, 지원·반환 시 |
| view_count | 선택 검증 필드, 지원·반환 시 |
| collected_at | 해당 게시물 응답을 받은 시각 |

기본 API 후보: `id,username,caption,timestamp,permalink,media_type,media_product_type,media_url,thumbnail_url,like_count,comments_count`

별도 검증 후보: `shortcode,view_count`

id, ig_id, ig_user_id의 의미를 혼동하지 않는다. view_count는 views/total_views_count와 같은 값으로 간주하거나 대체하지 않는다. 선택 필드 미지원 시 컬럼은 빈값으로 유지하고 field_support.csv에 이유를 기록할 수 있다.

### 4.3 post_media.csv — 개별 구성 이미지·영상

| 컬럼 | 뜻 / 출처 |
|---|---|
| run_id | 실행 식별자 |
| account_key | 공식 입력 계정 연결 번호 |
| post_id | posts.id 연결 |
| id | 개별 미디어 API id |
| media_role | single 또는 carousel_child |
| item_order | API 반환 순서, 1부터 |
| media_type | 개별 이미지·영상 유형 |
| media_url | 개별 미디어 URL, 반환 시 |
| thumbnail_url | 개별 영상 썸네일 URL, 반환 시 |
| collected_at | 해당 미디어 응답을 받은 시각 |

children API 후보: `id,media_type,media_url,thumbnail_url`

- 단일 이미지·영상은 상위 게시물 응답으로 한 행을 만들고 media_role=single, id=post_id로 둔다. 이를 위해 불필요한 추가 API 호출을 하지 않는다.
- 캐러셀은 children의 각 미디어를 한 행으로 저장한다. 컨테이너 자체는 이 테이블에 넣지 않는다. 상위 컨테이너 정보는 posts.csv와 raw JSON에 보존한다.
- children에 다음 페이지가 있으면 지원되는 방식으로 이어서 수집한다. 목록 종료를 확인하지 못했으면 완료라고 쓰지 않는다.
- 삭제·권한·URL 누락 등으로 행이 부족한 경우 실제 확보한 범위만 기록한다.

### 4.4 collection_log.csv — 요청/수집 이력

```csv
run_id,request_id,account_key,resource_type,parent_post_id,started_at,finished_at,api_version,requested_fields,requested_post_limit,requested_since,requested_until,page_index,attempt_no,http_status,status,records_received,has_next_page,stop_reason,error_code,error_subcode,error_message,raw_response_path
```

- resource_type: account/posts/children. 중첩 응답이면 같은 request_id로 자원별 로그를 연결할 수 있다.
- status: success/partial/failed. HTTP 성공과 수집 목표 완료를 혼동하지 않는다.
- stop_reason: target_count_reached/date_boundary_reached/end_of_list/rate_limited/api_error/interrupted/field_unsupported 등 의미가 명확한 값.
- 배치 외부 HTTP 200만 보고 성공 판정하지 말고 내부 응답 상태와 오류를 확인한다.
- requested_since/until은 목표 조건이지 API가 해당 파라미터를 지원한다는 뜻이 아니다. 페이지네이션 후 timestamp 판정이 필요하면 코드에서 처리한다.
- has_next_page는 true/false/unknown을 구분한다. children의 end_of_list 확인이 없으면 완전 수집을 보장하지 않는다.
- 오류 로그와 원본 응답에서 토큰·비밀값을 제거한다.

### 4.5 field_support.csv / run_manifest.json

field_support.csv 헤더:

```csv
api_version,resource_type,field_name,checked_at,status,sample_count,error_code,note
```

필드 상태는 returned/accepted_but_absent/rejected/not_tested 등을 구분한다. 빈 응답 한 번만으로 미지원 확정하지 않는다. 오류가 토큰·한도 원인이면 필드 미지원으로 분류하지 않는다.

run_manifest.json에는 실행 시작/끝·확정 수집 개수/기간·실제 API 버전·입력 목록 해시·수집기 Git SHA·파일별 행 수/해시·계정별 확보 게시물 수/최초·최종 게시시각/중단 이유·캐러셀 완료/미확인 수·전체 성공/부분/실패 범위를 기록한다. 이는 원본 검증용 관리값이며 분석 결과가 아니다. 자격증명은 기록하지 않는다.

## 5. 원본 보존 규칙

1. CSV 이전 API 응답 JSON을 raw/에 저장한다. 인증정보만 마스킹하고 나머지 필드·중첩 구조·누락 여부를 보존한다. 토큰이 포함된 paging URL도 처리한다.
2. caption과 biography의 줄바꿈·공백·이모지·해시태그를 바꾸지 않는다. CSV 문법에 맞는 인용/이스케이프는 사용하되 재파싱 결과 원문이 같아야 한다.
3. id/ig_id/post_id/ig_user_id 등 모든 식별자는 문자열로 읽고 쓴다. 지수 표기·부동소수점 변환 금지. CSV의 따옴표만으로 Excel 자료형이 보장되지는 않으므로 가져오기 안내를 제공한다.
4. 미반환·해당 없음·미확보를 실제 0과 구별한다. CSV 빈값의 정확한 근거는 원본 JSON·필드 검증·로그에서 추적한다.
5. timestamp는 API 원문을 보존하고 관리 시각은 시간대가 포함된 ISO 8601로 기록한다. 수집 시 팔로워 수를 게시 당시 팔로워 수로 표현하지 않는다.
6. 재개 시 이미 확보한 항목의 불필요한 재호출과 중복 행을 방지한다. 새 관측은 새 실행/시각으로 보존하고 과거 관측을 덮어쓰지 않는다.
7. 이미지 파일을 별도 승인 범위에서 다운로드한다면 local_path/download_status/downloaded_at/file_sha256을 별도 관리한다. SHA256은 시각적 유사도 점수가 아니다.
8. engagement_count/engagement_rate_pct/hashtags/mentions/language/inferred_country/is_design_post/color/technique/texture/motif/season/trend_score는 이번 RAW에 생성하지 않는다.
9. Insights·댓글 본문·저장/공유/도달·팔로워 인구통계·Creator Marketplace로 범위를 확대하지 않는다. 외부 계정 API와 소유자 승인 API를 혼합하지 않는다.

## 6. 실행 순서

1. 최신 저장소와 실행 환경을 확인하고 이 문서를 `docs/OHORA_RAW_COLLECTION_EXECUTION.md`에 보존한다. 기존 문서가 있으면 차이를 확인하고 이력을 남긴다.
2. 위 스키마를 SCHEMA.md 또는 기존 대응 문서에 반영한다. 작은 수정으로 기존 수집기를 재사용한다. 기존 정상 기능과 원본은 보존한다.
3. 네트워크 없이 fixture/기존 응답 형태를 이용하여 CSV 보존·ID·결측·관계·캐러셀 페이지네이션·배치 내부 오류·중단 후 재개를 검증한다. 실제 의미 있는 검증만 작성한다.
4. 국가와 미디어 유형이 다른 소수 대상부터 실제 API 시험 조회한다. 기존 검증 필드부터 확인하고 추가 필드는 분리하여 검증한다. shortcode/view_count 오류로 전체 기본 조회가 깨지지 않게 한다.
5. 실제 응답과 사용량 헤더를 확인하여 기존 확정 배치 크기·간격을 사용하거나 더 보수적으로 조정한다. 한도 도달 시 체크포인트를 남기고 중단/재개하며 무한 재시도하지 않는다.
6. 확정된 개수/기간·294계정 목록으로 본 수집한다. 아직 확정되지 않은 수집 범위는 임의로 정하지 않는다. 이미 확인된 범위·권한은 사용자에게 다시 묻지 않는다.
7. CSV와 JSON을 검증하고 결과를 실행별 패키지로 정리한다. 실패 계정을 숨기지 말고 부분 완료를 정확히 보고한다.
8. GitHub의 코드·설계·검증 결과·상태·인수인계와 등록부를 최신화한다. 이후 진행자가 바로 재개할 수 있게 남긴다.

동일 원인으로 진전 없는 실패가 발생하면 원인 분석 후 실질적으로 개선한 방법으로 최대 1회 재시도한다. 2회 실패하면 중단 지점·근거·대안을 보고한다. 단 정상적인 검증 진전이 있는 개발 반복을 기계적으로 제한하지 않는다.

## 7. 완료 검증 기준

- 공식 294계정 입력 목록의 행 수·키 중복·국가 분류·사용자명 보존 확인.
- 실행 내 posts.id 중복 검사 및 accounts와 연결되는 account_key/ig_user_id 검사.
- post_media.post_id의 참조 무결성, 단일 행/캐러셀 자식 규칙, item_order와 페이지 경계 확인.
- 캐러셀 컨테이너를 구성 미디어 개수에 중복 포함하지 않았는지 확인.
- 원본 JSON에서 추출한 caption·수치·ID와 CSV를 대조. 결측과 0·긴 ID·줄바꿈·유니코드 검증.
- 모든 실패/미완료 대상에 로그와 중단 이유가 존재하는지 확인.
- 최신 N개 확보를 전체 과거 이력 확보로 표현하지 않는지 확인.
- 시험 호출/본 수집/오프라인 테스트를 구분하고 검증한 수·실패 수·미검증 항목을 보고.
- 토큰·환경파일·민감정보가 결과 패키지와 Git 변경 목록에 없는지 검사. 비밀값은 출력하지 않는다.
- URL 확보와 이미지 다운로드 완료를 분리하여 보고.
- 수집 결과를 재열어 행 수·관계·파일 해시를 확인. 실행 성공 로그만으로 완료 판정하지 않는다.

## 8. GitHub 공시·인수인계

사용자가 말한 Git 공시는 기존 비공개 저장소에 설계·코드·검증 기록을 남기는 뜻이다. 공개 배포나 원본 데이터 업로드를 뜻하지 않는다.

- Git에는 코드·본 지시서·스키마·비밀값 없는 테스트·검증 요약만 반영한다. 대용량 원본 CSV/JSON/미디어·토큰·.env는 올리지 않는다. 적절한 gitignore를 확인한다.
- 커밋 전 Author/Committer와 GitHub 계정 연결, GIT_AUTHOR_EMAIL/GIT_COMMITTER_EMAIL 덮어쓰기 여부를 확인한다. force push·이력 재작성·빈 커밋 반복 금지.
- 주요 완료·중단 시 STATUS.md/HANDOFF.md를 갱신하고 실제 커밋 SHA를 재조회한다.
- HANDOFF에는 ①목표/요구/기술 ②완료 기능/결정 근거 ③테스트 명령과 결과/미검증 ④상태/중단 지점 ⑤오류/시도/금지 재시도/대안 ⑥저장소/브랜치/SHA/경로 ⑦실행 명령/환경/배포 미적용 여부 ⑧원본 위치/백업/인증 관리/수정 금지 ⑨다음 작업/완료 기준/승인 사항 ⑩KST 시각/검증 범위/문서 기준 커밋을 기록한다.
- project-book/BOOK.md에서 담당 저장소를 확인·필요시 등록하고 마지막 실제 작업 시각(KST)과 상태를 갱신한다. 조건부 SHA 저장·충돌 시 재조회·커밋 후 재조회로 검증한다. 번호를 임의로 만들거나 다른 프로젝트를 덮어쓰지 않는다.
- 이번 작업은 수집기/원본 확보다. 기존 요구가 없는 Vercel 배포나 대시보드 개발은 하지 않는다. 배포 항목은 미적용으로 표시한다.
- Git 쓰기 실패 시 미반영이라고 보고하고 변경 코드·인수인계의 다운로드 대안을 제공한다. 문서만 썼다고 수집 완료를 주장하지 않는다.

## 9. 최종 사용자 보고

짧고 명확하게 다음을 보고한다.

1. 저장소 / 브랜치 / 원격에서 확인한 SHA / 설계 문서 경로.
2. 실제 사용 API 버전 / 검증된 필드 / 미지원 또는 미확인 필드.
3. 확정 수집 범위 / 대상·성공·부분·실패 계정 수 / 게시물·개별 미디어 수.
4. 원본 JSON·CSV·실제 이미지 각각의 확보 여부와 결과 위치.
5. 테스트 및 원본 대조 결과 / 남은 문제 / 다음 재개 지점.
6. Vercel: 이번 작업은 미적용(기존 별도 요구가 없는 경우).
7. STATUS/HANDOFF/BOOK 반영과 원격 재조회 결과.
8. 마지막 줄: BOOK.md에서 실제 확인한 `프로젝트 번호: pN`, 없으면 `프로젝트 번호: 미배정`.

이 문서를 받은 뒤 확인 가능한 작업은 자율적으로 진행하라. 저장소·입력 목록·인증정보·수집 범위 중 실제로 부족한 항목만 근거를 들어 질문하고, 확보하지 않은 결과를 성공으로 표현하지 마라.