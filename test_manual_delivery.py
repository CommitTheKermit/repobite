"""외부 조회와 메일 발송 없이 수동 초안과 발송 기록을 검증한다."""

from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import contribution_tracking
from test_contribution_tracking import ContributionRedis

from manual_delivery import ManualDelivery
import radar
from test_radar import GOOD, ISSUE


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = ManualDelivery(root / 'private' / 'delivery.sqlite')
        issue = radar.normalize_issue('Owner/Repo', ISSUE)
        rows = [{**issue, 'number': n, 'url': f'https://github.com/Owner/Repo/issues/{n}',
                 'created_at': f'2026-10-{n:02d}T00:00:00Z',
                 'grade': GOOD, 'model': radar.MODEL, 'criteria_version': 2,
                 'reasoning_effort': radar.REASONING_EFFORT} for n in range(1, 6)]
        subscribers = [dict(user_id='alice', email='alice@example.test', subscriptions=['owner/repo']),
                       dict(user_id='bob', email='bob@example.test', subscriptions=['other/repo'])]
        checked = []

        def refresh(candidates):
            checked.append([row['number'] for row in candidates])
            return [{**row, 'freshness': {'eligible': True, 'checked_at': 'now'}}
                    for row in candidates]

        def prepare(rows=rows, subscribers=subscribers, day='2026-10-21', **options):
            return store.prepare(rows, subscribers, day=day, refresh=refresh,
                                 public_check=options.get('public_check', lambda repo: True))

        drafts = prepare()
        assert len(drafts) == 1 and drafts[0]['count'] == 3
        digest = drafts[0]['id']
        assert store.db.execute('SELECT COUNT(*) FROM sent_issues').fetchone()[0] == 0
        path = store.export(digest, root / 'export')
        email = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        assert email['To'] == 'alice@example.test'
        assert email['X-Unsent'] == '1'
        body = email.get_body().get_content()
        assert '/issues/5' in body and '/issues/3' in body and '/issues/2' not in body
        assert '구현 난이도가 아닌' in body
        # 같은 날 재생성은 새 발송이나 새 수신자를 만들지 않는다.
        assert prepare()[0]['id'] == digest
        assert len(checked) == 2
        assert store.confirm_sent(digest, today='2026-10-21') is True
        assert store.confirm_sent(digest, today='2026-10-21') is False
        assert prepare() == []
        assert store.db.execute('SELECT COUNT(*) FROM delivery_outbox').fetchone()[0] == 1
        def unavailable(**payload):
            raise RuntimeError('모의 DB 장애')
        try:
            store.sync_deliveries(unavailable)
        except RuntimeError:
            pass
        else:
            raise AssertionError('동기화 실패를 성공 처리했습니다')
        assert store.db.execute('SELECT synced_at FROM delivery_outbox').fetchone()[0] is None
        published = []
        assert store.sync_deliveries(lambda **payload: published.append(payload)) == 1
        assert published[0]['user_id'] == 'alice'
        assert published[0]['digest_id'] == digest
        assert published[0]['state'] == 'operator_confirmed'
        assert 'email' not in published[0]
        assert set(published[0]['items'][0]) == {'repo', 'number', 'url', 'title'}
        assert store.sync_deliveries(lambda **payload: published.append(payload)) == 0
        assert len(published) == 1
        assert store.db.execute('SELECT COUNT(*) FROM sent_issues').fetchone()[0] == 3
        # 재시작 후에도 이미 보낸 이슈를 다음 날 다시 담지 않는다.
        store.close()
        store = ManualDelivery(root / 'private' / 'delivery.sqlite')
        tomorrow = prepare(day='2026-10-22')
        assert tomorrow[0]['count'] == 2
        payload = json.loads(store.db.execute('SELECT items FROM digests WHERE id=?',
                                             (tomorrow[0]['id'],)).fetchone()[0])
        assert {row['number'] for row in payload} == {1, 2}
        try:
            store.confirm_sent(tomorrow[0]['id'], today='2026-10-21')
        except ValueError:
            pass
        else:
            raise AssertionError('다른 날짜의 발송을 확인했습니다')
        # 사람별 발송 기록을 격리한다.
        bob = [{**subscribers[1], 'subscriptions': ['OWNER/REPO']}]
        assert prepare(subscribers=bob)[0]['count'] == 3
        # 비공개/확인실패 레포와 현행 메타데이터가 없는 과거 판정은 발송하지 않는다.
        assert prepare(subscribers=bob, public_check=lambda repo: False) == []
        assert prepare(rows=[{**rows[0], 'criteria_version': None}], subscribers=bob) == []
        assert prepare(rows=[{**rows[0], 'model': 'old-model'}], subscribers=bob) == []
        # 이슈가 닫히면 같은 날 준비해 두었던 초안도 무효화한다.
        new = prepare(subscribers=bob)
        assert new
        assert store.prepare(rows, bob, day='2026-10-21', public_check=lambda repo: True,
                             refresh=lambda candidates: [
                                 {**row, 'freshness': {'eligible': False}} for row in candidates]) == []
        try:
            store.export(new[0]['id'], root / 'export')
        except ValueError:
            pass
        else:
            raise AssertionError('최신성 검사에서 무효화한 초안을 내보냈습니다')
        # 수신 주소가 바뀐 초안을 이전 ID로 발송 확인할 수 없다.
        old = prepare(subscribers=bob)[0]['id']
        changed = prepare(subscribers=[{**bob[0], 'email': 'changed@example.test'}])[0]['id']
        assert old != changed
        try:
            store.confirm_sent(old, today='2026-10-21')
        except ValueError:
            pass
        else:
            raise AssertionError('주소 변경 전 초안을 발송 확인했습니다')
        # 수신 거부 계정은 다음 준비에서 사라지고 이전 자동 생성 메일도 제거한다.
        new = prepare(subscribers=bob)
        store.export_prepared(new, root / 'export')
        (root / 'export' / 'operator-note.eml').write_text('수동 파일')
        assert (root / 'export' / (new[0]['id'] + '.eml')).exists()
        assert prepare(subscribers=[]) == []
        store.export_prepared([], root / 'export')
        assert not (root / 'export' / (new[0]['id'] + '.eml')).exists()
        assert (root / 'export' / 'operator-note.eml').exists()
        assert store.db.execute("SELECT COUNT(*) FROM digests WHERE state='prepared'").fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM sent_issues').fetchone()[0] == 3
        store.close()
    # 실제 C -> E 함수 계약을 사용하고, 원격 성공 응답 유실 뒤에도 한 번만 저장한다.
    with tempfile.TemporaryDirectory() as directory:
        store = ManualDelivery(Path(directory) / 'delivery.sqlite')
        draft = store.prepare(rows, [{**subscribers[0], 'user_id': '10'}], day='2026-10-21',
                              refresh=refresh, public_check=lambda repo: True)[0]
        store.confirm_sent(draft['id'], today='2026-10-21')
        db = ContributionRedis()
        def lost_response(**payload):
            contribution_tracking.record_delivery(**payload)
            raise RuntimeError('원격 저장 후 응답 유실')
        with patch.object(contribution_tracking.community, 'redis', db):
            try:
                store.sync_deliveries(lost_response)
            except RuntimeError:
                pass
            assert store.sync_deliveries(contribution_tracking.record_delivery) == 1
            deliveries = contribution_tracking.user_deliveries('10')
            assert len(deliveries) == 1
            assert deliveries[0]['id'] == draft['id']
            assert deliveries[0]['provider_delivery_verified'] is False
            assert all(set(item) == {'repo', 'number'} for item in deliveries[0]['items'])
            assert contribution_tracking.user_deliveries('20') == []
            assert store.sync_deliveries(contribution_tracking.record_delivery) == 0
        store.close()
    print('통과: 하루 3건·구독 격리·최신성·공개 검증·초안/발송 분리·재시작·중복 방지')


if __name__ == '__main__':
    main()
