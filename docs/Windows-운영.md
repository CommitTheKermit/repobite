> 2026-10-23 화면 개편 후속: 현재 화면·수집 정책은 [구독 즉시 수집 운영](구독-즉시수집-운영.md)을 따른다. 아래의 담기, 매일 03:00 단일 배치, 이전 온보딩·난이도 노출 설명은 당시 운영 이력이다. 최신 정책은 구독 시 단일 저장소 수집, 총 3회 시도, 6시간 정기 수집과 확정 TypeSafe 시안이다.

# Windows 운영

서버의 SSH 주소, 공개키 로그인, 원격 웹 터널과 점검 명령은
[Windows 홈 서버 SSH 접속](Windows-SSH-접속.md)에 정리했다.

Python 3.14와 GitHub CLI를 설치한 뒤 저장소에서 아래 명령을 확인한다.

```powershell
py -3.14 --version
gh auth status
py -3.14 test_radar.py
```

Vertex AI 서비스 계정 JSON은 저장소 밖에 두고 사용자 환경 변수로 경로만 지정한다.

```powershell
[Environment]::SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", "C:\안전한-외부-경로\service-account.json", "User")
[Environment]::SetEnvironmentVariable("GOOGLE_CLOUD_LOCATION", "global", "User")
```

새 PowerShell 창에서 `scripts\run-batch.ps1`을 한 번 실행해 인증과 파일 생성을 확인한다.
기본 배치는 최근 24시간 갱신 이슈를 수집하고 최대 100건을 판정한 뒤 `candidates.jsonl`에
레포당 새 후보를 최대 5건 추가한다. 기존 후보는 유지하고 같은 `repo/number`는 다시 추가하지 않는다.

관리자 PowerShell에서 다음 명령을 실행해 작업을 등록한다. 계정 암호는 작업 스케줄러 등록에만 전달하며 파일에 저장하지 않는다.
등록 스크립트는 현재 GitHub CLI 토큰을 Windows DPAPI로 암호화해 사용자 로컬 앱 데이터에 저장한다.
암호화 파일은 같은 Windows 사용자와 컴퓨터에서 실행되는 예약 작업만 복호화할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register-tasks.ps1 -BatchTime "03:00"
```

`repobite-web`은 시스템 시작 시 실행되고 `repobite-batch`는 매일 지정 시각에 실행된다.
두 작업 모두 중복 실행을 무시하고 실패 시 15분 간격으로 3회 재시도하며, 실행 시 절전 모드를 해제한다.
웹 작업은 상시 실행을 위해 실행 시간 제한을 `PT0S`로 등록한다. 배치는 기본 72시간 제한을 유지한다.
기존 웹 작업은 등록 스크립트 변경만으로 갱신되지 않는다. 암호 로그온 작업의 설정 변경에는
작업 계정 암호가 다시 필요하다. 암호 없이 `Set-ScheduledTask`를 실행하면 이 환경에서는
`0x8007052e`로 거절됐다. 계정이나 로그온 유형을 바꾸어 우회하지 않는다.
Windows 서버의 관리자 PowerShell에서 저장소 루트를 열고 아래 스크립트를 실행한다.
암호는 서버 콘솔의 보안 입력으로만 받고 채팅, 파일, 명령줄 인자에 기록하지 않는다.
스크립트는 기존 웹 작업의 실행 시간 제한만 변경하고 웹 작업을 재시작한다. 배치는 수정하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update-web-task.ps1
```

적용 후 `ExecutionTimeLimit=PT0S`, 작업 상태 `Running`, loopback 웹 `8765`와 상태 서버
`8767`의 HTTP 200을 각각 확인한다. 수동 기동 성공과 다음 부팅의 자동 기동 검증은 별개다.
배치 콘솔 로그는 `%LOCALAPPDATA%\RepoBite\batch.log`에 누적되어 예약 실행 실패 원인을 확인할 수 있다.
Python 표준 출력과 오류 출력은 PowerShell 파이프라인으로 모아 transcript에 기록하고 원래 종료 코드를 유지한다. UTF-8로 한글 원인을 보존하며, 오류 출력 자체로 Python 재시도를 중단하지 않는다.
Vertex HTTP 오류는 재시도마다 `http_status`, 상태 코드별 원인 `cause`, 시도 횟수 `attempts`,
재시도 여부 `retry`를 기록한다. 응답이 구조화된 오류를 제공하면 `api_status`와 `ErrorInfo.reason`도
기록한다. 최종 실패의 같은 진단은 `grades.jsonl`의 `error_details`에 남는다.
원문 메시지, 요청 URL, 인증 헤더, 오류 metadata와 이슈 본문은 진단 로그에 복사하지 않는다.
따라서 과거 실행의 `HTTPError`만 있는 행에서 HTTP 코드를 소급 복원할 수는 없다.
재시도 간격과 판정 일부 실패 시 후보 생성을 건너뛰는 기존 정책은 유지한다.

