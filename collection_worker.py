"""구독 요청이 있을 때만 실행하는 Windows 수집기. 유휴 폴링은 하지 않는다."""
import argparse
from contextlib import AbstractContextManager
import json
from pathlib import Path
import secrets
import threading
import time

import community
import collection
import radar
from public_feed import public_items


class CollectionLock(AbstractContextManager):
    """정기 수집과 구독 수집의 파일·snapshot 쓰기를 한 실행으로 제한한다."""
    def __init__(self):
        self.token = secrets.token_hex(24)
        self.stop = threading.Event()
        self.lost = False

    def __enter__(self):
        while community.redis('SET', collection.LOCK_KEY, self.token, 'NX', 'EX', 120) != 'OK':
            time.sleep(2)
        self.thread = threading.Thread(target=self.renew, daemon=True)
        self.thread.start()
        return self

    def renew(self):
        while not self.stop.wait(30):
            try:
                if not community.redis('EVAL', "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('EXPIRE',KEYS[1],120) end; return 0", 1, collection.LOCK_KEY, self.token):
                    self.lost = True
                    return
            except (OSError, RuntimeError):
                self.lost = True
                return

    def check(self):
        if self.lost or community.redis('GET', collection.LOCK_KEY) != self.token:
            raise RuntimeError('수집 실행권을 잃었습니다.')

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        community.redis('EVAL', "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0", 1, collection.LOCK_KEY, self.token)


def save_job(job, stage):
    job.update(stage=stage, updated_at=community.timestamp())
    community.redis('HSET', collection.JOBS_KEY, job['repo'], json.dumps(job))


def collect_repository(repo, root, progress):
    """한 저장소의 공개 이슈만 수집하고 기존 레포당 20건 판정 한도를 지킨다."""
    info = radar.gh_json('repos/' + repo, include_status=True)
    if info.get('private') is not False or info.get('archived') or info.get('disabled') or not info.get('has_issues'):
        raise ValueError('수집 가능한 공개 저장소가 아닙니다.')
    directory = Path(root) / '.radar-community' / 'subscriptions' / repo.replace('/', '__')
    directory.mkdir(parents=True, exist_ok=True)
    repos = directory / 'repos.txt'
    repos.write_text(repo + '\n', encoding='utf-8')
    issues, grades = directory / 'issues.jsonl', directory / 'grades.jsonl'
    progress('fetching')
    if radar.collect(argparse.Namespace(repos=repos, sample=None, since='7d', output=issues)):
        raise RuntimeError('GitHub 수집 실패')
    progress('grading')
    if radar.grade(argparse.Namespace(input=issues, output=grades, reuse=grades, model=radar.MODEL,
                                      all_issues=False, workers=1)):
        raise RuntimeError('판정 실패')
    # 정기 수동 메일 초안에서도 즉시 수집 후보를 사용할 수 있도록 같은 후보 파일에 병합한다.
    if radar.candidates(argparse.Namespace(input=grades, output=Path(root) / '.radar-community' / 'candidates.jsonl')):
        raise RuntimeError('후보 저장 실패')
    return public_items(radar.read_jsonl(issues), radar.read_jsonl(grades))


def merge_repository(repo, items, lock):
    lock.check()
    # 잠금 만료와 쓰기 사이에도 소유권을 Redis 내부에서 확인한다.
    result = community.redis('EVAL', """
if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
local raw=redis.call('GET',KEYS[2]); local s=raw and cjson.decode(raw) or {}
local items={}; for _,i in ipairs(s.items or {}) do
 if string.lower(i.repo)~=ARGV[2] then table.insert(items,i) end end
for _,i in ipairs(cjson.decode(ARGV[3])) do table.insert(items,i) end
local names={}; for _,r in ipairs(s.collected_repos or {}) do names[string.lower(r)]=true end
names[ARGV[2]]=true; local repos={}; for r,_ in pairs(names) do table.insert(repos,r) end
s.items=items; s.collected_repos=repos; s.collected_at=ARGV[4]
-- cjson은 빈 Lua 테이블을 object로 쓰므로 배열은 JSON 조각으로 보존한다.
local encoded=cjson.encode(s); if #items==0 then encoded=string.gsub(encoded,'"items":{}','"items":[]') end
redis.call('SET',KEYS[2],encoded); return 1
""", 2, collection.LOCK_KEY, community.SNAPSHOT_KEY, lock.token, repo,
        json.dumps(items, ensure_ascii=False), community.timestamp())
    if not result:
        raise RuntimeError('수집 실행권을 잃었습니다.')


def drain(root=radar.ROOT):
    with CollectionLock() as lock:
        # 유휴 상태에서 반복 조회하지 않는다. 실행 중 추가된 요청도 이 실행이 마저 처리한다.
        while True:
            jobs = [json.loads(raw) for raw in community.redis('HVALS', collection.JOBS_KEY) or []]
            pending = [j for j in jobs if j['stage'] in collection.ACTIVE]
            if not pending:
                return
            snapshot = json.loads(community.redis('GET', community.SNAPSHOT_KEY) or '{}')
            for job in pending:
                if job['repo'] in snapshot.get('collected_repos', []):
                    save_job(job, 'done')
                    continue
                while job['attempt'] < 3:
                    lock.check()
                    job['attempt'] += 1
                    save_job(job, 'fetching')
                    try:
                        items = collect_repository(job['repo'], root, lambda stage: save_job(job, stage))
                        merge_repository(job['repo'], items, lock)
                        save_job(job, 'done')
                        break
                    except (OSError, ValueError, RuntimeError, KeyError, TypeError, radar.subprocess.SubprocessError):
                        lock.check()
                        save_job(job, 'retrying' if job['attempt'] < 3 else 'failed')
                        if job['attempt'] < 3:
                            time.sleep(5 * job['attempt'])
                else:
                    save_job(job, 'failed')
