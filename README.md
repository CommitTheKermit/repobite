# oss-radar MVP

GitHub 이슈 본문을 읽고 난이도(1/2/3)와 준비도(ready/needs_info/undecided)를 독립적으로 판정하는 CLI.
Python 3.14 표준 라이브러리만 사용한다. Mac 로컬 웹 화면을 지원하며 설치 패키지, DB, 알림 발송은 없다.

## Mac에서 웹으로 사용

```sh
python3 web.py
```

[로컬 웹 화면](http://127.0.0.1:8765)을 연다. 포트가 사용 중이면 `python3 web.py --port 8766`으로 바꾼다.
이 Mac에 로그인된 `gh`와 `codex`를 그대로 사용한다. 서버를 켠 터미널은 실행 중에 유지한다.
서버 종료는 `Ctrl+C`이며, 진행 중인 CLI 작업도 종료 신호를 보낸다.

1. 레포 목록과 최근 갱신 기간을 선택하고 **이슈 수집**을 누른다. 이전에 저장한 목록은 **기본 30개 불러오기**로 교체할 수 있다. 기존 표본은 **고정 표본 30건 수집**으로 조회한다.
2. **제한 N건 판정**은 실행당 새 모델 호출 최대 100건, 레포당 최대 20건을 판정한다. **전체 N건 판정 (상한 없음)**은 아직 판정하지 못한 이슈를 모두 판정한다. 두 버튼 모두 저비용 모델 `gpt-5.6-luna`, 추론 `low`, 최대 16개 동시 실행을 사용한다.
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
실제 HTTP 요청으로 `bibliometrix#666` 1건 수집과 Luna 판정도 확인했다.
WebMCP 지원 브라우저에서는 같은 판정 시작 동작을 `start_issue_grading` 도구로 제공한다.
이 환경에는 지원 브라우저 검증 컨텍스트가 없어 WebMCP 등록/실행은 미검증이며 일반 버튼은 독립적으로 동작한다.

## 준비와 실행

Python 3.14, 인증된 `gh`, ChatGPT로 로그인된 `codex`가 필요하다.
개발 환경에서 Python 3.14.5, gh 2.67.0, codex-cli 0.153.4를 확인했다.
인증이 없다면 각 CLI에서 `gh auth login`, `codex login`을 실행한다.
키나 토큰을 코드에 넣지 않는다. `.env`는 Git에서 제외되며 앱이 자동으로 읽지는 않는다.

```sh
python3 test_radar.py
python3 radar.py collect --since 7d
python3 radar.py grade
python3 radar.py report
```

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
- `grade`: 이슈당 `codex exec` 1회, 최대 16개 동시 호출. 기본 모델은 `gpt-5.6-luna`, 추론은 `low`다. `--model`로 변경할 수 있다.
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
python3 radar.py grade --model gpt-5.6-luna
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

`issues.jsonl`은 `repo, number, title, body, url, created_at, labels, user`를 저장한다.
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

판정은 임시 디렉터리에서 `read-only`, `--ephemeral`로 실행한다.
사용자 config와 프로젝트 문서 주입을 끄고 shell/web 도구를 비활성화한다.
프롬프트는 stdin으로 보내며, 이슈 본문의 명령을 따르지 않도록 데이터 경계를 명시한다.
원시 CLI stderr는 인증 정보 등이 섞일 수 있어 출력하지 않는다.

`schema.json`은 Structured Outputs 호환을 위해 모든 필드를 필수로 둔다.
지시서 예시와 달리 `exclude_reason`도 필수이며, 제외하지 않으면 빈 문자열이다.
stdlib 검증기는 이 고정 스키마의 필드/타입/enum과 비어 있지 않은 판정 근거를 검사한다.

이미 연결된 PR의 timeline 조회, 레포별 알림 상한, 번역 공백 발굴은 이번 범위 밖이다.
구독으로 실행하므로 API 비용과 기획서 월 $10~$50 추정은 검증하지 않는다.

근거: [GitHub Issues API](https://docs.github.com/en/rest/issues/issues#list-repository-issues),
[GitHub GraphQL Issue](https://docs.github.com/en/graphql/reference/issues),
[Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode),
[설정 옵션](https://learn.chatgpt.com/docs/config-file/config-reference),
[Structured Outputs 필수 필드](https://developers.openai.com/api/docs/guides/structured-outputs),
[Luna 모델 안내](https://learn.chatgpt.com/docs/models).
로컬 옵션은 `gh api --help`, `codex exec --help`로도 확인했다.
