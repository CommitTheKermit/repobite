# Windows 운영

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
배치 콘솔 로그는 `%LOCALAPPDATA%\RepoBite\batch.log`에 누적되어 예약 실행 실패 원인을 확인할 수 있다.

작업 스케줄러에서 각 작업을 수동 실행해 종료 코드와 로컬 모드의 `issues.jsonl`, `grades.jsonl`,
`candidates.jsonl` 갱신을 확인한다. 그다음 Windows를 재부팅해 `http://127.0.0.1:8765` 접속을 확인한다.
현재 웹 서버는 로컬 요청만 허용하므로 Host와 Origin 검사를 완화하거나 외부에 공개하지 않는다.

## 나중에 공용 DB에 연결하기

공용 DB는 Upstash Redis를 사용한다. Vercel 서버와 Windows 작업 계정의 사용자 환경변수에
같은 `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`을 설정한다.
토큰은 Windows 환경변수 설정 화면 등에서 입력하고 소스, 명령 기록, 채팅에 남기지 않는다.
이 문서와 코드 변경만으로 DB나 스케줄러가 생성되지는 않는다.

환경변수를 설정한 새 PowerShell에서 `py -3.14 community_batch.py`를 실행한다.
기존 GitHub CLI와 Vertex AI 인증도 필요하다. 배치는 기본 `repos.txt`와 공용 등록 목록을 합쳐
수집·판정하고, 성공한 공개 결과를 DB에 반영한다. 이 경로의 로컬 파일은 `.radar-community/`에 저장한다.
레포 등록 순간에는 수집하지 않으며, 이 명령이 성공해야 대기 상태가 해제된다.
실패하거나 DB 반영을 못 하면 종료 코드 1이며 운영 사이트의 이전 결과는 유지된다.
등록 후 비공개 전환이나 삭제 등으로 한 레포 조회가 실패해도 현재 배치는 전체 실패하므로
운영자가 DB의 해당 등록과 기본 목록을 확인한 뒤 다시 실행한다.

`scripts/run-batch.ps1`은 두 DB 환경변수가 모두 있으면 공용 배치를 실행하고,
모두 없으면 기존 로컬 배치를 실행한다. 하나만 있으면 설정 오류로 종료한다.
작업 계정에 환경변수를 설정한 다음 스케줄러를 등록하고 실제 실행을 확인한다.
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

이 검사가 성공해도 실제 GitHub/Vertex 인증, 공용 DB 저장·운영 반영, 예약 시각 실행,
절전·덮개 닫힘·재부팅 후 동작은 [Windows-Codex-작업계획.md](Windows-Codex-작업계획.md)에 따라 따로 검증한다.
