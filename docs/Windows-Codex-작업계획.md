# RepoBite Windows 운영 설정 및 실기 검증

이 문서는 Windows 노트북의 Codex에 그대로 전달할 작업 지시서다.

## 목표

현재 구현된 RepoBite를 Windows 노트북에서 운영 가능하게 설정하고 실제로 검증한다.

완료 조건은 다음과 같다.

1. Python, GitHub CLI, Google Cloud CLI 인증이 정상이다.
2. `radar.py batch`가 실제 GitHub 및 Vertex AI를 사용해 성공한다.
3. `issues.jsonl`, `grades.jsonl`, `candidates.jsonl`이 정상 생성된다.
4. Windows 작업 스케줄러가 웹 서버와 일일 배치를 실행한다.
5. 배치의 실제 예약 실행과 웹 서버의 재부팅 후 자동 실행을 검증한다.
6. 비밀값이나 서비스 계정 파일은 저장소와 로그에 남지 않는다.

## 대상

- 장치: 현재 Windows 노트북
- 저장소: 현재 Codex에서 연 RepoBite 저장소
- 브랜치: `feat/windows-daily-batch`
- 기준 커밋: `9fad041 feat(batch): Windows 일일 후보 수집을 추가`
- 산출물: `issues.jsonl`, `grades.jsonl`, `candidates.jsonl`
- 예약 작업: `repobite-web`, `repobite-batch`

새 브랜치를 만들지 말고 기존 `feat/windows-daily-batch` 브랜치를 재사용한다.

## 소스 우선순위

서로 충돌하면 다음 순서로 판단한다.

1. 현재 커밋의 실제 코드와 테스트
2. `docs/Windows-운영.md`
3. `README.md`
4. `handoff.md`

`handoff.md`는 구현 전 작성된 문서라 브랜치와 구현 예정 항목이 오래된 상태다. 후보 및 배치 기능을 다시 구현하지 않는다.

## 제외 범위

- 외부 네트워크 공개
- Cloudflare Tunnel 또는 공유기 포트 포워딩
- Host 또는 Origin 검사 완화
- 인증 기능 및 알림 발송
- SQLite 또는 Docker
- Cloud Run 또는 Cloud Scheduler
- `web.Application` 리팩터링
- GitHub 이슈, PR, 원격 저장소 푸시

현재 `web.Application`은 상태 조회, 프로세스 실행, 파일 저장을 함께 담당해 단일 책임 원칙을 위반한다. 이번 Windows 단일 사용자 운영 범위에서는 건드리지 않는다.

## 작업 전 확인

비밀값이나 암호 자체는 요청하지 말고 다음 항목만 사용자에게 확인한다.

1. 저장소가 있는 Windows 경로
2. 매일 배치를 실행할 현지 시각
3. Windows 작업 계정에 실제 암호가 설정되어 있는지
4. `GOOGLE_APPLICATION_CREDENTIALS` 사용자 환경 변수가 설정되어 있는지
5. 검증을 위한 재부팅을 지금 수행해도 되는지

Windows 암호, 서비스 계정 JSON 내용, 액세스 토큰을 채팅에 입력하게 하지 않는다. 암호가 필요하면 사용자가 PowerShell의 보안 입력창에 직접 입력한다.

## 1. 저장소와 브랜치 확인

```powershell
git status --untracked-files=no --short
git branch --show-current
git log -1 --oneline
git remote -v
```

- 추적 중인 미커밋 변경이 있으면 내용을 파악하고 사용자에게 보고한 뒤 중단한다.
- 브랜치가 다르면 `feat/windows-daily-batch`가 로컬에 있는지 확인하고 전환한다.
- 커밋 `9fad041`이 없으면 기능을 재작성하지 말고 저장소 전달 방법을 사용자에게 묻는다.
- 원본 환경에는 Git remote가 없었으므로 원격 브랜치가 있다고 가정하지 않는다.
- 단순 착수 점검에서는 미추적 파일을 나열하지 않는다.

필수 파일을 확인한다.

```powershell
Test-Path .\radar.py
Test-Path .\freshness.py
Test-Path .\vertex.py
Test-Path .\scripts\run-batch.ps1
Test-Path .\scripts\run-web.ps1
Test-Path .\scripts\register-tasks.ps1
Test-Path .\docs\Windows-운영.md
```

