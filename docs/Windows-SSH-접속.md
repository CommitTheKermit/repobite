# Windows 홈 서버 SSH 접속

이 문서는 `VIVOBOOK`에서 동작하는 RepoBite 홈 서버의 현재 구성과 원격 접속 방법을 기록한다.
비밀번호, 개인키, GitHub 토큰, Google 서비스 계정 JSON은 저장소에 기록하지 않는다.

## 현재 구성

2026-09-19에 다음 상태를 확인했다.

- Windows 계정: `qnf323`
- 컴퓨터 이름: `VIVOBOOK`
- OpenSSH 서버: TCP 22에서 IPv4/IPv6 수신 중
- 인증: 공개키만 허용 (`PasswordAuthentication no`, `AuthenticationMethods publickey`)
- 허용 계정: `qnf323`
- 관리자 공개키 파일: `C:\ProgramData\ssh\administrators_authorized_keys`
- Tailscale MagicDNS: `vivobook.tail302ce0.ts.net`
- Tailscale IPv4: `100.87.16.43`
- 현재 LAN IPv4: `192.168.0.16` (DHCP에 따라 바뀔 수 있음)
- RepoBite 저장소: `C:\Users\qnf32\Documents\Codex\repobite`
- 로컬 웹: `http://127.0.0.1:8765`

Windows 방화벽은 Private 네트워크의 TCP 22와 Tailscale 인터페이스의 TCP 22를 허용한다.
공유기 포트 포워딩 없이 외부에서 접속할 때는 Tailscale을 사용한다. TCP 22를 공용 인터넷에
직접 노출하지 않는다.

## 전원 운영 방식

이 서버는 AC 전원에 계속 연결해 **항상 켜진 상태**로 운영한다. 현재 균형 조정 전원 계획에서
AC 자동 절전 시간이 `0`(사용 안 함)이므로 SSH와 Tailscale 연결은 유휴 중에도 유지된다.
유휴 시에는 Windows와 CPU가 자동으로 클록·전력을 낮추고, 03:00 배치나 SSH 작업이 시작되면
필요한 성능을 다시 사용한다. 별도의 재부팅이나 수동 전원 계획 전환을 일상 운영에 넣지 않는다.

이 기기는 S0 Modern Standby를 지원하지 않는다. 배터리 전원에서는 10분 뒤 S3 절전에 들어가고
절전 해제 타이머도 꺼져 있으므로 SSH 접속과 예약 배치를 보장하지 않는다. 홈 서버로 사용할 때는
AC 전원을 유지한다. 예약 작업의 `WakeToRun`은 켜져 있지만 AC 자동 절전을 사용하지 않으므로
평상시에는 보조 안전장치 역할만 한다.

현재 `sshd` 서비스는 실행 중이지만 시작 유형은 `Manual`이다. 상시 켜짐 운영 중에는 현재 연결에
영향이 없고 재부팅은 정기 운영 절차가 아니다. Windows 업데이트나 정전 뒤 자동 복구까지 원하면
관리자 PowerShell에서 다음을 한 번 실행한다.

```powershell
Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd
```

## 권장 접속 방법: Tailscale

접속할 컴퓨터에도 Tailscale을 설치하고 같은 Tailnet에 로그인한다. 클라이언트의 개인키는
서버의 `administrators_authorized_keys`에 등록된 공개키와 짝이 맞아야 한다.

```sh
ssh qnf323@vivobook.tail302ce0.ts.net
```

MagicDNS를 사용할 수 없으면 Tailscale IP로 접속한다.

```sh
ssh qnf323@100.87.16.43
```

처음 접속할 때 표시되는 호스트 키 지문은 다른 신뢰 가능한 경로로 서버에서 확인한 값과
대조한 뒤 승인한다. 비밀번호 입력으로 대체할 수 없으며 개인키는 서버나 저장소에 복사하지 않는다.

## 같은 LAN에서 접속

클라이언트가 서버와 같은 신뢰할 수 있는 사설 네트워크에 있을 때만 현재 LAN 주소를 사용할 수 있다.

```sh
ssh qnf323@192.168.0.16
```

LAN 주소는 공유기의 DHCP 할당에 따라 변할 수 있다. 장기 운영 시 공유기에서 `VIVOBOOK`에
DHCP 예약을 설정하거나 `ipconfig`로 현재 주소를 다시 확인한다.

