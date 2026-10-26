"""익명 의견 접수. 입력과 저장 결과를 한국어 응답으로 전달한다."""

from http.server import BaseHTTPRequestHandler
import json

import community
import metrics


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_POST(self):
        try:
            data = community.public_json_body(self, 2048)
        except community.InvalidPublicRequest as error:
            return self.reply(error.status, {"error": str(error)})
        try:
            metrics.record_feedback(data.get("text"))
        except ValueError as error:
            return self.reply(400, {"error": str(error)})
        except OverflowError as error:
            return self.reply(429, {"error": str(error)})
        except (OSError, RuntimeError, KeyError, TypeError):
            return self.reply(503, {"error": "의견을 저장하지 못했습니다. 잠시 후 다시 시도하세요."})
        self.reply(201, {"message": "의견을 보냈습니다. 고맙습니다."})

    def method_not_allowed(self):
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = method_not_allowed
