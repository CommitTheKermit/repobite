# oss-radar MVP

GitHub 이슈 본문을 읽고 난이도(1/2/3)와 준비도(ready/needs_info/undecided)를 독립적으로 판정하는 CLI.
Python 3.14 표준 라이브러리만 사용한다. 설치 패키지, 웹 UI, DB, 알림 발송은 없다.

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

`repos.txt`에 추적할 레포를 한 줄에 하나씩 적는다. 기본은 지시서의 9개 레포와
기획서의 기여 사례인 `Q00/ouroboros`, 총 10개다. 빈 줄과 `#` 주석을 허용한다.

- `collect`: `gh api repos/{repo}/issues`를 페이지 끝까지 읽고 PR, 담당자가 있는 이슈, 봇 작성 이슈를 제외한다. 문자열/라벨 사전 필터는 없다.
- `--since 7d`: 최근 7일 **갱신** 기준이다. 생성 시각 필터가 아니다. `24h`, `1w`도 지원한다.
- `grade`: 이슈당 `codex exec` 1회, 최대 4개 동시 호출. 기본 모델은 `gpt-5.6-luna`, 추론은 `low`다. `--model`로 변경할 수 있다.
- `report`: Markdown 교차표, Lv.1 × ready 비율, 레포 분포와 상위 3개 집중도, 사람 판정과의 이진 비교를 stdout에 출력한다.

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
`grades.jsonl`은 원본 필드에 `model, reasoning_effort, graded_at, grade`를 추가한다.
`grade` 안에 `difficulty, readiness, reason, exclude, exclude_reason`이 있다.
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
성공한 재실행은 지정한 결과 파일을 교체한다. 재개/자동 재시도는 없으며 재판정하면 다시 호출한다.
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
[Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode),
[설정 옵션](https://learn.chatgpt.com/docs/config-file/config-reference),
[Structured Outputs 필수 필드](https://developers.openai.com/api/docs/guides/structured-outputs),
[Luna 모델 안내](https://learn.chatgpt.com/docs/models).
로컬 옵션은 `gh api --help`, `codex exec --help`로도 확인했다.
