# RepoBite Windows 서버 전환과 다음 구현 계획

## 프로젝트 위치 / 브랜치
- 경로: `/Users/ujeonghyeon/Desktop/dev/myDev/repobite`
- 브랜치: `docs/windows-server-handoff`
- 커밋 규칙: 새 작업은 새 브랜치에서 시작하고, 프롬프트 단위로 Conventional Commits 형식의 한글 커밋을 남긴다. 비밀값과 서명 트레일러는 커밋하지 않는다.

## 무엇을 만드는가
트렌드 중심 GitHub 레포 30개의 이슈를 수집하고 Vertex AI로 초보자 적합성을 판정해 추천 후보를 제공하는 웹 서비스다.
다음 구현은 새 추천 후보를 중복 없이 기록하고, Windows 노트북이 매일 한 번 자동으로 수집부터 후보 생성까지 수행하도록 만든다.
GCP는 `gemini-3.1-flash-lite` 판정 API에만 사용하고 웹 서버, 스케줄러, 데이터는 Windows 노트북에서 운영한다.

## 이번 작업에서 확정한 결정 (중요)
- Mac 로컬 MVP에서 항상 켜둘 수 있는 Windows 노트북 서버로 방향을 바꾼다.
- Cloud Run, Cloud Scheduler, GCP 영속 저장소는 사용하지 않는다. Vertex AI만 GCP에 남긴다.
- 첫 자동화는 기존 Python 표준 라이브러리 코드, JSONL 원자적 저장, 판정 재사용을 그대로 쓴다. SQLite와 Docker는 다중 사용자 요구가 확정되기 전까지 추가하지 않는다.
- Windows 작업 스케줄러에 시작 시 웹 서버 실행 작업과 매일 배치 작업을 각각 등록하는 구성이 가장 작은 운영 단위다.
- 외부 공개 방식은 미확정이다. Cloudflare Tunnel 또는 공유기 포트 포워딩을 배포 단계에서 결정한다.
- 현재 웹은 로컬 Host와 Origin만 허용하므로 인증 없이 외부에 공개하면 안 된다.

## 재사용할 코어 / 건드리지 말 것
- `radar.py` - 수집, 실행당 100건과 레포당 20건 제한, 16개 병렬 판정, 성공 판정 재사용, 리포트 집계를 재사용한다.
- `freshness.py` - 추천 직전 열린 상태, 담당자, 연결된 열린 PR 검사를 재사용한다.
- `vertex.py` - `GOOGLE_APPLICATION_CREDENTIALS` 서비스 계정 인증과 Vertex AI JSON 판정을 재사용한다. 키 파일 경로나 내용을 코드에 넣지 않는다.
- `web.py`, `web.html` - 현재 로컬 웹 흐름을 보존한다. 공개 전에는 `local_request` 보안 검사를 완화하지 않는다.
- `repos.txt` - 검증한 트렌드 중심 기본 30개 목록을 유지한다.
- `docs/Gemini-표본30-실측.md`, `docs/일반-모집단-품질-실측.md` - 모델 품질 기준선이므로 덮어쓰지 않는다.

## 현재 상태
- 변경: 기능 변경은 `02755b5`, `49e726a`, `692b1b0`에 커밋됐다. 핸드오프 작성 전 워킹트리는 깨끗했다.
- 빌드: 별도 빌드 단계 없음. Python 3.14 표준 라이브러리 기반이다.
- 테스트: `python3.14 test_vertex.py`, `python3.14 test_radar.py`, `python3.14 test_web.py`, `node test_web_ui.mjs` 통과. 서비스 계정으로 Vertex AI 실제 1회 호출 성공.
- 실측: 고정 표본 30건 중 27건 판정 성공, 최신 상태 확인 후 최종 추천 1건.
- 의존성: 새 Python 패키지 없음. 로컬 실행에는 Python 3.14, `gh`, `gcloud`, 유효한 GitHub 인증과 Vertex AI 서비스 계정이 필요하다.
- 객체지향 문제: `web.Application`이 상태 조회, 프로세스 실행, 파일 저장을 함께 맡아 단일 책임 원칙을 위반한다. Windows 단일 사용자 단계에서는 유지하고 다중 사용자 저장소를 도입할 때 분리한다.

## 다음에 할 일 (구현 단계)
1. `radar.py`, `test_radar.py` - `candidates` 명령을 추가한다. 성공 판정이며 `exclude=false`, `difficulty=1`, `readiness=ready`, `freshness.eligible=true`인 행만 받는다. `repo/number`를 키로 기존 후보를 재사용해 새 후보만 원자적으로 기록한다. 레포당 후보 상한 값은 구현 전에 사용자에게 확인한다.
2. `radar.py`, `test_radar.py` - `batch` 명령 하나로 최근 이슈 수집, 제한 판정, 최신성 확인, 후보 생성을 순서대로 실행한다. 기존 함수와 파일 경로 옵션을 재사용하고 중간 실패 시 0이 아닌 종료 코드를 반환한다.
3. Windows 실행 스크립트와 운영 문서 - 저장소 밖의 `GOOGLE_APPLICATION_CREDENTIALS`와 GitHub 인증을 사용해 `python radar.py batch`를 실행하는 PowerShell 스크립트를 만든다. 비밀값은 스크립트나 저장소에 기록하지 않는다.
4. Windows 작업 스케줄러 설정 - 웹 서버는 시스템 시작 시, 배치는 매일 한 번 실행한다. 중복 실행 금지, 실패 재시도, 절전 해제 조건을 설정하고 실제 재부팅과 예약 실행을 검증한다.
5. 외부 공개 전 보안 결정 - 공유 대상이 한 명인지 여러 사용자인지 확인한 뒤 인증, HTTPS, Host와 Origin 정책을 설계한다. 그 후 Cloudflare Tunnel 또는 직접 포트 공개 중 하나를 적용한다.
6. 실제 알림 발송 - 후보 생성과 자동 배치가 안정화된 뒤 채널을 정하고 구현한다.

## 제약 / 함정
- 제공된 서비스 계정 키는 저장소 밖에서 `600` 권한으로 관리 중이다. 핸드오프에는 경로나 비밀값을 기록하지 않는다.
- Windows 환경의 Python, `gh`, `gcloud`, 작업 스케줄러, 절전 설정은 아직 미검증이다.
- `web.py`는 `127.0.0.1`에만 바인딩하고 로컬 Host와 Origin만 허용한다. 현재 상태로는 다른 기기에서 접속할 수 없다.
- `.radar-web/`과 `*.jsonl`은 Git에서 제외된다. Windows 디스크 백업은 자동 배치가 안정화된 뒤 추가한다.
- [GitHub Actions 예약 실행](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)은 부하가 높을 때 지연되거나 일부 작업이 누락될 수 있어 주 실행기로 선택하지 않았다.
- 외부 공개와 다중 사용자 저장은 이번 다음 단계의 제외 범위다. 먼저 단일 Windows 서버에서 후보 생성과 매일 배치를 검증한다.
