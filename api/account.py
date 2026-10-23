"""Vercel 계정 API. 로컬 서버도 handle_account로 같은 보안 경계를 사용한다."""

from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlsplit

import accounts
import collection


def cookie_value(headers, name):
    jar = SimpleCookie()
    try:
        jar.load(headers.get("Cookie", ""))
    except CookieError:
        return None
    return jar[name].value if name in jar else None


def cookie_header(name, value="", seconds=0):
    return f"{name}={value}; Path=/; Max-Age={seconds}; Secure; HttpOnly; SameSite=Lax"


def respond(request, status, payload=None, headers=()):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
    request.send_response(status)
    request.send_header("Content-Type", "application/json; charset=utf-8")
    request.send_header("Content-Length", str(len(body)))
    request.send_header("Cache-Control", "no-store")
    request.send_header("X-Content-Type-Options", "nosniff")
    request.send_header("Referrer-Policy", "no-referrer")
    for name, value in headers:
        request.send_header(name, value)
    request.end_headers()
    request.wfile.write(body)


def read_payload(request):
    if request.headers.get_content_type() != "application/json":
        raise ValueError("JSON 형식으로 입력하세요.")
    length = int(request.headers.get("Content-Length", "0"))
    if not 0 < length <= 2048:
        raise ValueError("입력 길이를 확인하세요.")
    try:
        payload = json.loads(request.rfile.read(length))
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("입력 형식을 확인하세요.") from None
    if not isinstance(payload, dict):
        raise ValueError("입력 형식을 확인하세요.")
    return payload