## 원격에서 RepoBite 웹 열기

RepoBite 웹 서버는 보안을 위해 `127.0.0.1`에만 바인딩한다. 원격 브라우저에 직접 공개하지 않고
SSH 로컬 포트 포워딩을 사용한다.

```sh
ssh -N -L 8765:127.0.0.1:8765 qnf323@vivobook.tail302ce0.ts.net
```

터널을 유지한 상태에서 클라이언트 브라우저로 `http://127.0.0.1:8765`을 연다. 클라이언트의
8765 포트가 사용 중이면 왼쪽 포트만 바꾼다.

```sh
ssh -N -L 18765:127.0.0.1:8765 qnf323@vivobook.tail302ce0.ts.net
```

이 경우 브라우저 주소는 `http://127.0.0.1:18765`이다.

## 접속 후 운영 명령

SSH 접속 직후 PowerShell에서 저장소로 이동한다.

```powershell
Set-Location C:\Users\qnf32\Documents\Codex\repobite
git status
```

웹과 매일 배치의 상태를 확인한다.

```powershell
Get-ScheduledTask -TaskName repobite-web,repobite-batch |
    Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName repobite-batch |
    Select-Object LastRunTime,LastTaskResult,NextRunTime
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765 |
    Select-Object StatusCode
```

`LastTaskResult`가 `0`이면 마지막 배치가 성공한 것이다. 웹 작업이 실행 중일 때 표시되는
`267009` (`0x41301`)는 오류가 아니라 작업이 현재 실행 중이라는 뜻이다.

배치를 즉시 실행하거나 최근 로그를 확인한다.

```powershell
Start-ScheduledTask -TaskName repobite-batch
Get-Content "$env:LOCALAPPDATA\RepoBite\batch.log" -Tail 100
```

결과 파일은 저장소 루트의 `issues.jsonl`, `grades.jsonl`, `candidates.jsonl`이다. 이 파일들은
운영 데이터이며 Git에서 무시된다. GitHub 토큰은 `%LOCALAPPDATA%\RepoBite\github-token.clixml`에
Windows DPAPI로 암호화되어 있으며 내용이나 복호화 결과를 출력하지 않는다. Google 서비스 계정
JSON도 저장소 밖에 유지하고 `GOOGLE_APPLICATION_CREDENTIALS`에는 경로만 둔다.

## 설치·운영 작업 요약

- Python 3.14, GitHub CLI, Google Cloud SDK를 설치하고 인증했다.
- Vertex AI 서비스 계정과 `global` 리전을 사용자 환경변수로 연결했다.
- Windows에서 `gcloud.cmd`를 찾도록 실행 경로를 보완하고 Vertex 429/5xx 재시도를 추가했다.
- `repobite-web`은 시스템 시작 시, `repobite-batch`는 매일 03:00에 실행하도록 등록했다.
- 두 예약 작업은 중복 실행을 무시하고 실패 시 15분 간격으로 최대 3회 재시도한다.
- AC 전원에서는 자동 절전을 사용하지 않고 균형 조정 계획의 유휴 절전으로 상시 연결을 유지한다.
- 2026-09-19 03:00 실제 예약 실행이 종료 코드 0으로 완료되는 것을 확인했다.
- 로컬 웹은 HTTP 200, 전체 회귀 테스트와 Windows 사전 검사를 통과했다.

## 장애 확인

서버에서 다음 순서로 확인한다.

```powershell
Get-Service sshd
Get-NetTCPConnection -LocalPort 22 -State Listen
Get-NetFirewallRule | Where-Object DisplayName -Match 'SSH|OpenSSH'
tailscale status
```

- `sshd`가 중지됐으면 관리자 PowerShell에서 `Start-Service sshd`를 실행한다.
- Tailscale 접속만 실패하면 양쪽 장치의 로그인·온라인 상태와 Tailnet ACL을 확인한다.
- LAN 접속만 실패하면 현재 네트워크 프로필이 Private인지, 서버 IP가 바뀌지 않았는지 확인한다.
- `Permission denied (publickey)`이면 클라이언트가 올바른 개인키를 사용 중인지 확인한다.
- 웹 접속만 실패하면 `repobite-web` 상태와 SSH 터널의 로컬 포트를 확인한다.
