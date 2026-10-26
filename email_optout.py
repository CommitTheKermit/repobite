"""메일별 임의 토큰으로 해당 주소의 수신 동의를 원자적으로 해제한다."""
import hashlib
import json
import re
import secrets

import accounts
import community


def token_key(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise ValueError('메일의 수신 해지 링크를 확인하세요.')
    return 'repobite:email:optout:' + hashlib.sha256(token.encode()).hexdigest()


def create_link(user_id, email):
    token = secrets.token_urlsafe(32)
    community.redis('SET', token_key(token), json.dumps([user_id, email]), 'EX', 60 * 60 * 24 * 365)
    return accounts.PUBLIC_ORIGIN + '/api/email_unsubscribe?token=' + token


def valid_link(token):
    return bool(community.redis('GET', token_key(token)))


def opt_out(token):
    # 이전 주소로 받은 메일이 새 주소의 동의를 해제하지 않도록 같은 Lua에서 확인한다.
    return community.redis('EVAL', '''
local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
local recipient=cjson.decode(raw)
local saved=redis.call('HGET',KEYS[2],recipient[1]); if not saved then return 1 end
local p=cjson.decode(saved)
if p.email==recipient[2] then
 p.delivery_enabled=false; redis.call('HSET',KEYS[2],recipient[1],cjson.encode(p))
end
return 1
''', 2, token_key(token), accounts.PREFERENCES_KEY)
