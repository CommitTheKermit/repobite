"""공개 반응 집계. 저장소 장애도 페이지 동작에 영향을 주지 않는다."""

from http.server import BaseHTTPRequestHandler
import json

import community
import metrics


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data=None):
        body = json.dumps(data, ensure_ascii=False).encode() if data is not None else b""
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
            data = community.public_json_body(self, 256)
        except community.InvalidPublicRequest as error:
            return self.reply(error.status, {"error": str(error)})
        try:
            metrics.record_event(data.get("name"))
        except ValueError as error:
            return self.reply(400, {"error": str(error)})
        except (OSError, RuntimeError, KeyError, TypeError):
            pass
        self.reply(204)

    def method_not_allowed(self):
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = method_not_allowed
