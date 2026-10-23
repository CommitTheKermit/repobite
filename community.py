"""공용 레포 목록과 공개 수집 결과. 비밀값은 서버 환경변수에서만 읽는다."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
REPOS_KEY = "repobite:repos"
SNAPSHOT_KEY = "repobite:snapshot"


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_repo(value):
    if not isinstance(value, str) or len(value) > 250:
        raise ValueError("GitHub URL 또는 owner/repo 형식으로 입력하세요.")
    value = value.strip()
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/").rstrip("/")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value)
            or value.split("/")[1] in {".", ".."}):
        raise ValueError("GitHub URL 또는 owner/repo 형식으로 입력하세요.")
    return value


def redis(*command):
    endpoint = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    try:
        url = urlsplit(endpoint)
    except ValueError:
        raise RuntimeError("공용 저장소 연결을 확인하세요.") from None
    if not token or url.scheme != "https" or not url.hostname or url.username or url.password:
        raise RuntimeError("공용 저장소 연결을 확인하세요.")
    request = Request(endpoint.rstrip("/"), data=json.dumps(command).encode(), headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            data = json.load(response)
        if "error" in data or "result" not in data:
            raise ValueError()
        return data["result"]
    except (OSError, ValueError, TypeError):
        raise RuntimeError("공용 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None


def registrations():
    rows = [json.loads(value) for value in redis("HVALS", REPOS_KEY)]
    return sorted(rows, key=lambda row: row["added_at"], reverse=True)


def feed():
    # 공개 범위는 저장소 이름 합집합뿐이다. 계정 식별자와 이메일은 반환하지 않는다.
    import accounts
    snapshot = redis("GET", SNAPSHOT_KEY)
    return {"subscribed_repos": accounts.subscription_repositories(),
            "snapshot": json.loads(snapshot) if snapshot else None}
