"""외부 API 호출 없이 요청·재시도·공개 경계와 잠금 소유권을 검증한다."""
from contextlib import nullcontext
import io
import json
import os
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import collection
import collection_server
import collection_worker as worker
import community


class CollectionTest(unittest.TestCase):
    def test_collected_repository_does_not_wake_worker(self):
        with patch.object(collection, 'enqueue', return_value={'stage': 'done'}), patch.object(collection, 'wake') as wake:
            self.assertEqual(collection.request('owner/repo')['stage'], 'done')
            wake.assert_not_called()

    def test_dispatch_failure_preserves_pending_job(self):
        with patch.object(collection, 'enqueue', return_value={'stage': 'queued'}), patch.object(collection, 'wake', side_effect=OSError):
            self.assertEqual(collection.request('owner/repo')['stage'], 'queued')

    def test_status_exposes_only_subscribed_repo_state(self):
        raw = {'repo': 'a/b', 'stage': 'grading', 'attempt': 2, 'updated_at': 'now', 'private': 'hidden'}
        with patch.object(community, 'redis', side_effect=[[json.dumps(raw), None], '{}']) as redis:
            rows = collection.statuses(['A/B', 'c/d'])
            self.assertEqual(rows[0], {k: raw[k] for k in ('repo','stage','attempt','updated_at')})
            self.assertEqual(rows[1]['stage'], 'idle')
            self.assertEqual(redis.call_args_list[0].args, ('HMGET', collection.JOBS_KEY, 'a/b', 'c/d'))

    def attempt_scenario(self, failures):
        job = {'repo': 'owner/repo', 'stage': 'queued', 'attempt': 0, 'updated_at': 'now'}
        saved = []
        def redis(command, *args):
            if command == 'HVALS':
                return [json.dumps(job)] if job['stage'] in collection.ACTIVE else []
            if command == 'GET':
                return '{}'
            if command == 'HSET':
                job.update(json.loads(args[-1])); saved.append(dict(job)); return 1
            raise AssertionError(command)
        lock = Mock()
        attempts = [RuntimeError('429')] * failures + [[]]
        with patch.object(community,'redis',side_effect=redis), patch.object(worker,'CollectionLock',return_value=nullcontext(lock)), patch.object(worker,'collect_repository',side_effect=attempts) as collect, patch.object(worker,'merge_repository') as merge, patch.object(worker.time,'sleep'):
            worker.drain()
            self.assertEqual(collect.call_count, min(failures + 1, 3))
            self.assertEqual(merge.call_count, int(failures < 3))
            self.assertEqual(job['stage'], 'done' if failures < 3 else 'failed')
            self.assertFalse(any(j['stage'] == 'failed' and j['attempt'] < 3 for j in saved))
            for call in collect.call_args_list:
                self.assertEqual(call.args[0], 'owner/repo')

    def test_transient_failure_is_retried_then_completes(self):
        self.attempt_scenario(2)

    def test_only_third_failed_attempt_becomes_failure(self):
        self.attempt_scenario(3)

    def test_lost_lock_prevents_snapshot_write(self):
        lock = Mock(); lock.check.side_effect = RuntimeError('lost')
        with patch.object(community,'redis') as redis:
            with self.assertRaises(RuntimeError): worker.merge_repository('a/b', [], lock)
            redis.assert_not_called()

    def test_signed_endpoint_rejects_unsigned_expired_and_replayed_requests(self):
        secret = 'test-only-collection-secret-32-characters'
        server = ThreadingHTTPServer(('127.0.0.1',0), collection_server.Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def request(raw, signed=True):
            req = Request(f'http://127.0.0.1:{server.server_port}/collect', data=raw,
                          headers={'X-RepoBite-Signature': collection.signature(raw,secret) if signed else ''})
            try:
                with urlopen(req) as response: return response.status
            except HTTPError as error:
                code = error.code; error.close(); return code
        try:
            with patch.dict(os.environ,REPOBITE_COLLECT_SECRET=secret), patch.object(community,'redis',side_effect=['OK',None]), patch.object(collection_server,'run_pending') as run:
                now = json.dumps({'at':int(time.time()),'nonce':'a'*32}).encode()
                self.assertEqual(request(now,False),403)
                self.assertEqual(request(json.dumps({'at':0,'nonce':'a'*32}).encode()),403)
                self.assertEqual(request(now),202)
                self.assertEqual(request(now),409)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