## 2. Windows 실행 환경 확인

```powershell
py -3.14 --version
git --version
gh --version
gcloud --version
node --version
Get-Command Register-ScheduledTask
Get-Command New-ScheduledTaskSettingsSet
powercfg /a
```

필수 조건은 Python 3.14, GitHub CLI, Google Cloud CLI, 유효한 GitHub 인증, Vertex AI용 Application Default Credentials, Windows ScheduledTasks PowerShell 모듈이다.

Node는 `test_web_ui.mjs`에만 필요하다. Node가 없으면 운영 자체와 분리해 보고하고 UI 회귀 테스트가 미검증임을 명시한다. 필수 도구가 없으면 사용자 승인 없이 설치하지 않는다.

## 3. 인증과 비밀값 확인

서비스 계정 JSON은 저장소 밖에 있어야 한다. 파일 내용이나 전체 경로를 출력하지 않는다.

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = [Environment]::GetEnvironmentVariable(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "User"
)
$env:GOOGLE_CLOUD_LOCATION = [Environment]::GetEnvironmentVariable(
    "GOOGLE_CLOUD_LOCATION",
    "User"
)

if (-not $env:GOOGLE_APPLICATION_CREDENTIALS) {
    throw "GOOGLE_APPLICATION_CREDENTIALS 사용자 환경 변수가 없습니다."
}
if (-not (Test-Path -LiteralPath $env:GOOGLE_APPLICATION_CREDENTIALS)) {
    throw "서비스 계정 파일을 찾을 수 없습니다."
}
if ($env:GOOGLE_CLOUD_LOCATION -ne "global") {
    throw "GOOGLE_CLOUD_LOCATION은 global이어야 합니다."
}
```

서비스 계정 파일이 저장소 내부에 있으면 중단하고 저장소 밖으로 옮기도록 안내한다. 파일 내용은 읽거나 출력하지 않는다.

```powershell
gh auth status
gcloud auth application-default print-access-token *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Vertex AI ADC 인증 확인에 실패했습니다."
}
```

ADC 토큰은 화면이나 로그에 출력하지 않는다. `.gitignore`에 `.env`, `.env.*`, `*.jsonl`, `*.tmp`, `.radar-web/`이 유지되는지도 확인한다.

## 4. 네트워크 없는 회귀 테스트

```powershell
py -3.14 test_radar.py
py -3.14 test_freshness.py
py -3.14 test_vertex.py
py -3.14 test_web.py
node test_web_ui.mjs
```

하나라도 실패하면 작업 스케줄러를 등록하지 않는다. 전체 오류와 관련 호출 경로를 확인하고 공통 원인을 가장 작은 위치에서 수정한다. Windows 호환성 수정에는 최소 재현 테스트를 남기고 전체 테스트를 다시 실행한다.

파일이 변경되면 같은 브랜치에 Conventional Commits 형식의 한글 커밋을 남긴다. 기존 기능과 무관한 리팩터링이나 새 의존성은 추가하지 않는다.

## 5. 실제 배치 실행

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-batch.ps1
$LASTEXITCODE
```

종료 코드가 0인지 확인한다. 파일 내용 대신 존재 여부, 크기, 갱신 시각만 출력한다.

```powershell
Get-Item .\issues.jsonl, .\grades.jsonl, .\candidates.jsonl |
    Select-Object Name, Length, LastWriteTime
```

JSONL 형식과 후보 중복을 검사한다.

```powershell
py -3.14 -c "import radar; from pathlib import Path; files=('issues.jsonl','grades.jsonl','candidates.jsonl'); rows={p:radar.read_jsonl(Path(p)) for p in files}; candidates=rows['candidates.jsonl']; assert len(candidates)==len({radar.issue_key(r) for r in candidates}); print({p:len(v) for p,v in rows.items()})"
```

후보 조건은 판정 성공, `exclude=false`, `difficulty=1`, `readiness=ready`, `freshness.eligible=true`, 같은 `repo/number` 중복 없음이다. 한 실행에서 레포당 새 후보를 최대 5건 추가하고 기존 후보 이력은 유지한다.

배치가 실패하면 후보 생성까지 성공했다고 보고하지 않는다. 오류 분류와 중단 단계를 확인한다.

## 6. 기존 예약 작업 확인

