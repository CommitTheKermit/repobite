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
    rows = registrations()
    snapshot = redis("GET", SNAPSHOT_KEY)
    return {"repos": rows, "snapshot": json.loads(snapshot) if snapshot else None}


def register(value):
    name = normalize_repo(value)
    existing = redis("HGET", REPOS_KEY, name.lower())
    if existing:
        return {"repo": json.loads(existing), "created": False}
    # ponytail: 서비스 전체 시간당 30회 검증. 이용량이 늘면 IP별 제한과 봇 검증으로 전환.
    allowed = redis("EVAL", "local n=redis.call('INCR',KEYS[1]); "
                    "if n==1 then redis.call('EXPIRE',KEYS[1],3600) end; return n", 1,
                    "repobite:registration-rate")
    if allowed > 30:
        raise OverflowError("지금은 등록 요청이 많습니다. 잠시 후 다시 시도하세요.")
    request = Request(f"https://api.github.com/repos/{name}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RepoBite"})
    try:
        with urlopen(request, timeout=10) as response:
            info = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("공개 GitHub 레포를 찾지 못했습니다. 주소를 확인하세요.") from None
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from None
    except (OSError, ValueError):
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from None
    if info.get("private") is not False or not info.get("has_issues") or info.get("archived"):
        raise ValueError("이슈 기능이 켜져 있는 공개 레포만 추가할 수 있습니다. 보관된 레포는 제외합니다.")
    name = normalize_repo(info["full_name"])
    defaults = {line.split("#", 1)[0].strip().lower()
                for line in (ROOT / "repos.txt").read_text(encoding="utf-8").splitlines()}
    row = {"repo": name, "description": (info.get("description") or "")[:300],
           "added_at": timestamp()}
    if name.lower() in defaults:
        return {"repo": row, "created": False, "default": True}
    # 등록 중복과 상한은 동시에 여러 요청이 와도 DB 안에서 판정한다.
    result = redis("EVAL", "if redis.call('HEXISTS',KEYS[1],ARGV[1])==1 then return 0 end; "
                   "if redis.call('HLEN',KEYS[1])>=300 then return -1 end; "
                   "return redis.call('HSET',KEYS[1],ARGV[1],ARGV[2])", 1,
                   REPOS_KEY, name.lower(), json.dumps(row, ensure_ascii=False))
    if result == -1:
        raise OverflowError("공용 수집 목록이 가득 찼습니다. 나중에 다시 시도하세요.")
    if result == 0:
        row = json.loads(redis("HGET", REPOS_KEY, name.lower()))
    return {"repo": row, "created": bool(result)}
