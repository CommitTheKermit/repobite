"""구독 수집 요청과 상태. Vercel에서는 요청 전달만 하며 판정은 Windows에서 한다."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import community

JOBS_KEY = 'repobite:collect:jobs'
LOCK_KEY = 'repobite:collect:lock'
ACTIVE = {'queued', 'fetching', 'grading', 'retrying'}


def statuses(repos):
    names = [community.normalize_repo(repo).lower() for repo in repos]
    if not names:
        return []
    values = community.redis('HMGET', JOBS_KEY, *names)
    snapshot = json.loads(community.redis('GET', community.SNAPSHOT_KEY) or '{}')
    collected = {n.lower() for n in snapshot.get('collected_repos', [])}
    result = []
    for name, raw in zip(names, values):
        if raw:
            job = json.loads(raw)
            result.append({key: job[key] for key in ('repo', 'stage', 'attempt', 'updated_at')})
        else:
            result.append({'repo': name, 'stage': 'done' if name in collected else 'idle', 'attempt': 0,
                           'updated_at': snapshot.get('collected_at')})
    return result


def completion_id(job):
    if job["stage"] != "done" or not job["attempt"]:
        return None
    # 기존 snapshot의 결과는 새 구독의 수집 완료가 아니다.
    completed_at = job["updated_at"]
    return hashlib.sha256((job["repo"].lower() + "\0" + str(completed_at)).encode()).hexdigest()


def status(repo):
    return statuses([repo])[0]


def enqueue(repo):
    name = community.normalize_repo(repo).lower()
    job = {'repo': name, 'stage': 'queued', 'attempt': 0, 'updated_at': community.timestamp()}
    # 수집된 저장소와 진행 중 요청은 재사용한다. 실패 기록도 자동으로 초기화하지 않는다.
    community.redis('EVAL', """
local old=redis.call('HGET',KEYS[1],ARGV[1]); if old then return old end
local raw=redis.call('GET',KEYS[2]); if raw then
 local s=cjson.decode(raw); for _,r in ipairs(s.collected_repos or {}) do
  if string.lower(r)==ARGV[1] then return '' end end end
redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); return ARGV[2]
""", 2, JOBS_KEY, community.SNAPSHOT_KEY, name, json.dumps(job))
    return status(name)


def signature(body, secret):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def wake():
    endpoint = os.environ.get('REPOBITE_COLLECT_URL', '')
    secret = os.environ.get('REPOBITE_COLLECT_SECRET', '')
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or len(secret) < 32:
        raise RuntimeError('즉시 수집 연결 설정을 확인하세요.')
    body = json.dumps({'at': int(time.time()), 'nonce': secrets.token_hex(16)}).encode()
    request = Request(endpoint, data=body, headers={'Content-Type': 'application/json',
                      'X-RepoBite-Signature': signature(body, secret)})
    with urlopen(request, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError('즉시 수집 요청을 전달하지 못했습니다.')


def request(repo):
    job = enqueue(repo)
    if job['stage'] in ACTIVE:
        # 전달 실패로 저장된 구독을 실패 처리하지 않는다. 상태 재조회 시 다시 깨울 수 있다.
        try:
            wake()
        except (OSError, ValueError, RuntimeError):
            pass
    return job
