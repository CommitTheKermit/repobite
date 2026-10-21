"""외부 조회와 메일 발송 없이 수동 초안과 발송 기록을 검증한다."""

from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import tempfile

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
        store.close()
    print('통과: 하루 3건·구독 격리·최신성·공개 검증·초안/발송 분리·재시작·중복 방지')


if __name__ == '__main__':
    main()
