"""공개 Vercel API. 수집 실행이나 DB 자격 증명은 공개하지 않는다."""

from http.server import BaseHTTPRequestHandler
import json

import community


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
        self.wfile.write(body)

    def do_GET(self):
        try:
            self.reply(200, community.feed())
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            self.reply(503, {"error": "공용 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요."})

    def do_POST(self):
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()
