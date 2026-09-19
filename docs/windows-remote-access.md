# Windows 서버 원격 접속

이 문서는 Mac에서 Windows 서버 `vivobook`에 접속해 플리파를 관리하는 절차를 정리한다.

## 접속 정보

| 항목 | 값 |
| --- | --- |
| Windows SSH 사용자 | `qnf323` |
| Tailscale 호스트명 | `vivobook.tail302ce0.ts.net` |
| Tailscale IPv4 | `100.87.16.43` |
| 플리파 HTTPS | `https://vivobook.tail302ce0.ts.net` |
| 플리파 저장소 | `C:\Users\qnf32\Documents\Codex\flippa` |
| 플리파 데이터 | `C:\Users\qnf32\AppData\Local\Plipa` |
| ED25519 호스트 키 지문 | `SHA256:93IoYoup2+q40VBkhxpsR3NR9AFU4liTGnhkjjJRNIg` |

Windows 사용자명은 `qnf323`이지만 사용자 프로필 폴더명은 `qnf32`다. 경로에 사용자명을
대입하지 말고 위 표의 전체 경로를 사용한다.

## Mac에서 접속

Mac에서 Tailscale을 켜고 Windows PC와 같은 tailnet에 로그인한다. 공개키 파일을 명시해
다른 키가 잘못 선택되는 것을 막는다.

```bash
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes qnf323@vivobook.tail302ce0.ts.net
```

MagicDNS 이름을 찾지 못하면 Tailscale IP로 접속한다.

```bash
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes qnf323@100.87.16.43
```

최초 접속에서는 표시된 ED25519 지문이 위 표의 값과 같은지 확인한 뒤에만 승인한다.
접속 직후 기본 셸은 `cmd.exe`다. PowerShell이 필요하면 다음을 실행한다.

```cmd
powershell
```

저장소로 이동하려면 다음을 실행한다.

```powershell
Set-Location 'C:\Users\qnf32\Documents\Codex\flippa'
```

## Mac에서 이 문서 확인

SSH 접속 후 PowerShell에서 읽는다.

```powershell
Get-Content -Raw -Encoding UTF8 'C:\Users\qnf32\Documents\Codex\flippa\docs\windows-remote-access.md'
```

Mac으로 복사해 로컬 편집기로 보려면 Mac 터미널에서 실행한다.

```bash
scp -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes \
  qnf323@vivobook.tail302ce0.ts.net:C:/Users/qnf32/Documents/Codex/flippa/docs/windows-remote-access.md \
  ./windows-remote-access.md
```

## 상태 확인

Windows PowerShell에서 SSH와 Tailscale 서비스를 확인한다.

```powershell
Get-Service sshd, Tailscale | Format-Table Name, Status, StartType
tailscale status
```

플리파 서버와 Tailscale Serve를 확인한다.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 4317
tailscale serve status
curl.exe -sS -o NUL -w "HTTP %{http_code}`n" https://vivobook.tail302ce0.ts.net/
```

정상 상태는 다음과 같다.

- `sshd`: `Running`, `Automatic`
- `Tailscale`: `Running`, `Automatic`
- `127.0.0.1:4317`: 플리파가 수신 중
- Tailscale Serve: HTTPS 주소를 `http://127.0.0.1:4317`로 프록시
- HTTPS 확인: `HTTP 200`

Android 도구 위치는 다음과 같다.

```powershell
Test-Path "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
Test-Path "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe"
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices -l
& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -list-avds
```

## 플리파 실행

저장소에서 포그라운드로 실행하고 로그를 직접 보려면 다음을 사용한다.

```powershell
Set-Location 'C:\Users\qnf32\Documents\Codex\flippa'
.\run-windows.ps1
```

현재 사용자 로그인 시 다음 시작 항목이 플리파를 자동 실행한다.

```powershell
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PlipaServer
```

따라서 Windows가 재부팅된 뒤에는 `qnf323` 사용자가 로그인해야 플리파가 시작된다. 반면
Tailscale과 OpenSSH는 Windows 서비스로 자동 시작한다.

## 저장소 관리

변경 사항을 확인한 뒤에만 업데이트한다.

```powershell
Set-Location 'C:\Users\qnf32\Documents\Codex\flippa'
git status --short --branch
git fetch origin
git log --oneline --decorate HEAD..origin/main
```

작업 트리가 깨끗하고 원격 커밋을 확인한 경우에만 다음을 실행한다.

```powershell
git pull --ff-only
```

## 보안 구성

- SSH는 공개키 인증만 허용하며 비밀번호 인증은 비활성화했다.
- SSH 로그인 사용자는 `qnf323`만 허용한다.
- Windows 방화벽은 SSH 22번 포트를 Tailscale 주소 대역에서만 허용한다.
- 플리파는 `127.0.0.1:4317`에만 바인딩하고 Tailscale Serve가 HTTPS를 종료한다.
- Tailscale Funnel과 공유기 포트 포워딩은 사용하지 않는다.
- 개인키, 비밀번호, 토큰은 이 저장소나 문서에 기록하지 않는다.

## 문제 해결

### 호스트명을 찾지 못함

명령에 Markdown 링크 형식, `http://`, 대괄호가 들어가지 않았는지 확인한다. 호스트명은
`vivobook`이며 `vibobook`이 아니다. Tailscale 연결을 확인한 뒤 IP 주소로도 시도한다.

```bash
tailscale ping vivobook
ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes qnf323@100.87.16.43
```

### `Permission denied (publickey)`

사용자명이 `qnf323`인지 확인하고 등록한 키를 명시한다.

```bash
ssh -vv -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes qnf323@vivobook.tail302ce0.ts.net
```

`Offering public key` 뒤에 `Server accepts key`가 표시되는지 확인한다. 개인키 파일 권한도
확인한다.

```bash
chmod 600 ~/.ssh/id_ed25519
```

### 호스트 키가 변경됐다는 경고

경고를 무시하거나 `known_hosts`를 바로 삭제하지 않는다. Windows에서 현재 호스트 키 지문을
다시 확인한 뒤 기존 문서의 지문과 변경 이유를 검증한다.

### 플리파 웹 화면이 열리지 않음

SSH 접속이 된다면 Windows PowerShell에서 포트와 Serve 상태를 확인한다.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 4317 -ErrorAction SilentlyContinue
tailscale serve status
```

포트가 없으면 저장소에서 `run-windows.ps1`을 실행하고 오류 메시지를 확인한다.
