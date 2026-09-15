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

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register-tasks.ps1 -BatchTime "03:00"
```

`repobite-web`은 시스템 시작 시 실행되고 `repobite-batch`는 매일 지정 시각에 실행된다.
두 작업 모두 중복 실행을 무시하고 실패 시 15분 간격으로 3회 재시도하며, 실행 시 절전 모드를 해제한다.

작업 스케줄러에서 각 작업을 수동 실행해 종료 코드와 `issues.jsonl`, `grades.jsonl`,
`candidates.jsonl` 갱신을 확인한다. 그다음 Windows를 재부팅해 `http://127.0.0.1:8765` 접속을 확인한다.
현재 웹 서버는 로컬 요청만 허용하므로 Host와 Origin 검사를 완화하거나 외부에 공개하지 않는다.
