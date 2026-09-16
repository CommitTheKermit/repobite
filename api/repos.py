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
        if (self.headers.get("Origin") != "https://repobite.vercel.app"
                or self.headers.get_content_type() != "application/json"):
            self.reply(403, {"error": "RepoBite 화면에서 등록하세요."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("입력이 너무 깁니다.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("레포 주소를 입력하세요.")
            result = community.register(payload.get("repo"))
            self.reply(201 if result["created"] else 200, result)
        except ValueError as error:
            self.reply(400, {"error": str(error) if not isinstance(error, json.JSONDecodeError)
                             else "입력 형식을 확인하세요."})
        except OverflowError as error:
            self.reply(429, {"error": str(error)})
        except (OSError, RuntimeError, KeyError, TypeError):
            self.reply(503, {"error": "등록하지 못했습니다. 잠시 후 다시 시도하세요."})