def handle_account(request):
    """BaseHTTPRequestHandler 호환 요청을 처리한다. 예외의 원문은 공개하지 않는다."""
    params = parse_qs(urlsplit(request.path).query, keep_blank_values=True)
    action = params.get("action", ["session"])[0]
    session = cookie_value(request.headers, accounts.SESSION_COOKIE)
    is_callback = action == "callback" and request.command == "GET"
    try:
        if any(len(values) != 1 for values in params.values()):
            raise ValueError("요청 형식을 확인하세요.")
        if request.command == "GET":
            if action == "start":
                location, state = accounts.start_login()
                respond(request, 302, headers=[("Location", location), ("Set-Cookie", cookie_header(
                    accounts.STATE_COOKIE, state, accounts.STATE_SECONDS))])
            elif action == "callback":
                if "error" in params:
                    raise accounts.AuthenticationRequired()
                secret = accounts.complete_login(params.get("code", [""])[0], params.get("state", [""])[0],
                    cookie_value(request.headers, accounts.STATE_COOKIE), previous_session=session)
                snapshot = accounts.session_snapshot(secret)
                destination = "/#/subs" if snapshot["preferences"].get("onboarding_completed") else "/#/topics"
                respond(request, 302, headers=[("Location", accounts.PUBLIC_ORIGIN + destination),
                    ("Set-Cookie", cookie_header(accounts.STATE_COOKIE)), ("Set-Cookie", cookie_header(
                        accounts.SESSION_COOKIE, secret, accounts.SESSION_SECONDS))])
            elif action == "collection":
                user = accounts.require_user(session)
                names = accounts.subscriptions(user["id"])
                jobs = collection.statuses(names)
                seen = accounts.collection_acknowledgements(user["id"], names)
                for job in jobs:
                    identity = collection.completion_id(job)
                    job.update(completion_id=identity, acknowledged=bool(identity and seen.get(job["repo"].lower()) == identity))
                if any(job["stage"] in collection.ACTIVE for job in jobs):
                    if collection.community.redis("SET", "repobite:collect:wake-limit", "1", "NX", "EX", 15) == "OK":
                        try:
                            collection.wake()
                        except (OSError, ValueError, RuntimeError):
                            pass
                respond(request, 200, {"user_id": user["id"], "jobs": jobs})
            elif action == "session":
                respond(request, 200, accounts.session_snapshot(session))
            else:
                respond(request, 404, {"error": "요청한 기능을 찾지 못했습니다."})
            return
        if request.command not in {"POST", "DELETE"}:
            respond(request, 405, {"error": "지원하지 않는 요청입니다."}, [("Allow", "GET, POST, DELETE")])
            return
        if request.headers.get("Origin") != accounts.PUBLIC_ORIGIN:
            respond(request, 403, {"error": "RepoBite 화면에서 요청하세요.", "code": "origin_rejected"})
            return
        if action == "logout" and request.command == "POST":
            accounts.logout(session)
            respond(request, 200, {"authenticated": False}, [("Set-Cookie", cookie_header(accounts.SESSION_COOKIE))])
            return
        user = accounts.require_user(session)
        payload = read_payload(request)
        if payload.get("expected_user_id") != user["id"]:
            respond(request, 409, {"error": "로그인 계정이 바뀌었습니다. 화면을 새로고침한 뒤 다시 시도하세요.",
                                   "code": "account_changed"})
            return
        if action == "preferences" and request.command == "POST":
            saved = accounts.save_preferences(user["id"], payload.get("email"), payload.get("delivery_enabled"))
            respond(request, 200, {"preferences": saved})
        elif action == "personalization" and request.command == "POST":
            saved = accounts.save_personalization(user["id"], payload.get("difficulty"),
                                                 payload.get("experience"), payload.get("topics"))
            respond(request, 200, {"preferences": saved})
        elif action == "onboarding" and request.command == "POST":
            saved = accounts.save_preferences(user["id"], payload.get("email"), payload.get("delivery_enabled"), complete=True)
            respond(request, 200, {"preferences": saved})
        elif action == "collection_seen" and request.command == "POST":
            name = collection.community.normalize_repo(payload.get("repo")).lower()
            if name not in {repo.lower() for repo in accounts.subscriptions(user["id"])}:
                raise ValueError("구독 중인 저장소의 완료 알림만 확인할 수 있습니다.")
            identity = collection.completion_id(collection.status(name))
            if not identity or identity != payload.get("completion_id"):
                raise ValueError("수집 완료 상태가 바뀌었습니다. 잠시 후 다시 확인하세요.")
            accounts.acknowledge_collection(user["id"], name, identity)
            respond(request, 200, {"repo": name, "completion_id": identity, "acknowledged": True})
        elif action == "subscriptions":
            if request.command == "POST":
                result = accounts.subscribe(user["id"], payload.get("repo"))
                result["collection"] = collection.request(result["repo"])
                respond(request, 201 if result["created"] else 200, result)
            else:
                respond(request, 200, accounts.unsubscribe(user["id"], payload.get("repo")))
        else:
            respond(request, 404, {"error": "요청한 기능을 찾지 못했습니다."})
    except accounts.AuthenticationRequired:
        if is_callback:
            respond(request, 302, headers=[("Location", accounts.PUBLIC_ORIGIN + "/?auth=failed"),
                ("Set-Cookie", cookie_header(accounts.STATE_COOKIE))])
        else:
            respond(request, 401, {"error": "GitHub 로그인이 필요합니다. 입력은 유지한 뒤 다시 시도하세요.",
                                   "code": "authentication_required"})
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, OverflowError) as error:
        if is_callback:
            respond(request, 302, headers=[("Location", accounts.PUBLIC_ORIGIN + "/?auth=failed"),
                ("Set-Cookie", cookie_header(accounts.STATE_COOKIE))])
        elif isinstance(error, OverflowError):
            respond(request, 429, {"error": str(error), "code": "rate_limited"})
        elif isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            respond(request, 400, {"error": str(error), "code": "invalid_input"})
        else:
            respond(request, 503, {"error": "계정 요청을 처리하지 못했습니다. 입력을 유지하고 잠시 후 다시 시도하세요.",
                                   "code": "service_unavailable"})


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # OAuth callback URL의 code/state가 액세스 로그에 남지 않도록 한다.
        pass

    def do_GET(self):
        handle_account(self)

    def do_POST(self):
        handle_account(self)

    def do_DELETE(self):
        handle_account(self)
