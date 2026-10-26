"""외부 전송 없이 자동 메일의 중복 방지와 수신 동의 경계를 검증한다."""
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import automatic_delivery as auto
from api.email_unsubscribe import handler
import contribution_tracking
import email_optout
from manual_delivery import ManualDelivery
import radar
import resend_delivery
from test_accounts import MemoryRedis
from test_contribution_tracking import ContributionRedis
from test_radar import GOOD, ISSUE

NOW = datetime(2026, 10, 26, 2, tzinfo=timezone.utc)
SUBSCRIBER = dict(user_id='alice', email='alice@example.test', subscriptions=['owner/repo'], difficulty=1)


class AutomaticDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = ManualDelivery(Path(self.directory.name) / 'delivery.sqlite')
        issue = radar.normalize_issue('Owner/Repo', ISSUE)
        self.rows = [{**issue, 'number': n, 'url': f'https://github.com/Owner/Repo/issues/{n}',
                      'grade': GOOD, 'model': radar.MODEL, 'criteria_version': radar.CRITERIA_VERSION,
                      'reasoning_effort': radar.REASONING_EFFORT} for n in range(1, 6)]
        self.pause = patch('automatic_delivery.time.sleep')
        self.pause.start()

    def tearDown(self):
        self.pause.stop()
        self.store.close()
        self.directory.cleanup()

    def prepare(self, day='2026-10-26'):
        return self.store.prepare(self.rows, [SUBSCRIBER], day=day,
            refresh=lambda rows: [{**r, 'freshness': {'eligible': True}} for r in rows], public_check=lambda repo: True)

    def send(self, transport, **kwargs):
        return auto.send_prepared(self.store, [SUBSCRIBER], transport=transport,
                                  link=lambda *args: 'https://example.test/unsubscribe', now=NOW, **kwargs)

    def test_provider_acceptance_is_once_and_three_issues_are_never_resent(self):
        self.prepare()
        calls = []
        result = self.send(lambda payload, key: calls.append((payload, key)) or 'provider-12345678')
        self.assertEqual(result, {'accepted': 1, 'pending': 0})
        self.assertEqual(self.prepare(), [])
        self.assertEqual(self.send(lambda *args: self.fail('중복 전송')), {'accepted': 0, 'pending': 0})
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM sent_issues').fetchone()[0], 3)
        payload = calls[0][0]
        self.assertEqual(payload['to'], ['alice@example.test'])
        self.assertEqual(payload['text'].count('https://github.com/'), 3)
        for hidden in ('readiness', 'reason', '본문 충분'):
            self.assertNotIn(hidden, payload['text'])
        receipts = []
        self.store.sync_deliveries(lambda **receipt: receipts.append(receipt))
        self.assertEqual(receipts[0]['state'], 'provider_accepted')
        self.assertNotIn('email', receipts[0])
        self.assertEqual(self.prepare('2026-10-27')[0]['count'], 2)

    def test_timeout_and_process_restart_reuse_exact_payload_and_key(self):
        self.prepare()
        calls = []
        def uncertain(payload, key):
            calls.append((payload, key))
            raise RuntimeError('모의 통신 중단')
        self.assertEqual(self.send(uncertain)['pending'], 1)
        self.assertEqual(self.prepare(), [])
        self.store.close()
        self.store = ManualDelivery(Path(self.directory.name) / 'delivery.sqlite')
        def accepted(payload, key):
            calls.append((payload, key))
            return 'provider-12345678'
        self.assertEqual(self.send(accepted)['accepted'], 1)
        self.assertEqual(calls[0], calls[1])

    def test_old_uncertain_request_is_blocked_and_cannot_be_manually_confirmed(self):
        draft = self.prepare()[0]
        self.send(lambda *args: (_ for _ in ()).throw(RuntimeError()))
        with self.assertRaises(ValueError):
            self.store.confirm_sent(draft['id'], today='2026-10-26')
        result = auto.send_prepared(self.store, [SUBSCRIBER], transport=lambda *args: self.fail('오래된 요청 재전송'),
                                    now=NOW + timedelta(hours=24))
        self.assertEqual(result['pending'], 1)

    def test_revoked_consent_and_changed_preferences_cancel_unsent_draft(self):
        for recipient in ([], [{**SUBSCRIBER, 'email': 'changed@example.test'}],
                          [{**SUBSCRIBER, 'subscriptions': []}], [{**SUBSCRIBER, 'difficulty': 2}]):
            self.store.db.execute('DELETE FROM digests')
            self.store.db.commit()
            self.prepare()
            self.send(lambda *args: self.fail('동의 또는 조건 변경 후 전송'), recheck=lambda: recipient)
            self.assertEqual(self.store.db.execute('SELECT state FROM digests').fetchone()[0], 'cancelled')

    def test_no_candidate_or_other_level_never_prepares_mail(self):
        self.rows = [{**row, 'grade': {**GOOD, 'difficulty': 2}} for row in self.rows]
        self.assertEqual(self.prepare(), [])

    def test_full_grade_sources_include_level_two_and_immediate_collection(self):
        from contextlib import nullcontext
        root = Path(self.directory.name)
        directory = root / '.radar-community'
        (directory / 'subscriptions' / 'Owner__Repo').mkdir(parents=True)
        row = {**self.rows[0], 'grade': {**GOOD, 'difficulty': 2}}
        (directory / 'subscriptions' / 'Owner__Repo' / 'grades.jsonl').write_text(json.dumps(row) + '\n')
        snapshot = {'collected_at': datetime.now(timezone.utc).isoformat(), 'items': [row]}
        with patch('automatic_delivery.CollectionLock', return_value=nullcontext()), patch('community.redis', return_value=json.dumps(snapshot)):
            self.assertEqual(auto.candidate_snapshot(root), [row])
        snapshot['items'][0] = {**row, 'title': '새 본문으로 다시 판정한 제목'}
        with patch('automatic_delivery.CollectionLock', return_value=nullcontext()), patch('community.redis', return_value=json.dumps(snapshot)):
            self.assertEqual(auto.candidate_snapshot(root), [])

    def test_concurrent_sender_is_rejected_without_second_run(self):
        path = Path(self.directory.name) / 'delivery.sqlite'
        with auto.single_sender(path):
            with self.assertRaises(OSError):
                with auto.single_sender(path):
                    self.fail('중복 실행 허용')

    def test_remote_receipt_distinguishes_accepted_from_delivered(self):
        redis = ContributionRedis()
        with patch('community.redis', redis):
            receipt = contribution_tracking.record_delivery('101', 'digest-123456', '2026-10-26',
                [{'repo': 'Owner/Repo', 'number': 1}], NOW.isoformat(), state='provider_accepted', provider_id='provider-123456')
        self.assertFalse(receipt['delivery']['provider_delivery_verified'])
        self.assertEqual(receipt['delivery']['attestation_basis'], 'provider_acceptance')

    def test_transport_does_not_leak_provider_error_body_or_key(self):
        from urllib.error import HTTPError
        import io
        with patch.dict('os.environ', {'RESEND_API_KEY': 're_unit_test_value'}), patch('resend_delivery.urlopen',
                side_effect=HTTPError('https://api.resend.com/emails', 401, 'private', {}, io.BytesIO(b'private'))):
            with self.assertRaises(resend_delivery.SendError) as caught:
                resend_delivery.send_email({}, 'test-key')
        self.assertNotIn('private', str(caught.exception))
        self.assertNotIn('re_unit_test_value', str(caught.exception))


class OptoutTests(unittest.TestCase):
    def test_confirmation_get_cannot_change_preferences_and_post_is_repeatable(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch('email_optout.valid_link', return_value=True), patch('email_optout.opt_out', return_value=1) as disable:
                connection = HTTPConnection(*server.server_address)
                connection.request('GET', '/api/email_unsubscribe?token=' + 'x' * 43)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn('form', response.read().decode())
                disable.assert_not_called()
                for _ in range(2):
                    connection.request('POST', '/api/email_unsubscribe?token=' + 'x' * 43, body='List-Unsubscribe=One-Click')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_token_is_random_and_only_hash_is_saved(self):
        redis = MemoryRedis()
        with patch('community.redis', redis):
            link = email_optout.create_link('alice', 'alice@example.test')
            token = link.split('token=')[1]
            self.assertNotIn(token, next(iter(redis.values)))
            self.assertTrue(email_optout.valid_link(token))
            with self.assertRaises(ValueError):
                email_optout.token_key('../invalid')


if __name__ == '__main__':
    unittest.main()
