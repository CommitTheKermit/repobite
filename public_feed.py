"""로컬 웹과 공용 배치가 함께 사용하는 공개 이슈 변환."""

import radar

REPO_CATALOG = {
    "THU-MAIC/OpenMAIC": ("멀티 에이전트 학습 서비스", ("ai-ml", "agents-automation")),
    "volcengine/OpenViking": ("AI 에이전트용 컨텍스트 데이터베이스", ("ai-ml", "search-knowledge")),
    "github/github-mcp-server": ("GitHub 공식 MCP 서버", ("agents-automation", "dev-tools")),
    "ml-explore/mlx": ("Apple Silicon용 배열·머신러닝 프레임워크", ("ai-ml",)),
    "mlc-ai/web-llm": ("브라우저 LLM 추론 엔진", ("ai-ml", "web-framework")),
    "cactus-compute/needle": ("소형 기기용 파운데이션 모델", ("ai-ml",)),
    "vbenjs/vue-vben-admin": ("Vue 관리자 화면 템플릿", ("web-framework", "ui-design-system")),
    "withastro/astro": ("콘텐츠 중심 웹 프레임워크", ("web-framework",)),
    "unovue/reka-ui": ("Vue용 접근성 UI 프리미티브", ("web-framework", "ui-design-system")),
    "honojs/hono": ("웹 표준 기반 서버 프레임워크", ("web-framework", "backend-api")),
    "better-auth/better-auth": ("인증 프레임워크", ("web-framework", "security-identity")),
    "dragonflydb/dragonfly": ("인메모리 데이터베이스", ("database", "backend-api")),
    "asciimoo/hister": ("개인 검색 엔진", ("search-knowledge",)),
    "semantica-agi/semantica": ("AI 컨텍스트 그래프 인프라", ("ai-ml", "search-knowledge")),
    "ghostty-org/ghostty": ("GPU 가속 터미널", ("ide-terminal", "desktop-app")),
    "lightpanda-io/browser": ("자동화용 헤드리스 브라우저", ("dev-tools",)),
    "neurosnap/zmx": ("터미널 세션 연결·분리 도구", ("ide-terminal", "dev-tools")),
    "henrygd/beszel": ("경량 서버 모니터링", ("observability", "infra-cloud")),
    "superradcompany/microsandbox": ("로컬 우선 microVM 런타임", ("infra-cloud", "dev-tools")),
    "Tencent/AI-Infra-Guard": ("AI 보안 스캔 플랫폼", ("ai-ml", "security-identity")),
    "glanceapp/glance": ("셀프호스팅 피드 대시보드", ("observability", "infra-cloud")),
    "gtsteffaniak/filebrowser": ("웹 파일 관리자", ("dev-tools", "productivity")),
    "bookorbit/bookorbit": ("독서·라이브러리 관리 서비스", ("productivity", "desktop-app")),
    "AprilNEA/OpenLogi": ("Logitech 장치 설정 앱", ("desktop-app",)),
    "OpenWhispr/openwhispr": ("로컬·클라우드 음성 받아쓰기 앱", ("media-creative", "desktop-app")),
    "TNT-Likely/BeeCount": ("크로스플랫폼 가계부", ("productivity", "mobile")),
    "debpalash/VoiceStudio": ("음성 생성·편집 도구", ("media-creative", "desktop-app")),
    "tt-a1i/archify": ("아키텍처 다이어그램 에이전트 스킬", ("agents-automation", "dev-tools")),
}


def public_items(issues, rows):
    grades = {radar.issue_key(row): row for row in rows}
    items = []
    for issue in issues:
        row = grades.get(radar.issue_key(issue), {})
        if any(row.get(key) != issue.get(key) for key in ("title", "body")):
            row = {}
        description, categories = REPO_CATALOG.get(issue["repo"], ("카테고리 미정 레포지토리", ()))
        items.append({"repo": issue["repo"], "number": issue["number"],
                      "title": issue["title"], "url": issue["url"],
                      "created_at": issue["created_at"], "user": issue.get("user", ""),
                      "description": description,
                      "repository_image": issue.get("repository_image", ""),
                      "categories": list(categories), "grade": row.get("grade"),
                      "error": row.get("error"), "model": row.get("model"),
                      "freshness": row.get("freshness"),
                      "criteria_version": row.get("criteria_version")})
    return items