```powershell
Get-ScheduledTask -TaskName "repobite-web" -ErrorAction SilentlyContinue
Get-ScheduledTask -TaskName "repobite-batch" -ErrorAction SilentlyContinue
```

기존 작업이 있으면 `register-tasks.ps1`의 `-Force`가 덮어쓰므로 사용자에게 확인받기 전까지 등록하지 않는다.

## 7. 작업 스케줄러 등록

관리자 PowerShell에서 실행한다. 시각은 사용자가 확정한 값으로 바꾼다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register-tasks.ps1 -BatchTime "03:00"
```

스크립트가 Windows 작업 계정 암호를 요청하면 사용자가 PowerShell 창에 직접 입력한다. Codex 채팅이나 문서에 암호를 적지 않는다.

```powershell
Get-ScheduledTask -TaskName "repobite-web" |
    Select-Object TaskName, State, Triggers, Settings
Get-ScheduledTask -TaskName "repobite-batch" |
    Select-Object TaskName, State, Triggers, Settings
```

필수 설정은 다음과 같다.

- 웹: 시스템 시작 트리거
- 배치: 매일 확정 시각 트리거
- 중복 실행 무시
- 실패 시 15분 간격으로 3회 재시도
- 놓친 실행을 가능한 즉시 시작
- 실행 시 절전 해제 허용

## 8. 예약 배치 실검증

수동 스크립트 실행만으로 예약 실행을 검증했다고 판단하지 않는다. 사용자 동의를 받고 확정 시각까지 기다리거나, 임시로 3분 뒤 시각에 등록해 자동 실행을 확인한 다음 최종 시각으로 되돌린다.

검증 중 60초 이상 상태 갱신 없이 기다리지 않는다.

```powershell
Get-ScheduledTaskInfo -TaskName "repobite-batch" |
    Select-Object LastRunTime, LastTaskResult, NextRunTime
Get-Item .\issues.jsonl, .\grades.jsonl, .\candidates.jsonl |
    Select-Object Name, Length, LastWriteTime
```

임시 시각을 사용했다면 자동 실행 성공 후 최종 시각으로 다시 등록한다.

## 9. 웹 서버 수동 검증

```powershell
Start-ScheduledTask -TaskName "repobite-web"
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName "repobite-web" |
    Select-Object TaskName, State
Invoke-WebRequest http://127.0.0.1:8765 -UseBasicParsing |
    Select-Object StatusCode
```

작업 상태가 실행 중이고 HTTP 상태 코드가 200이어야 한다. 외부 주소로 접속하거나 Host와 Origin 검사를 완화하지 않는다.

## 10. 재부팅 후 자동 시작 검증

재부팅 직전에 반드시 사용자에게 명시적인 허락을 받는다. 모든 파일 변경이 커밋되었거나 작업 트리가 깨끗하고 사용자 작업이 저장됐는지 확인한 다음 재부팅한다.

재부팅 후 같은 저장소에서 Codex를 다시 열고 다음을 실행한다.

```powershell
Get-ScheduledTaskInfo -TaskName "repobite-web" |
    Select-Object LastRunTime, LastTaskResult
Get-ScheduledTask -TaskName "repobite-web" |
    Select-Object TaskName, State
Invoke-WebRequest http://127.0.0.1:8765 -UseBasicParsing |
    Select-Object StatusCode
```

웹 서버 작업이 실행 중이고 HTTP 200을 반환해야 완료다.

## 11. 최종 Git 상태

```powershell
git status --untracked-files=no --short
git branch --show-current
git log -1 --oneline
```

Windows 호환성 수정이 있었다면 테스트한 뒤 즉시 한 커밋으로 남긴다.

```text
fix(windows): 예약 실행 호환성을 수정
```

비밀값, `.env`, 서비스 계정 JSON, JSONL 실행 결과는 커밋하지 않는다.

## 완료 보고

- 현재 브랜치와 마지막 커밋
- 설치 및 확인한 도구 버전
- 통과한 테스트
- 실제 배치 종료 코드
- JSONL별 행 수
- 예약 작업의 트리거와 설정
- 예약 배치의 `LastRunTime`, `LastTaskResult`
- 재부팅 후 웹 작업 상태와 HTTP 상태 코드
- 발생한 Windows 전용 수정과 커밋
- 남은 미검증 항목

실행하지 않은 항목을 완료했다고 말하지 않는다.
