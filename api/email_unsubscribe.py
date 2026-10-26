"""GET은 확인 화면만, POST는 수신 해지를 수행한다. 메일 스캐너 GET은 동의를 바꾸지 않는다."""
from html import escape
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

import email_optout


def handle_unsubscribe(request):
    status, message, form = 200, '', ''
    try:
        params = parse_qs(urlsplit(request.path).query)
        if set(params) != {'token'} or len(params['token']) != 1:
            raise ValueError()
        token = params['token'][0]
        if request.command == 'GET':
            if not email_optout.valid_link(token):
                raise ValueError()
            message = 'RepoBite 이메일 알림을 끄시겠어요?'
            form = (f'<form method="post" action="/api/email_unsubscribe?token={escape(token)}">'
                    '<button type="submit">이메일 알림 끄기</button></form>')
        elif request.command == 'POST':
            if not email_optout.opt_out(token):
                raise ValueError()
            message = '이메일 알림을 껐습니다. 저장소 구독은 유지됩니다.'
        else:
            status, message = 405, '지원하지 않는 요청입니다.'
    except (ValueError, KeyError):
        status, message = 400, '메일의 수신 해지 링크를 확인하세요.'
    except (OSError, RuntimeError):
        status, message = 503, '잠시 후 다시 시도해 주세요. 아직 알림 설정을 변경하지 못했습니다.'
    body = ('<!doctype html><html lang="ko"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>RepoBite 이메일 알림</title><main><h1>RepoBite</h1><p>'
            + message + '</p>' + form + '<a href="/">RepoBite로 돌아가기</a></main></html>').encode()
    request.send_response(status)
    for name, value in [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(body))),
                        ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
                        ('X-Content-Type-Options', 'nosniff')]:
        request.send_header(name, value)
    request.end_headers()
    request.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        handle_unsubscribe(self)

    def do_POST(self):
        handle_unsubscribe(self)

    def log_message(self, *args):
        pass  # 수신 해지 토큰을 응용 프로그램 접근 로그에 남기지 않는다.
