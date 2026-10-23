"""관리 웹과 분리된 인증 전용 실행 입구. 요청 후 작업 스레드는 큐가 비면 종료한다."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import time

import collection
import collection_worker
import community

RUNNER = threading.Lock()


def run_pending():
    # 동시 알림은 하나로 합친다. 종료 경계에서 온 알림은 기다렸다 새로 조회한다.
    with RUNNER:
        try:
            collection_worker.drain()
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            # 작업은 Redis에 보존되어 다음 알림/정기 실행 때 복구한다. 비밀·원문을 기록하지 않는다.
            print('구독 수집 실행 중단: 다음 실행에서 보존된 요청을 확인합니다.', flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def do_POST(self):
        try:
            secret = os.environ.get('REPOBITE_COLLECT_SECRET', '')
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/collect' or len(secret) < 32 or not 0 < length <= 256:
                return self.reply(403)
            raw = self.rfile.read(length)
            if not hmac.compare_digest(self.headers.get('X-RepoBite-Signature', ''), collection.signature(raw, secret)):
                return self.reply(403)
            value = json.loads(raw)
            if (type(value.get('at')) is not int or abs(time.time() - value['at']) > 60
                    or not re.fullmatch('[0-9a-f]{32}', value.get('nonce', ''))):
                return self.reply(403)
            if community.redis('SET', 'repobite:collect:nonce:' + value['nonce'], '1', 'NX', 'EX', 120) != 'OK':
                return self.reply(409)
            threading.Thread(target=run_pending, daemon=True).start()
            self.reply(202)
        except (OSError, ValueError, RuntimeError, TypeError, AttributeError):
            self.reply(503)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    if len(os.environ.get('REPOBITE_COLLECT_SECRET', '')) < 32:
        raise SystemExit('수집 전용 인증 설정이 필요합니다.')
    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        server.serve_forever()
