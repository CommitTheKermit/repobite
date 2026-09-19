# Windows 서버 구성 작업 이력

작업일: 2026-09-18 ~ 2026-09-19\
대상 장치: `vivobook`\
대상 저장소: `C:\Users\qnf32\Documents\Codex\flippa`

이 문서는 플리파를 Windows 노트북에서 실행하고 Mac에서 Tailscale과 SSH로 관리하기 위해
수행한 변경, 검증 결과, 미완료 항목을 기록한다. 현재 사용 절차는
[Windows 서버 원격 접속](windows-remote-access.md)을 참고한다.

## 목표

- private GitHub 저장소를 업데이트 가능한 정식 Git checkout으로 구성
- macOS 전용이던 플리파를 Windows에서도 실행
- 플리파 웹 서버는 loopback에 유지하고 Tailscale에서만 HTTPS로 접근
- Mac에서 Windows PowerShell과 저장소를 관리할 수 있도록 공개키 SSH 구성
- 노트북 절전 때문에 서버가 중단되지 않도록 AC 전원 정책 조정
- Android Studio, SDK, ADB, Emulator 준비

## 초기 상태

- OS: Windows 11 Pro 64비트
- 네트워크: Wi-Fi, 사설 네트워크
- AC 절전: 15분
- AC 최대 절전: 3시간
- Tailscale, OpenSSH Server, Android SDK 없음
- RDP 비활성화
- 작업 폴더는 Git 저장소가 아닌 빈 Codex 작업 공간
- Git CLI는 Windows Schannel 자격 증명 오류로 private 저장소를 직접 clone하지 못함

## 수행한 작업

### 1. 전원 정책

AC 전원 사용 중 자동 절전과 최대 절전을 해제했다. 화면 끄기는 서버 실행과 무관하므로 별도
변경하지 않았다.

검증값:

```text
standby-timeout-ac = 0
hibernate-timeout-ac = 0
```

배터리 전원 정책은 변경하지 않았다. 서버 운영 중에는 충전기를 연결해야 한다.

### 2. GitHub 인증과 저장소 복제

다른 서버 구성 작업에서 GitHub CLI 인증을 완료했고, 해당 자격 증명을 사용해 private 저장소를
다음 경로에 복제했다.

```text
C:\Users\qnf32\Documents\Codex\flippa
```

원격 저장소:

```text
https://github.com/CommitTheKermit/flippa.git
```

Windows Schannel 문제는 clone 명령에서만 OpenSSL TLS 백엔드를 사용해 우회했으며 전역 Git
설정은 변경하지 않았다.

### 3. Windows 호환성 수정

초기 Windows 테스트에서 Python 9개 중 3개가 CP949/UTF-8 불일치로 실패했다. 기록 파일을
UTF-8로 쓰고 Windows 기본 인코딩으로 다시 읽는 것이 원인이었다.

다음 변경을 적용했다.

- JSON, JSONL, AI 출력, Emulator discovery 파일을 명시적으로 UTF-8로 읽고 씀
- Codex CLI 표준 입력을 UTF-8로 전달
- Windows 데이터 기본 경로를 `%LOCALAPPDATA%\Plipa`로 변경
- Android SDK 기본 경로를 `%LOCALAPPDATA%\Android\Sdk`로 추가
- Windows의 `adb.exe`, `emulator.exe` 실행 파일명 지원
- `PLIPA_ORIGIN`으로 정확한 원격 HTTPS origin 하나를 허용
- 서버의 실제 바인딩은 계속 `127.0.0.1`로 유지
- Windows 실행기 `run-windows.ps1` 추가
- 원격 origin을 허용하는 HTTP 보안 테스트 추가

검증 결과:

- Python 단위 테스트: 9개 통과
- JavaScript 구문 검사: 통과
- 스트림 프레이밍 검사: 통과
- `git diff --check`: 오류 없음

### 4. 플리파 실행과 자동 시작

Windows용 가상환경 `.venv`를 만들고 고정 버전 의존성을 설치했다.

```text
grpcio 1.84.0
protobuf 7.36.1
typing-extensions 4.16.0
```

사용자 환경변수:

```text
PLIPA_ORIGIN=https://vivobook.tail302ce0.ts.net
PLIPA_DATA=C:\Users\qnf32\AppData\Local\Plipa
```

`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`의 `PlipaServer` 값으로 사용자 로그인 시
`run-windows.ps1`을 숨김 실행하도록 등록했다. 이 방식은 Windows 부팅만으로 실행되는 서비스가
아니므로 `qnf323` 사용자가 로그인해야 한다.

### 5. Tailscale과 HTTPS

Tailscale 설치와 로그인을 완료했다.

```text
장치 DNS: vivobook.tail302ce0.ts.net
Tailscale IPv4: 100.87.16.43
```

Tailscale Serve가 다음 경로를 tailnet 내부에만 공개한다.

```text
https://vivobook.tail302ce0.ts.net/
  -> http://127.0.0.1:4317
```

실제 HTTPS 요청에서 `HTTP 200`을 확인했다. Funnel과 공유기 포트 포워딩은 사용하지 않았다.

### 6. Android 도구

설치한 항목:

