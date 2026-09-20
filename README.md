# RepoBite MVP

GitHub 이슈 본문을 읽고 난이도(1/2/3)와 준비도(ready/needs_info/undecided)를 독립적으로 판정하는 CLI.
Python 3.14 표준 라이브러리만 사용한다. 로컬 수집·판정과 공개 탐색 화면을 지원한다.
공용 레포 등록은 Upstash Redis 연결이 필요하며, 설치 패키지와 알림 발송은 없다.

## 사용자들이 추가한 레포

왼쪽 `+` 아이콘(모바일에서는 상단 `+ 담기`)에서 GitHub URL 또는 `owner/repo`를 입력한다.
주소를 모르면 팝업의 **이름으로 검색**에서 GitHub 전체 공개 레포를 검색한다.
검색 버튼 또는 Enter로 조회하며 상위 10개 중 이슈 기능이 켜져 있고 보관되지 않은 결과를 표시한다.
소유자/레포명과 설명을 보고 선택하면 등록 입력란에 이름이 채워진다. **레포 담기**를 눌러야 저장한다.
입력 변경이나 팝업 닫기로 취소한 검색의 늦은 응답은 표시하지 않는다.
검색은 브라우저에서 GitHub 공개 API를 직접 조회하므로 공용 DB 없이도 동작한다.
GitHub 검색 한도나 연결 오류가 발생하면 안내하고, 주소 직접 입력은 계속 사용할 수 있다.
근거: [GitHub 검색 API](https://docs.github.com/en/rest/search/search#search-repositories),
[브라우저 교차 출처 지원](https://docs.github.com/en/rest/using-the-rest-api/using-cors-and-jsonp-to-make-cross-origin-requests).
로그인 없이 모두에게 공유되며, 상단 **사용자들이 추가한 레포**에서 바로 확인한다.
등록은 수집을 실행하지 않는다. 다음 정기 수집까지 **수집 대기**로 표시하고,
수집을 마쳤지만 조건에 맞는 이슈가 없으면 별도로 표시한다.
중복 주소는 대소문자와 GitHub의 정식 이름을 기준으로 하나로 저장한다.
기본 수집 목록에 이미 있는 레포는 추가하지 않고 안내한다.
실패하면 입력을 유지해 재시도할 수 있으며, 취소하면 등록하지 않는다.

공개·이슈 활성화·미보관 레포만 등록한다. 초기 운영 보호를 위해 서비스 전체의 새 주소 확인은
시간당 30회, 공용 등록 목록은 300개까지 받는다. 로그인, 개인별 보관함과 사용자 삭제 기능은 없다.

`api/repos.py`는 Vercel의 공개 등록/조회 API이고, `community.py`는 DB 접근과 등록 검증을 담당한다.
Vercel과 나중에 사용할 Windows 작업 계정에 다음 환경변수를 같은 DB 값으로 설정한다.
값은 채팅·소스·커밋에 넣지 않는다. `.env`는 무시 대상이며 Python이 자동 로드하지 않는다.

- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

DB 생성과 환경변수 설정, 운영 배포는 별도로 해야 한다. 연결 전에는 기존 레포를 계속 표시하지만
공용 목록 조회와 등록은 실패 안내를 표시한다. 미연결 상태를 저장 성공으로 처리하지 않는다.
공개 API의 POST 출처는 정식 운영 주소 `https://repobite.vercel.app`으로 제한한다.
프리뷰 배포의 등록은 지원하지 않는다. 로컬 `web.py`에서는 기존 Host/Origin 검사를 적용한다.

`python3 community_batch.py`는 기본 목록과 공용 등록 목록을 합쳐 기존 수집·판정·후보 생성을 실행한다.
성공한 결과만 DB에 저장하므로 웹 재배포 없이 다음 페이지 조회에 반영된다.
배치 도중 추가된 레포는 다음 배치까지 대기로 남는다. 실패하면 이전 공개 결과를 유지한다.
기본 최근 24시간 갱신 기준과 실행당 100건·레포당 20건 판정 상한은 유지한다.
새 레포의 과거 전체 이슈를 소급 수집하지는 않는다. 실행 파일은 `.radar-community/`에 보관하며,
등록 목록과 공개 결과는 별도 DB 키라 결과 반영 중 등록을 덮어쓰지 않는다.
Windows 스케줄러 연결 방법은 [Windows 운영 문서](docs/Windows-운영.md)를 따른다.

검증: `python3 test_community.py`, `python3 test_web.py`, `python3 test_radar.py`, `node test_web_ui.mjs`.
외부 DB/GitHub를 대체한 검증이며 실제 계정 연결과 Windows 작업 실행은 별도 확인해야 한다.
연결 계약 근거: [Upstash REST API](https://upstash.com/docs/redis/features/restapi),
[Vercel Python Functions](https://vercel.com/docs/functions/runtimes/python),
[GitHub 레포 조회 API](https://docs.github.com/en/rest/repos/repos#get-a-repository).

## Mac에서 웹으로 사용

```sh
python3 web.py
```

[로컬 웹 화면](http://127.0.0.1:8765)을 연다. 포트가 사용 중이면 `python3 web.py --port 8766`으로 바꾼다.

Windows 홈서버는 [Tailscale 내부 상태 페이지](docs/홈서버-상태.md)에서 서비스와 예약 수집 상태를 확인한다.
이 Mac에 로그인된 `gh`와 Google Cloud ADC를 사용한다. 서버를 켠 터미널은 실행 중에 유지한다.
서버 종료는 `Ctrl+C`이며, 진행 중인 CLI 작업도 종료 신호를 보낸다.

1. 레포 목록과 최근 갱신 기간을 선택하고 **이슈 수집**을 누른다. 이전에 저장한 목록은 **기본 30개 불러오기**로 교체할 수 있다. 기존 표본은 **고정 표본 30건 수집**으로 조회한다.
2. **제한 N건 판정**은 실행당 새 모델 호출 최대 100건, 레포당 최대 20건을 판정한다. **전체 N건 판정 (상한 없음)**은 아직 판정하지 못한 이슈를 모두 판정한다. 두 버튼 모두 Vertex AI의 `gemini-3.1-flash-lite`, 최대 16개 동시 실행을 사용한다.
3. 추천 후보, 전체, 제외, 미판정·실패 항목을 골라 판정 이유와 GitHub 이슈를 확인한다. 추천 직전에 GitHub에서 열린 상태, 담당자, 연결된 열린 PR을 다시 확인하며 확인 실패도 추천에서 제외한다.

처음에는 기존 `issues.jsonl`과 `grades.jsonl`을 보여준다. 웹 작업은 `.radar-web/` 아래에 따로 저장하고
기존 CLI 파일을 덮어쓰지 않는다. 각 작업 결과를 저장한 뒤 `current` 링크를 원자적으로 교체해
수집분과 판정 결과가 섞이지 않게 한다. 서버 재시작 후에도 마지막 결과를 복원한다.
새 수집은 미판정 상태로 시작한다. 수집 실패는 이전 결과를 유지하고, 판정 일부 실패는 성공/실패를 함께 표시한다.
이전 작업 폴더는 로컬에 보존되지만 화면에는 마지막 결과만 표시한다. 자동 재시도나 이력 관리 화면은 없다.

서버는 `127.0.0.1`에만 연결한다. Host/Origin 검사와 JSON 요청 헤더 검사로 다른 사이트의 실행 요청을 거절하고,
정해진 페이지와 API만 제공한다. 파일 경로나 셸 명령을 웹에서 입력받지 않는다.
Mac 한 사용자, 서버 한 인스턴스, 동시 작업 하나를 위한 도구이며 외부 공개 서버 용도는 아니다.
HTTP 구현은 Python의 [ThreadingHTTPServer](https://docs.python.org/3.14/library/http.server.html)를 사용한다.

검증: `python3 test_web.py`, `python3 test_radar.py`. 화면 스크립트의 오류 복구와 버튼 분기는 Node 표준 모듈만 사용하는 `node test_web_ui.mjs`로 검사한다.
기존 Luna 실측 결과는 품질 문서에 보존하며, 현재 판정 경로는 Vertex AI를 사용한다.
WebMCP 지원 브라우저에서는 같은 판정 시작 동작을 `start_issue_grading` 도구로 제공한다.
이 환경에는 지원 브라우저 검증 컨텍스트가 없어 WebMCP 등록/실행은 미검증이며 일반 버튼은 독립적으로 동작한다.

## 준비와 실행

Python 3.14, 인증된 `gh`, Google Cloud CLI의 ADC가 필요하다.
개발 환경에서 Python 3.14.5와 gh 2.67.0을 확인했다. Vertex AI API를 활성화하고 다음처럼 로컬 인증과 프로젝트를 지정한다.

```sh
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com
export GOOGLE_CLOUD_PROJECT="$(gcloud config get-value project)"
export GOOGLE_CLOUD_LOCATION=global
```

다른 계정의 서비스 계정 JSON을 로컬에서 사용할 때는 저장소 밖의 파일을 지정한다. 프로젝트 ID는 파일에서 자동으로 읽는다.

```sh
export GOOGLE_APPLICATION_CREDENTIALS="/안전한/경로/service-account.json"
export GOOGLE_CLOUD_LOCATION=global
```

Cloud Run에서는 연결된 서비스 계정의 메타데이터 토큰을 사용하므로 키 파일을 만들지 않는다.
키나 토큰을 코드에 넣지 않는다. `.env`는 Git에서 제외되며 앱이 자동으로 읽지는 않는다.

```sh
python3 test_radar.py
python3 radar.py collect --since 7d
python3 radar.py grade
python3 radar.py candidates
python3 radar.py batch
python3 radar.py report
```

`candidates`는 최신 상태 확인까지 통과한 Lv.1 × ready 이슈만 `candidates.jsonl`에 기록한다.
기존 후보는 유지하고 같은 `repo/number`는 다시 넣지 않으며, 실행마다 레포당 새 후보를 최대 5건 추가한다.
`batch`는 최근 24시간 이슈 수집, 제한 판정, 후보 생성을 순서대로 실행하고 중간 단계가 실패하면 즉시 종료한다.
Windows 자동 실행 설정은 [Windows 운영 문서](docs/Windows-운영.md)를 따른다.
원격 관리는 [Windows 홈 서버 SSH 접속 문서](docs/Windows-SSH-접속.md)의 Tailscale SSH와
로컬 웹 포트 포워딩 절차를 따른다.

`repos.txt`에 추적할 레포를 한 줄에 하나씩 적는다. 빈 줄과 `#` 주석을 허용한다.
기본은 **10개 분야 × 3개, 총 30개**다. AI 에이전트, 모델 추론, 프런트엔드, 백엔드,
데이터, 개발 도구, 인프라·보안, 생산성, 모바일·데스크톱, 미디어를 고르게 담았다.
2026-09-10 확인한 GitHub Trending에서 25개를 관찰했고, 나머지는 분야 균형을 위해 보완했다.
24개가 2023년 이후 생성됐으며, 30개 모두 최근 30일 내 push와 열린 이슈가 있다.
처리량을 줄이기 위해 `NousResearch/hermes-agent`를 제외하고 열린 이슈가 상대적으로 적은 후보를 남겼다.
개별 레포와 조회 근거는 [선정 문서](docs/레포-선정.md)에 기록했다. 목록은 수동 선정이며 자동 갱신하지 않는다.

웹은 한 번에 최대 30개를 받는다. 전체 수집은 레포별 모든 페이지를 읽으므로 먼저 최근 1일로
조회해 건수를 확인할 수 있다. 실행 내역에 레포 진행 번호가 표시된다. 모델 판정은 별도 버튼으로 시작한다.

- `collect`: `gh api repos/{repo}/issues`를 페이지 끝까지 읽고 PR, 담당자가 있는 이슈, 봇 작성 이슈를 제외한다. 문자열/라벨 사전 필터는 없다.
- `--since 7d`: 최근 7일 **갱신** 기준이다. 생성 시각 필터가 아니다. `24h`, `1w`도 지원한다.
- `grade`: 이슈당 Vertex AI REST 호출 1회, 최대 16개 동시 호출. 기본 모델은 `gemini-3.1-flash-lite`, 사고 수준은 `minimal`이다. `--model`로 변경할 수 있다.
- `report`: Markdown 교차표, Lv.1 × ready 비율, 레포 분포와 상위 3개 집중도, 사람 판정과의 이진 비교를 stdout에 출력한다.

기본 판정은 웹·CLI 모두 **실행당 최대 100건, 레포당 최대 20건**이다. 수집 파일에 등장한 레포 순서대로
한 건씩 번갈아 선택하고, 각 레포 안에서는 `created_at`이 최근인 이슈를 먼저 선택한다.
같은 생성 시각이면 입력 순서를 유지한다. 대소문자만 다른 레포 이름도 동일한 레포로 묶는다.
실패한 호출도 상한에 포함하며 다른 이슈로 보충하지 않는다. 다음 실행에서는 실패 건을 다시 판정한다.
수집 원본은 유지하고 기존의 정확히 일치하는 성공 판정과 이번에 선택한 성공·실패를 판정 파일에 누적한다. 상한 밖의 미판정 이슈는 웹에서 미판정으로 남는다.
리포트 비율은 판정 파일에 누적된 결과 기준이며 아직 미판정인 전체 수집분까지 포함한 비율로 해석하면 안 된다.
이 상한은 한 번의 실행 기준이다. repo/number, 제목, 본문, 모델, 추론 강도, 판정 기준 버전이 모두 같은 성공 판정만 재사용한다.

기존 전체 판정은 웹의 **전체 N건 판정 (상한 없음)** 또는 CLI의 `python3 radar.py grade --all`로 실행한다.
전체 모드는 두 건수 상한을 모두 해제하며 입력 순서로 미판정·실패·변경 이슈를 판정한다. 정확히 일치하는 성공 결과는 재사용한다.
웹에서는 제한·전체 판정 중 어느 하나가 실행 중이면 다른 실행 버튼도 잠긴다.

입출력 경로는 `collect --repos/--output`, `grade --input/--output`, `report --input/--sample`로 바꾼다.
기본 입력 목록/스키마/표본은 스크립트 옆 파일을 사용하며 결과 파일은 현재 디렉터리에 쓴다.

## 고정 표본 재측정

```sh
python3 radar.py collect --sample fixtures/sample30.json
python3 radar.py grade --model gemini-3.1-flash-lite
python3 radar.py report
```

`collect --sample`은 Search API 없이 고정된 repo/number로 직접 조회한다.
과거 비교를 위해 현재 닫힌 이슈도 유지하지만 PR/담당자/봇 필터는 동일하게 적용한다.
현재 상태와 본문을 조회하므로 최초 사람 판정 당시와 달라질 수 있다.
조회 실패와 제외 사유는 stderr에 출력하며, 조회 실패가 있으면 종료 코드 1을 반환한다.
`--sample`과 `--since`는 함께 사용할 수 없다.

사람 판정과 사유는 `fixtures/sample30.json`에 지시서 30행을 그대로 옮겼다.
모델에는 실제 제목/본문과 판정 기준만 전달한다. 사람 판정은 전달하지 않는다.
다만 지시서의 few-shot 2건은 이 표본에도 속하므로 이 측정은 완전히 독립된 평가가 아니다.

## 데이터와 비율 해석

`issues.jsonl`은 `repo, number, title, body, url, created_at, labels, user, repository_image`를 저장한다.
`repository_image`는 README 이미지 후보 중 AI가 선택한 네트워크 URL이며, 없으면 웹에서 Social preview를 사용한다.
본문 null은 빈 문자열로, labels는 이름 배열로, user는 login 문자열로 정규화한다.
`grades.jsonl`은 원본 필드에 `model, reasoning_effort, criteria_version, graded_at, grade`를 추가한다.
`grade` 안에 `difficulty, readiness, reason, exclude, exclude_reason`이 있다.
Lv.1 × ready 후보에는 `freshness` 확인 결과를 추가하고 `eligible=true`인 건만 추천한다.
판정 실패는 `grade: null`과 `error` 오류 분류로 남기며 명령은 종료 코드 1을 반환한다.
실패를 성공으로 간주하거나 통계에서 숨기지 않는다.

주 비율은 `exclude=false AND difficulty=1 AND readiness=ready` 건수를
**판정 성공 전체 건수(AI 제외 포함)**로 나눈다. AI 제외 후 분모의 비율도 함께 표시한다.
교차표는 AI 제외 후 대상이며, 레포 집중도는 실패를 포함한 입력 건수 기준이다.
실패가 있으면 비율은 성공한 일부에 대한 값이다. 분모가 0이면 측정 불가로 표시한다.

사람 판정 비교는 repo/number가 일치하고 판정에 성공한 표본만 사용한다.
사람의 `부적합`과 AI의 `difficulty=3 OR readiness=undecided`를 이진 비교한다.
사람의 `적합/조건부`는 비부적합으로 묶고, AI의 `exclude`는 이 조건에 합치지 않는다.
매칭 건수, 혼동표, 전체 이진 일치율, 사람 부적합과의 겹침을 표시한다.
**이 수치는 두 축의 정답 일치율이나 일반 이슈 전체의 공급 비율이 아니다.**

출력은 임시 파일에 쓴 뒤 교체한다. 수집 오류나 저장 중 예외가 기존 결과를 자르지 않는다.
성공한 재실행은 지정한 결과 파일을 교체한다. 성공 판정은 정확히 일치할 때 재사용하며 실패 판정은 다음 실행에서 다시 호출한다.
수집 실패 없는 일반 실행은 전체 수집을 저장한다. 표본 모드는 조회 가능한 일부도 저장하고 실패를 알린다.
원문과 판정 결과인 `*.jsonl`은 로컬에서 확인하고 Git에는 넣지 않는다.
표본 실측 요약은 [기획서 20절](docs/기획서.md)에 기록한다.

## 판정 실행과 제약

판정은 Vertex AI `generateContent` REST API에 JSON 스키마를 함께 보낸다. 온도는 0이고 외부 도구는 사용하지 않는다.
이슈 본문의 명령을 따르지 않도록 프롬프트에 데이터 경계를 명시한다. 로컬에서는 ADC의 짧은 수명 토큰을, Cloud Run에서는 연결된 서비스 계정의 메타데이터 토큰을 사용한다.

`schema.json`은 Structured Outputs 호환을 위해 모든 필드를 필수로 둔다.
지시서 예시와 달리 `exclude_reason`도 필수이며, 제외하지 않으면 빈 문자열이다.
stdlib 검증기는 이 고정 스키마의 필드/타입/enum과 비어 있지 않은 판정 근거를 검사한다.

이미 연결된 PR의 timeline 조회, 레포별 알림 상한, 번역 공백 발굴은 이번 범위 밖이다.
구독으로 실행하므로 API 비용과 기획서 월 $10~$50 추정은 검증하지 않는다.

근거: [GitHub Issues API](https://docs.github.com/en/rest/issues/issues#list-repository-issues),
[GitHub GraphQL Issue](https://docs.github.com/en/graphql/reference/issues),
[Vertex AI Gemini 빠른 시작](https://cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart),
[Vertex AI JSON 스키마 출력](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1beta1/GenerationConfig),
[Google Cloud REST 인증](https://cloud.google.com/docs/authentication/rest),
[Gemini 3.1 Flash-Lite 모델](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-flash-lite).
