"""명시 실행 전용: 실제 Redis의 임시 키에서 Lua 중복·병합·잠금 경계를 검증한다.
환경변수는 기존 비밀 저장소에서 주입한다. 운영 키는 읽거나 수정하지 않는다.
"""
import json
import secrets
from unittest.mock import patch

import collection
import collection_worker as worker
import community


def main():
    native = community.redis
    prefix = 'repobite:test:collect:' + secrets.token_hex(12) + ':'
    keys = set()
    def redis(*args):
        transformed = []
        for arg in args:
            if isinstance(arg,str) and arg.startswith('repobite:'):
                arg = prefix + arg
                keys.add(arg)
            transformed.append(arg)
        return native(*transformed)
    try:
        with patch.object(community,'redis',side_effect=redis):
            first=collection.enqueue('Owner/Repo')
            assert first['stage']=='queued'
            assert collection.enqueue('OWNER/REPO')==first
            with worker.CollectionLock() as lock:
                redis('SET',community.SNAPSHOT_KEY,json.dumps({'items':[{'repo':'other/repo','number':1}], 'collected_repos':['other/repo'],'discovered_repos':[]}))
                worker.merge_repository('owner/repo',[],lock)
                snapshot=json.loads(redis('GET',community.SNAPSHOT_KEY))
                assert snapshot['items']==[{'repo':'other/repo','number':1}]
                assert set(snapshot['collected_repos'])=={'other/repo','owner/repo'}
                assert snapshot['discovered_repos']==[]
                worker.merge_repository('other/repo',[],lock)
                assert json.loads(redis('GET',community.SNAPSHOT_KEY))['items']==[]
                redis('SET',collection.LOCK_KEY,'different-owner','EX',120)
                try: worker.merge_repository('owner/repo',[{'repo':'owner/repo','number':2}],lock)
                except RuntimeError: pass
                else: raise AssertionError('잃은 잠금으로 저장했습니다')
                assert json.loads(redis('GET',community.SNAPSHOT_KEY))['items']==[]
            redis('HDEL',collection.JOBS_KEY,'owner/repo')
            assert collection.enqueue('OWNER/REPO')['stage']=='done'
        print('통과: 실제 Redis Lua 중복 요청·수집된 저장소 생략·결과 병합·빈 배열·잠금 소유권 검사')
    finally:
        if keys: native('DEL',*keys)


if __name__=='__main__': main()
