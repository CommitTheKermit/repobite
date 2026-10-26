"""매일 한국 시간 11시에 명시적으로 동의한 계정의 개인 구독 메일을 발송한다."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

import accounts
import community
from collection_worker import CollectionLock
from contribution_tracking import record_delivery, StateConflict
import email_optout
from manual_delivery import ManualDelivery, KST
import radar
from resend_delivery import digest_payload, send_email


@contextmanager
def single_sender(path):
    """프로세스 종료 때 OS가 해제하는 파일 잠금. 재시도와 수동 실행을 직렬화한다."""
    path = Path(str(path) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def initialize_attempts(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS automatic_attempts (
        digest_id TEXT PRIMARY KEY, payload TEXT NOT NULL, started_at TEXT NOT NULL,
        provider_id TEXT, accepted_at TEXT)''')
    store.db.commit()


def eligible_recipient(row, items, subscribers):
    for subscriber in subscribers:
        if subscriber['user_id'] != row['user_id'] or subscriber['email'] != row['email']:
            continue
        repos = {repo.lower() for repo in subscriber['subscriptions']}
        return all(item['repo'].lower() in repos and item['grade']['difficulty'] == subscriber.get('difficulty', 1)
                   for item in items)
    return False


def send_prepared(store, subscribers, transport=send_email, link=email_optout.create_link, now=None,
                  recheck=None):
    """외부 호출 전에 정확한 요청을 디스크에 보존한다. 불명확한 접수도 23시간 뒤 재전송하지 않는다."""
    now = now or datetime.now(timezone.utc)
    initialize_attempts(store)
    accepted = failed = 0
    rows = store.db.execute("SELECT * FROM digests WHERE state IN ('prepared','sending')").fetchall()
    for row in rows:
        if row['day'] != now.astimezone(KST).date().isoformat():
            # 오래된 미확인 요청은 차단 상태로 남겨 운영자가 제공자 로그를 확인하게 한다.
            if row['state'] == 'sending':
                failed += 1
            continue
        items = json.loads(row['items'])
        current = recheck() if recheck else subscribers
        if not eligible_recipient(row, items, current):
            # 아직 접수를 시작하지 않았다면 취소한다. 불명확한 접수의 이력을 지우지 않는다.
            if row['state'] == 'prepared':
                store.db.execute("UPDATE digests SET state='cancelled' WHERE id=?", (row['id'],))
                store.db.commit()
            else:
                failed += 1
            continue
        attempt = store.db.execute('SELECT * FROM automatic_attempts WHERE digest_id=?', (row['id'],)).fetchone()
        if attempt:
            if now - datetime.fromisoformat(attempt['started_at']) >= timedelta(hours=23):
                failed += 1
                continue
            payload = json.loads(attempt['payload'])
        else:
            payload = digest_payload(row, link(row['user_id'], row['email']))
            store.db.execute('INSERT INTO automatic_attempts VALUES (?,?,?,NULL,NULL)',
                             (row['id'], json.dumps(payload, ensure_ascii=False), now.isoformat()))
            store.db.execute("UPDATE digests SET state='sending' WHERE id=?", (row['id'],))
            store.db.commit()
        try:
            provider_id = transport(payload, 'repobite-digest/' + row['id'])
        except RuntimeError:
            failed += 1
            time.sleep(1)
            continue
        # 접수 이후 장애도 기존 Idempotency-Key로 재시도하므로 실제 전송을 중복시키지 않는다.
        with store.db:
            store.db.execute('UPDATE automatic_attempts SET provider_id=?,accepted_at=? WHERE digest_id=?',
                             (provider_id, now.isoformat(), row['id']))
            store.db.execute("UPDATE digests SET state='provider_accepted',confirmed_at=? WHERE id=?",
                             (now.isoformat(), row['id']))
            for item in items:
                repo, number = radar.issue_key(item)
                store.db.execute('INSERT OR IGNORE INTO sent_issues VALUES (?,?,?,?)',
                                 (row['user_id'], repo, number, row['id']))
            receipt = {'user_id': row['user_id'], 'digest_id': row['id'], 'day': row['day'],
                       'items': [{key: item[key] for key in ('repo', 'number', 'url', 'title')} for item in items],
                       'confirmed_at': now.isoformat(), 'state': 'provider_accepted', 'provider_id': provider_id}
            store.db.execute('INSERT OR IGNORE INTO delivery_outbox VALUES (?,?,NULL)',
                             (row['id'], json.dumps(receipt, ensure_ascii=False)))
        accepted += 1
        time.sleep(0.6)  # 기본 전송 속도를 초당 두 요청 미만으로 유지한다.
    return {'accepted': accepted, 'pending': failed}


def candidate_snapshot(root):
    # 수집기가 파일을 교체하는 동안 읽지 않는다. 네트워크 전송 중에는 수집 잠금을 점유하지 않는다.
    with CollectionLock():
        snapshot = json.loads(community.redis('GET', community.SNAPSHOT_KEY) or '{}')
        collected = datetime.fromisoformat(snapshot.get('collected_at', ''))
        age = datetime.now(timezone.utc) - collected
        if not timedelta(0) <= age <= timedelta(hours=24):
            raise RuntimeError('최근 24시간 내 수집 성공 결과가 필요합니다.')
        current = {radar.issue_key(item): item for item in snapshot.get('items', [])}
        directory = Path(root) / '.radar-community'
        # 기존 candidates.jsonl은 Lv.1만 보관하므로 전체 등급 원본에서 선택한다.
        paths = [directory / 'grades.jsonl', *sorted((directory / 'subscriptions').glob('*/grades.jsonl'))]
        rows = []
        for path in paths:
            if path.exists():
                rows.extend(radar.read_jsonl(path))
        return [row for row in rows if radar.issue_key(row) in current and all(
            row.get(key) == current[radar.issue_key(row)].get(key)
            for key in ('title', 'url', 'grade', 'model', 'criteria_version'))]


def run(state, root=radar.ROOT, dry_run=False):
    with single_sender(state):
        store = ManualDelivery(state)
        try:
            initialize_attempts(store)
            subscribers = accounts.delivery_subscribers()
            blocked = {r['user_id'] for r in store.db.execute("SELECT user_id FROM digests WHERE state='sending'")}
            rows = candidate_snapshot(root)
            wanted = {(repo.lower(), subscriber.get('difficulty', 1)) for subscriber in subscribers
                      for repo in subscriber['subscriptions']}
            rows = [row for row in rows if (row['repo'].lower(), (row.get('grade') or {}).get('difficulty')) in wanted]
            # 같은 날 접수와 과거 불명확 접수는 새 초안으로 덮어쓰지 않는다.
            prepared = store.prepare(rows, [s for s in subscribers if s['user_id'] not in blocked])
            if dry_run:
                print(json.dumps({'prepared': len(prepared), 'blocked_accounts': len(blocked), 'sent': 0}))
                return 0
            result = send_prepared(store, subscribers, recheck=accounts.delivery_subscribers)
            store.sync_deliveries(record_delivery)
            print(json.dumps(result))
            return int(result['pending'] > 0)
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--test-recipient', help='설정 직후 운영자 본인에게 연결 확인 메일 1건만 전송')
    args = parser.parse_args()
    try:
        if args.test_recipient:
            import secrets
            from resend_delivery import SENDER
            recipient = accounts.normalize_email(args.test_recipient)
            if not recipient:
                raise ValueError()
            send_email({'from': SENDER, 'to': [recipient], 'subject': '[RepoBite] 발송 연결 확인',
                        'text': 'RepoBite의 Resend 발송 연결 확인 메일입니다. 이 주소를 구독자로 등록하지 않습니다.'},
                       'repobite-connection/' + secrets.token_hex(16))
            print('Resend가 확인 메일을 접수했습니다. 받은편지함에서 실제 수신을 확인하세요.')
            return 0
        return run(args.state, dry_run=args.dry_run)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, sqlite3.Error, StateConflict):
        print('자동 발송 미완료: 키·계정 DB·수집 결과·미확인 접수 상태를 점검하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
