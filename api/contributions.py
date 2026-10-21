"""개인 기여 API. 계정 변경과 다른 출처의 쓰기를 거부한다."""

from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlsplit

import accounts
from api.account import cookie_value, read_payload, respond
import contribution_tracking as contributions


def handle_contributions(request):
    try:
        params = parse_qs(urlsplit(request.path).query, keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()):
            raise ValueError("요청 형식을 확인하세요.")
        if request.command not in {"GET", "POST"}:
            respond(request, 405, {"error": "지원하지 않는 요청입니다."}, [("Allow", "GET, POST")])
            return
        if request.command == "POST" and request.headers.get("Origin") != accounts.PUBLIC_ORIGIN:
            respond(request, 403, {"error": "RepoBite 화면에서 요청하세요.", "code": "origin_rejected"})
            return
        user = accounts.require_user(cookie_value(request.headers, accounts.SESSION_COOKIE))
        if request.command == "GET":
            if params.get("expected_user_id", [None])[0] != user["id"]:
                respond(request, 409, {"error": "로그인 계정이 변경됐습니다. 기록을 다시 확인하세요.",
                                       "code": "account_changed"})
                return
            respond(request, 200, contributions.user_contributions(user["id"]))
            return
        payload = read_payload(request)
        if payload.get("expected_user_id") != user["id"]:
            respond(request, 409, {"error": "로그인 계정이 변경됐습니다. 기록을 다시 확인하세요.",
                                   "code": "account_changed"})
            return
        if set(payload) - {"expected_user_id", "event_id", "repo", "number", "pr_url", "delivery_id"}:
            raise ValueError("지원하지 않는 입력이 있습니다.")
        result = contributions.record_event(user["id"], params.get("action", [""])[0],
            payload.get("repo"), payload.get("number"), payload.get("event_id"), payload.get("pr_url"), payload.get("delivery_id"))
        respond(request, 200, result)
    except accounts.AuthenticationRequired:
        respond(request, 401, {"error": "GitHub 로그인이 필요합니다. 입력을 유지하고 다시 시도하세요.",
                               "code": "authentication_required"})
    except contributions.StateConflict as error:
        respond(request, 409, {"error": str(error), "code": "state_conflict"})
    except ValueError as error:
        if isinstance(error, json.JSONDecodeError):
            respond(request, 503, {"error": "기여 기록을 읽지 못했습니다. 잠시 후 다시 시도하세요.",
                                   "code": "service_unavailable"})
        else:
            respond(request, 400, {"error": str(error), "code": "invalid_input"})
    except (OSError, RuntimeError, KeyError, TypeError):
        respond(request, 503, {"error": "기여 기록을 처리하지 못했습니다. 입력을 유지하고 다시 시도하세요.",
                               "code": "service_unavailable"})


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        handle_contributions(self)

    def do_POST(self):
        handle_contributions(self)

    def do_DELETE(self):
        handle_contributions(self)
