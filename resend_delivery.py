"""Resend 전송 경계. 오류 응답 원문과 인증 헤더는 로그에 노출하지 않는다."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SENDER = 'RepoBite <notify@repobite.ao3921.com>'


class SendError(RuntimeError):
    pass


def send_email(payload, idempotency_key):
    key = os.environ.get('RESEND_API_KEY', '')
    if not key.startswith('re_') or any(c.isspace() for c in key):
        raise SendError('Resend 키 설정을 확인하세요.')
    request = Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
        'Idempotency-Key': idempotency_key, 'User-Agent': 'RepoBite/1.0'})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not isinstance(result.get('id'), str) or not result['id']:
            raise SendError('Resend 접수 결과를 확인하지 못했습니다.')
        return result['id']
    except HTTPError as error:
        status = error.code
        error.close()
        raise SendError(f'Resend HTTP {status}: 접수 여부를 확인한 뒤 재시도하세요.') from None
    except (OSError, ValueError, KeyError, TypeError):
        raise SendError('Resend 접수 여부를 확인하지 못했습니다. 같은 요청으로 재시도합니다.') from None


def digest_payload(row, unsubscribe_url):
    items = json.loads(row['items'])
    lines = ['구독한 저장소에서 선택한 난이도에 맞는 새 이슈를 찾았습니다.', '']
    for item in items:
        level = item['grade']['difficulty']
        label = {1: '쉬움', 2: '보통', 3: '어려움'}[level]
        lines += [f"{item['repo']} #{item['number']} - Lv.{level} {label}", item['title'], item['url'], '']
    lines += ['작업 전에 GitHub에서 닫힘·담당자·연결된 PR을 확인하세요.', '',
              '이메일 알림 끄기: ' + unsubscribe_url]
    return {'from': SENDER, 'to': [row['email']], 'subject': f"[RepoBite] {row['day']} 구독 저장소의 새 이슈",
            'text': '\n'.join(lines), 'headers': {'List-Unsubscribe': '<' + unsubscribe_url + '>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}}
