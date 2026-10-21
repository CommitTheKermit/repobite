"""GitHub 신원과 개인 구독. GitHub 토큰은 신원 확인 중에만 사용한다."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import community

PUBLIC_ORIGIN = "https://repobite.vercel.app"
CALLBACK_URL = PUBLIC_ORIGIN + "/api/account?action=callback"
SESSION_COOKIE = "__Host-repobite_session"
STATE_COOKIE = "__Host-repobite_oauth"
SESSION_SECONDS = 30 * 24 * 60 * 60
STATE_SECONDS = 10 * 60
USERS_KEY = "repobite:accounts:users"
PREFERENCES_KEY = "repobite:accounts:preferences"
DAILY_LIMIT = 3


class AuthenticationRequired(Exception):
    """사용자가 다시 로그인해야 한다."""


def secret_hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def valid_secret(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value) is not None


def session_key(secret):
    return "repobite:accounts:session:" + secret_hash(secret)


def state_key(secret):
    return "repobite:accounts:oauth:" + secret_hash(secret)


def subscriptions_key(user_id):
    if not isinstance(user_id, str) or not re.fullmatch(r"[1-9][0-9]*", user_id):
        raise ValueError("사용자 정보를 확인하세요.")
    return "repobite:accounts:subscriptions:" + user_id


def oauth_credentials():
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("GitHub 로그인 설정을 확인하세요.")
    return client_id, client_secret


def github_json(request):
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, ValueError, TypeError):
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from None


def start_login():
    client_id, _ = oauth_credentials()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    community.redis("SET", state_key(state), verifier, "EX", STATE_SECONDS)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    parameters = {"client_id": client_id, "redirect_uri": CALLBACK_URL, "scope": "",
                  "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return "https://github.com/login/oauth/authorize?" + urlencode(parameters), state


def complete_login(code, state, browser_state, previous_session=None):
    if (not valid_secret(state) or not valid_secret(browser_state)
            or not hmac.compare_digest(state, browser_state)
            or not isinstance(code, str) or not code or len(code) > 512):
        raise AuthenticationRequired()
    # 동일 state 재사용은 동시에 콜백이 도착해도 한 번만 허용한다.
    verifier = community.redis("EVAL", "local v=redis.call('GET',KEYS[1]); "
                               "redis.call('DEL',KEYS[1]); return v", 1, state_key(state))
    if not valid_secret(verifier):
        raise AuthenticationRequired()
    client_id, client_secret = oauth_credentials()
    exchange = Request("https://github.com/login/oauth/access_token", data=urlencode({
        "client_id": client_id, "client_secret": client_secret, "code": code,
        "redirect_uri": CALLBACK_URL, "code_verifier": verifier}).encode(), headers={
            "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "RepoBite"})
    token_result = github_json(exchange)
    token = token_result.get("access_token")
    if not isinstance(token, str) or not token or token_result.get("error"):
        raise AuthenticationRequired()
    profile = github_json(Request("https://api.github.com/user", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RepoBite",
        "Authorization": "Bearer " + token}))
    # 토큰/이메일은 계정 레코드에 넣지 않는다. 매 로그인마다 GitHub 신원을 확인한다.
    github_id, login = profile.get("id"), profile.get("login")
    if (type(github_id) is not int or github_id <= 0 or not isinstance(login, str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login)):
        raise AuthenticationRequired()
    user = {"id": str(github_id), "login": login,
            "avatar_url": f"https://avatars.githubusercontent.com/u/{github_id}?v=4"}
    community.redis("HSET", USERS_KEY, user["id"], json.dumps(user))
    secret = secrets.token_urlsafe(32)
    community.redis("SET", session_key(secret), user["id"], "EX", SESSION_SECONDS)
    if valid_secret(previous_session):
        community.redis("DEL", session_key(previous_session))
    return secret


def authenticated_user(session_secret):
    if not valid_secret(session_secret):
        return None
    user_id = community.redis("GET", session_key(session_secret))
    if not user_id:
        return None
    subscriptions_key(user_id)
    record = community.redis("HGET", USERS_KEY, user_id)
    return json.loads(record) if record else None


def preferences(user_id):
    saved = community.redis("HGET", PREFERENCES_KEY, user_id)
    return json.loads(saved) if saved else {"email": "", "delivery_enabled": False, "daily_limit": DAILY_LIMIT}


def subscriptions(user_id):
    return sorted(community.redis("HVALS", subscriptions_key(user_id)) or [], key=str.lower)


def session_snapshot(session_secret):
    user = authenticated_user(session_secret)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": user, "preferences": preferences(user["id"]),
            "subscriptions": subscriptions(user["id"])}


def require_user(session_secret):
    user = authenticated_user(session_secret)
    if not user:
        raise AuthenticationRequired()
    return user


def logout(session_secret):
    if valid_secret(session_secret):
        community.redis("DEL", session_key(session_secret))


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("이메일 주소를 확인하세요.")
    value = value.strip()
    if not value:
        return ""
    if len(value) > 254 or not value.isascii() or any(c.isspace() for c in value):
        raise ValueError("이메일 주소를 확인하세요.")
    if value.count("@") != 1:
        raise ValueError("이메일 주소를 확인하세요.")
    local, domain = value.rsplit("@", 1)
    if (len(local) > 64 or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
            or local.startswith(".") or local.endswith(".") or ".." in local
            or "." not in domain or len(domain) > 253
            or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                   for part in domain.split("."))):
        raise ValueError("이메일 주소를 확인하세요.")
    return local + "@" + domain.lower()


def save_preferences(user_id, email, delivery_enabled):
    subscriptions_key(user_id)
    email = normalize_email(email)
    if type(delivery_enabled) is not bool:
        raise ValueError("수동 이메일 수신 여부를 선택하세요.")
    if delivery_enabled and not email:
        raise ValueError("수신할 이메일 주소를 입력하세요.")
    value = {"email": email, "delivery_enabled": delivery_enabled, "daily_limit": DAILY_LIMIT}
    community.redis("HSET", PREFERENCES_KEY, user_id, json.dumps(value))
    return value


def verified_repository(value):
    name = community.normalize_repo(value)
    try:
        with urlopen(Request("https://api.github.com/repos/" + name, headers={
                "Accept": "application/vnd.github+json", "User-Agent": "RepoBite"}), timeout=10) as response:
            info = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("공개 GitHub 레포를 찾지 못했습니다. 주소를 확인하세요.") from None
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from None
    except (OSError, ValueError, TypeError):
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from None
    if not isinstance(info, dict):
        raise RuntimeError("GitHub 확인에 실패했습니다. 잠시 후 다시 시도하세요.")
    if info.get("private") is not False or not info.get("has_issues") or info.get("archived") or info.get("disabled"):
        raise ValueError("이슈 기능이 켜진 공개 레포만 구독할 수 있습니다. 보관되거나 비활성인 레포는 제외합니다.")
    return community.normalize_repo(info.get("full_name"))


def subscribe(user_id, value):
    key = subscriptions_key(user_id)
    name = community.normalize_repo(value)
    existing = community.redis("HGET", key, name.lower())
    if existing:
        return {"repo": existing, "created": False}
    # 계정별 GitHub 검증 부하 제한. 이미 구독한 레포 재요청은 이 제한을 소비하지 않는다.
    attempts = community.redis("EVAL", "local n=redis.call('INCR',KEYS[1]); "
                               "if n==1 then redis.call('EXPIRE',KEYS[1],3600) end; return n", 1,
                               "repobite:accounts:subscription-rate:" + user_id)
    if attempts > 30:
        raise OverflowError("구독 요청이 많습니다. 잠시 후 다시 시도하세요.")
    name = verified_repository(name)
    created = community.redis("EVAL", "if redis.call('HEXISTS',KEYS[1],ARGV[1])==1 then return 0 end; "
                              "if redis.call('HLEN',KEYS[1])>=300 then return -1 end; "
                              "return redis.call('HSET',KEYS[1],ARGV[1],ARGV[2])", 1, key, name.lower(), name)
    if created == -1:
        raise OverflowError("계정당 최대 300개 레포를 구독할 수 있습니다.")
    return {"repo": name, "created": bool(created)}


def unsubscribe(user_id, value):
    name = community.normalize_repo(value)
    removed = community.redis("HDEL", subscriptions_key(user_id), name.lower())
    return {"repo": name, "removed": bool(removed)}


def subscription_repositories():
    """정기 수집용 서버 내부 조회. 개인 신원이나 수신 주소를 반환하지 않는다."""
    names = {}
    for user_id in community.redis("HKEYS", USERS_KEY) or []:
        for repo in subscriptions(user_id):
            names[repo.lower()] = repo
    return sorted(names.values(), key=str.lower)


def delivery_subscribers():
    """운영자 수동 발송 초안용 서버 내부 조회. 공개 API에 연결하지 않는다."""
    recipients = []
    for user_id in community.redis("HKEYS", USERS_KEY) or []:
        saved = preferences(user_id)
        if saved.get("delivery_enabled") is True and saved.get("email"):
            recipients.append({"user_id": user_id, "email": saved["email"], "daily_limit": DAILY_LIMIT,
                               "subscriptions": subscriptions(user_id)})
    return recipients