- Android Studio 2026.1 계열
- Android SDK
- Android Platform Tools의 ADB
- Android Emulator

확인된 경로:

```text
C:\Users\qnf32\AppData\Local\Android\Sdk\platform-tools\adb.exe
C:\Users\qnf32\AppData\Local\Android\Sdk\emulator\emulator.exe
```

AVD 생성과 실제 앱을 사용한 플리파 종단 간 검증은 아직 남아 있다.

### 7. SSH 서버

Windows용 Tailscale SSH 서버는 지원되지 않으므로 Windows OpenSSH Server를 Tailscale 네트워크
위에서 사용하도록 구성했다.

적용한 보안 설정:

- 허용 사용자: `qnf323`
- 공개키 인증만 허용
- 비밀번호 인증 비활성화
- `AuthenticationMethods publickey`
- 관리자 공개키 파일 ACL을 Administrators와 SYSTEM으로 제한
- 방화벽 22/TCP 허용 원격 주소:
  - `100.64.0.0/10`
  - `fd7a:115c:a1e0::/48`
- 기본 OpenSSH 전체 네트워크 허용 규칙은 없음

Mac `100.74.20.126`에서 실제 공개키 SSH 접속을 확인했다. 처음에는 프로필 경로
`C:\Users\qnf32`를 보고 사용자명을 `qnf32`로 잘못 지정했으나, 실제 계정명은 `qnf323`임을
서버 로그로 확인해 수정했다.

ED25519 서버 지문:

```text
SHA256:93IoYoup2+q40VBkhxpsR3NR9AFU4liTGnhkjjJRNIg
```

## 현재 주의 사항: OpenSSH 재부팅 대기

Windows 선택 기능 `OpenSSH.Server~~~~0.0.1.0` 다운로드가 장시간 50%에 머물러 공식
`Microsoft.OpenSSH.Preview` MSI로 우회 설치했다. 이후 Windows 선택 기능 설치가 백그라운드에서
뒤늦게 진행되어 현재 두 구현의 파일이 모두 존재한다.

2026-09-19 최종 점검:

```text
Windows capability: InstallPending
RebootPending: true
sshd service: Running
sshd start mode: Manual
active binary: C:\Windows\System32\OpenSSH\sshd.exe
inbox binary: present
preview binary: present
```

서비스는 현재 정상 동작하지만 Windows가 서비스를 삭제 대기 상태로 표시해 시작 유형을
`Automatic`으로 바꾸는 요청이 오류 1072로 거부됐다. 이 상태를 정리하려면 재부팅이 필요하다.
재부팅하면 현재 SSH 연결이 끊기므로 사용자가 PC 앞에 있거나 별도 복구 경로가 있을 때만 한다.

재부팅 후 확인 순서:

```powershell
Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
Get-Service sshd
sc.exe qc sshd
```

목표 상태:

```text
Capability State = Installed
sshd Status = Running
sshd START_TYPE = AUTO_START
```

서비스가 존재하고 실행되면 관리자 PowerShell에서 자동 시작을 적용한다.

```powershell
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
```

그 뒤 Mac에서 새 SSH 접속을 검증한다. Windows 기본 OpenSSH로 정상 접속되는 것을 확인하기
전에는 Preview MSI를 제거하지 않는다. 제거 여부는 사용자가 별도로 결정한다.

## 변경된 저장소 파일

| 파일 | 변경 내용 |
| --- | --- |
| `README.md` | Windows 실행 및 원격 운영 문서 링크 |
| `server.py` | UTF-8, Windows 데이터 경로, 원격 origin 검증 |
| `device.py` | Windows Android SDK와 실행 파일 경로 |
| `emulator.py` | discovery 파일 UTF-8 읽기 |
| `ai.py` | Codex 입력·출력 UTF-8 처리 |
| `test_plipa.py` | Windows UTF-8 수정과 원격 origin 회귀 검사 |
| `run-windows.ps1` | Windows 설치·실행 진입점 |
| `docs/windows-remote-access.md` | Mac 원격 운영 안내 |
| `docs/windows-setup-worklog.md` | 이 작업 이력 |

작업용 관리자 스크립트와 상태 JSON은 Codex 작업 공간의 `work` 폴더에만 있으며 저장소에는
포함하지 않았다.

## 남은 작업

1. 사용자가 PC 앞에 있을 때 Windows 재부팅
2. OpenSSH 선택 기능과 서비스 자동 시작 상태 재검증
3. Mac SSH 재접속 확인 후 중복 Preview 패키지 정리 여부 결정
4. Android AVD 생성 및 부팅
5. ADB, Emulator gRPC, 플리파 화면·입력 종단 간 검증
6. 현재 저장소 변경 검토 후 커밋·푸시

## 되돌리기 참고

Tailscale 웹 프록시 해제:

```powershell
tailscale serve --https=443 off
```

플리파 로그인 자동 실행 해제:

```powershell
Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name PlipaServer
```

SSH 방화벽 규칙 제거와 OpenSSH 패키지 제거는 원격 복구 경로가 사라질 수 있으므로 Mac SSH가
아닌 로컬 Windows 화면에서, 사용자가 명시적으로 결정한 경우에만 수행한다.