오류 구조 근거: [Vertex AI 오류 코드](https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/api-errors),
[Google ErrorInfo](https://docs.cloud.google.com/spanner/docs/reference/rest/v1/ErrorInfo).

작업 스케줄러에서 각 작업을 수동 실행해 종료 코드와 로컬 모드의 `issues.jsonl`, `grades.jsonl`,
`candidates.jsonl` 갱신을 확인한다. 이 서버의 일상 운영은 AC 전원에서 자동 절전을 끈 상시 켜짐
방식이며 재부팅은 정기 운영 절차가 아니다. 업데이트나 정전 뒤 복구까지 검증할 때만 사용자 허락을
받아 재부팅하고 `http://127.0.0.1:8765` 접속을 확인한다.
현재 웹 서버는 로컬 요청만 허용하므로 Host와 Origin 검사를 완화하거나 외부에 공개하지 않는다.

## 나중에 공용 DB에 연결하기

공용 DB는 Upstash Redis를 사용한다. Vercel 서버와 Windows 작업 계정의 사용자 환경변수에
같은 `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`을 설정한다.
토큰은 Windows 환경변수 설정 화면 등에서 입력하고 소스, 명령 기록, 채팅에 남기지 않는다.
이 문서와 코드 변경만으로 DB나 스케줄러가 생성되지는 않는다.

환경변수를 설정한 새 PowerShell에서 `py -3.14 community_batch.py`를 실행한다.
기존 GitHub CLI와 Vertex AI 인증도 필요하다. 배치는 주간 Trending 최대 15개와 누적 별 수 상위 15개를
매 실행 시 발굴하고 기본 `repos.txt`, 공용 등록, 개인 구독 목록과 합쳐 수집·판정한다.
발굴의 선정·실패 정책은 [저장소 자동 발굴](저장소-자동-발굴.md)을 따른다. 이후 성공한 공개 결과를 DB에 반영한다. 이 경로의 로컬 파일은 `.radar-community/`에 저장한다.
레포 등록 순간에는 수집하지 않으며, 이 명령이 성공해야 대기 상태가 해제된다.
실패하거나 DB 반영을 못 하면 종료 코드 1이며 운영 사이트의 이전 결과는 유지된다.
비공개(`private=true`)로 확인되거나 저장소 조회가 HTTP 404인 레포는 이번 실행에서만 제외하고
나머지 공개 레포 수집을 계속한다. 기본 목록·공용 등록·개인 구독은 삭제하지 않아 다음 실행에서
다시 공개 상태를 확인한다. 제외한 레포는 새 `collected_repos`, `discovered_repos`와 공개 이슈에서 뺀다.
전부 제외되면 판정 호출 없이 빈 공개 결과를 저장한다.
HTTP 401/403/429/5xx, 시간 초과, 잘못된 응답과 공개 상태 누락은 저장소 삭제로 추정하지 않는다.
이 경우 전체 배치를 실패시키고 이전 공개 결과를 유지한다.
HTTP 상태는 [GitHub CLI의 --include](https://cli.github.com/manual/gh_api) 응답 상태 행에서 읽으며
오류 메시지나 stderr의 404 문자열로 추측하지 않는다. 상태 행·헤더·오류 본문은 로그에 복사하지 않는다.

`scripts/run-batch.ps1`은 두 DB 환경변수가 모두 있으면 공용 배치를 실행하고,
모두 없으면 기존 로컬 배치를 실행한다. 하나만 있으면 설정 오류로 종료한다.
처음 등록하는 환경에서는 작업 계정에 환경변수를 설정한 다음 스케줄러를 등록한다.
이미 등록된 이 홈서버의 작업은 그대로 사용한다. wrapper가 실행 시 최신 User 환경변수를 읽으므로
DB 두 값 추가만으로 작업을 다시 등록할 필요는 없다. 입력 위치와 값의 출처는
[계정·구독 설정 절차](계정-구독-수동발송.md#4-windows-배치-계정에-db-두-값-입력)를 따른다.
동시에 하나의 배치만 실행한다. 기존 작업 설정은 중복 실행을 무시한다.

확인 순서:

1. 운영 화면에서 새 공개 레포를 등록하고 **수집 대기**를 확인한다.
2. Windows에서 배치를 실행하고 종료 코드 0을 확인한다.
3. 운영 화면을 새로고침해 해당 레포의 이슈 또는 **수집 완료 · 조건에 맞는 이슈 없음**을 확인한다.
4. 작업 스케줄러로 같은 배치를 실행해 동일한 결과를 확인한다.

DB 키는 `repobite:repos`(등록 목록), `repobite:snapshot`(마지막 공개 결과),
`repobite:registration-rate`(등록 검증 제한)이다. DB를 공개 클라이언트에 직접 연결하지 않는다.

## Windows 전달 전 사전 검증

[Windows preflight](../.github/workflows/windows.yml)는 push 시 Windows Server 2025에서 Python 3.14 회귀 테스트,
Node 24 UI 테스트, Windows PowerShell 문법과 배치 분기·작업 경로·종료 코드를 검사한다.
외부 API 인증키 없이 실행하며 실제 작업 스케줄러 등록이나 예약 실행은 하지 않는다.
실행 결과는 [GitHub Actions](https://github.com/CommitTheKermit/repobite/actions/workflows/windows.yml)에서 커밋별로 확인한다.

로컬 웹 결과는 `.radar-web/current.txt`에 마지막 성공 실행의 폴더 이름을 기록한다.
Windows 심볼릭 링크 생성 권한 없이 저장·재시작할 수 있으며 기존 Mac의 `current` 링크도 읽는다.
웹 종료는 Windows의 `taskkill /T /F`, Unix의 프로세스 그룹 종료로 하위 작업까지 정리한다.
한글 데이터는 UTF-8로 읽으며 PowerShell 5.1용 한글 스크립트는 UTF-8 BOM을 유지한다.

이 검사가 성공해도 실제 GitHub/Vertex 인증, 공용 DB 저장·운영 반영과 예약 시각 실행은
[Windows-Codex-작업계획.md](Windows-Codex-작업계획.md)에 따라 따로 검증한다. 절전·덮개 닫힘·재부팅
검증은 선택한 전원 운영 방식에 필요한 경우에만 수행한다.

## 2026-10-21 운영 수정의 검증 범위

- 웹 중단 원인: 작업 스케줄러의 72시간 실행 제한에 의한 종료 이벤트를 확인했다.
- HTTP 진단 코드와 신규 웹 등록 설정은 Windows의 Python 및 PowerShell 검사에서 통과했다. 모의 HTTP 429의 5회 시도, API 원인, 한글 원인과 비정상 종료 코드가 실제 배치 wrapper의 임시 transcript에 남는지도 검사한다. 실제 API 호출은 사용하지 않는다.
- 기존 웹 작업의 제한 변경은 암호 재입력이 없어 거절됐다. 위 스크립트의 서버 실행 후 `PT0S`를 재확인해야 한다.
- 기존 작업을 수동 시작해 `Running`, loopback 웹과 상태 서버의 HTTP 200, 내부 HTTPS 상태 응답 200을 확인했다. 현재 작업 제한은 `PT72H`다. 다음 부팅 및 다음 일일 배치 성공은 미검증이다.

암호 로그온 근거: [Task Scheduler 등록 API](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertaskdefinition).

## 2026-10-23 통합 코드 반영

- 기존 운영 체크아웃은 추적 파일 변경이 없는 `cffe3dd`였다. 기존 운영 수정 3건과 통합 브랜치의 대응 커밋은 range-diff에서 동일했다.
- Git bundle로 통합 이력을 전달하고 `codex/feature-integration`의 구현 커밋 `b32c718`로 전환했다. 기존 브랜치와 수집 데이터는 보존했다.
- 실제 운영 폴더에서 Python 3.14 회귀 12개 묶음과 `test_windows.ps1`이 통과했다. 외부 API를 호출하지 않는 검사다.
- 기존 `repobite-web` 작업을 10:44 한국시간에 재시작했다. 웹·상태 JSON·계정 세션·계정 및 기여 UI 모듈의 HTTP 200, 웹 작업 Running과 웹 Python 프로세스 1개를 확인했다. 계정·기여 UI 모듈을 새 소스와 대조해 일치했다. 내부 HTTPS 상태 조회도 200이었다. Node는 설치되어 있지 않아 Windows Node 검사는 실행하지 않았다.
- Windows 배치 실행 계정은 SSH 접속 계정과 SID가 같음을 확인했다. DB 두 변수는 User/Machine 모두 미입력이다.
- 공용 배치를 실행하거나 메일을 보내지 않았다. DB 연결과 실제 정기 배치 성공은 미검증이며, 10월 23일 03:00 기존 배치의 마지막 결과는 1이다. 다음 예약은 10월 24일 03:00 한국시간이다.
- 웹 실행 제한은 여전히 `PT72H`다. 제한 해제에는 위 `update-web-task.ps1`을 서버 관리자 콘솔에서 실행하고 계정 암호를 보안 입력해야 한다.

## 2026-10-23 Vercel 연결 검증

- 사용자가 Vercel 설정과 재배포를 완료했다. 정식 운영 주소의 새 배포 Ready, 공개 파일 HTTP 200과 로컬 파일 일치, 공용 목록 DB 읽기와 OAuth 임시 상태 저장을 확인했다.
- 실제 GitHub 로그인 왕복과 인증된 개인 구독·기여 목록 조회를 운영 브라우저에서 확인했다.
- 처음에는 Windows DB 설정이 없었다. 사용자가 Mac의 숨김 입력 도구로 두 값을 입력해 SSH로 배치 계정의 User 환경변수에 등록했다. 실제 DB 읽기와 운영 로그인 계정 저장을 홈서버에서 확인했다.
- Vercel Production Secret의 CLI 재다운로드가 불가능해 자동 전달하지 않았다. Mac 숨김 입력과 SSH 전달로 DB 두 값을 등록하는 임시 도구의 Python 문법과 Windows PowerShell 구문 검사를 통과했다. 사용자 입력 후 실제 DB 읽기·쓰기 검사와 User 저장을 완료했다.
- 기존 배치의 마지막 실행은 10월 23일 03:00, 종료 코드는 1이다. 마지막 로그에서 HTTP 429와 요청 제한 관련 문구를 확인했다. 새 DB 설정 이후 실행한 결과가 아니며 새 공용 배치의 성공 증거로 사용하지 않는다.

OAuth·DB 입력 순서는 [계정·구독 설정 절차](계정-구독-수동발송.md#외부-설정)를 따른다.

- 11:18:25 한국시간에 기존 `repobite-batch`를 수동 시작했다. 발굴 29개(Trending 14개·유명 15개), 전체 수집 저장소 57개, 이슈 1,782건이다. 판정 100건 중 85건 성공, 15건은 각각 5회 시도 후 HTTP 429와 `RESOURCE_EXHAUSTED`로 실패했다. 11:24:51 결과 파일 저장 후 작업 종료 코드는 1이었다.
- 실패 정책에 따라 DB snapshot을 저장하지 않았다. Windows DB와 정식 운영 API 모두 snapshot이 없음을 확인했다. 이는 실제 실패 실행의 증거이며 공용 배치 성공이나 공개 결과 반영 증거가 아니다. 실제 정기 시각의 성공도 미검증이다.
- 운영 브라우저에서 로그인 유지와 개인 구독 저장·새로고침 후 재조회·해지를 확인하고 원래 빈 목록으로 복원했다.

## 공용 배치 요청 집중 완화

2026-10-23 공용 배치의 기본 동시 판정 수를 4개로 제한한다. 필요하면 `py -3.14 community_batch.py --workers 2`처럼 1-16개 범위에서 실행한다. 기존 `scripts/run-batch.ps1`은 공용 배치 기본값 4개를 사용하므로 예약 작업 재등록이 필요하지 않다. 일반 CLI와 로컬 웹의 기본 동시 판정 16개는 유지한다. 성공 판정 재사용, 실행당 100건·레포당 20건 새 판정 상한, 전체 성공 때만 후보와 공개 snapshot을 반영하는 정책도 유지한다.

429 원인에 대한 고정 할당량·일시 처리 용량 구분은 미확인이다. 요청 집중 완화의 실제 효과는 운영 배치 종료 코드와 공개 API snapshot 재조회로 확인한다.

실제 적용 결과: 2026-10-23 13:12:45 한국시간에 기존 작업을 수동 실행하고 종료 코드 0을 확인했다. 새 판정 100건 성공, 기존 81건 재사용, 실패 0건, 후보 88건과 공개 이슈 1,763건이 저장됐다. Trending 14개·유명 15개와 운영 API 반영을 확인했다. 상세 증거는 [기능 통합 진행 상태](기능-통합-진행상태.md)의 공용 피드 복구 완료 절을 따른다. 다음 03:00의 실제 정기 트리거 실행과 기존 웹 제한 PT0S 영구 적용은 별개다.
