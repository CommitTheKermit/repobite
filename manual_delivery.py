"""사용자별 이메일 초안을 만들고 운영자가 확인한 수동 발송을 따로 기록한다.

메일 서버에 연결하지 않는다. 이메일과 초안 DB는 공개 폴더 밖에서 보관한다.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

import community
import freshness
import radar

KST = timezone(timedelta(hours=9))
DAILY_LIMIT = 3


def korean_day():
    return datetime.now(KST).date().isoformat()


def is_public_repository(repo):
    try:
        return radar.gh_json('repos/' + repo).get('private') is False
    except (OSError, ValueError, RuntimeError):
        return False


class ManualDelivery:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS digests (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, day TEXT NOT NULL,
                email TEXT NOT NULL, items TEXT NOT NULL, state TEXT NOT NULL,
                confirmed_at TEXT, UNIQUE(user_id, day));
            CREATE TABLE IF NOT EXISTS sent_issues (
                user_id TEXT NOT NULL, repo TEXT NOT NULL, number INTEGER NOT NULL,
                digest_id TEXT NOT NULL, PRIMARY KEY(user_id, repo, number));
        ''')
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def prepare(self, rows, subscribers, day=None, refresh=freshness.apply_freshness,
                public_check=is_public_repository):
        """재생성 시 최신성을 재확인한다. 초안은 발송 실적으로 집계하지 않는다."""
        day = day or korean_day()
        date.fromisoformat(day)
        candidates = radar.unique_issues(rows)
        candidates = [row for row in candidates if freshness.is_candidate(row)
                      and row.get('criteria_version') == radar.CRITERIA_VERSION
                      and row.get('model') == radar.MODEL
                      and row.get('reasoning_effort') == radar.REASONING_EFFORT]
        candidates.sort(key=lambda row: (row.get('created_at', ''), radar.issue_key(row)),
                        reverse=True)
        candidates = refresh(candidates) if candidates else []
        public = {repo: public_check(repo) for repo in {row['repo'] for row in candidates}}
        candidates = [row for row in candidates
                      if (row.get('freshness') or {}).get('eligible') is True
                      and public[row['repo']]]
        prepared = []
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for subscriber in subscribers:
                user_id = str(subscriber['user_id'])
                email = subscriber['email']
                # 공개 API가 아니라 서버 전용 계정 조회 결과만 받는다.
                if not user_id or not isinstance(email, str) or '\r' in email or '\n' in email:
                    raise ValueError('수신자 정보가 잘못되었습니다')
                subscriptions = {community.normalize_repo(repo).lower()
                                 for repo in subscriber['subscriptions']}
                current = self.db.execute(
                    'SELECT * FROM digests WHERE user_id=? AND day=?',
                    (user_id, day)).fetchone()
                if current and current['state'] == 'operator_confirmed':
                    continue
                sent = {(row['repo'], row['number']) for row in self.db.execute(
                    'SELECT repo,number FROM sent_issues WHERE user_id=?', (user_id,))}
                selected = []
                for row in candidates:
                    repo, number = radar.issue_key(row)
                    if repo in subscriptions and (repo, number) not in sent:
                        selected.append({key: row.get(key) for key in (
                            'repo', 'number', 'url', 'title', 'grade', 'freshness',
                            'model', 'criteria_version')})
                    if len(selected) == DAILY_LIMIT:
                        break
                if not selected:
                    if current:
                        self.db.execute('DELETE FROM digests WHERE id=?', (current['id'],))
                    continue
                digest_id = hashlib.sha256((user_id + ':' + day).encode()).hexdigest()
                self.db.execute('''INSERT INTO digests VALUES (?,?,?,?,?,?,NULL)
                    ON CONFLICT(user_id,day) DO UPDATE SET
                    email=excluded.email,items=excluded.items,state=excluded.state''',
                    (digest_id, user_id, day, email,
                     json.dumps(selected, ensure_ascii=False), 'prepared'))
                prepared.append({'id': digest_id, 'day': day, 'count': len(selected)})
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return prepared

    def export(self, digest_id, directory):
        row = self.db.execute('SELECT * FROM digests WHERE id=?', (digest_id,)).fetchone()
        if not row or row['state'] != 'prepared':
            raise ValueError('발송 대기 중인 초안이 없습니다')
        message = EmailMessage(policy=SMTP)
        message['To'] = row['email']
        message['Subject'] = f"[RepoBite] {row['day']} 기여 후보"
        message['X-Unsent'] = '1'
        items = json.loads(row['items'])
        lines = ['구독한 저장소의 기여 후보입니다.',
                 '등급은 구현 난이도가 아닌 이슈 본문 완결성 기준입니다.', '']
        for item in items:
            reason = item['grade']['reason'].replace('\r', ' ').replace('\n', ' ')[:40]
            lines += [item['title'], item['url'], reason, '']
        lines += ['실제 착수 전 담당자와 연결된 PR을 다시 확인해주세요.']
        message.set_content('\n'.join(lines))
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (digest_id + '.eml')
        # 원자 교체로 중단된 내보내기가 완성된 초안을 손상시키지 않게 한다.
        temporary = path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(message.as_bytes())
        temporary.replace(path)
        return path

    def confirm_sent(self, digest_id, today=None):
        """운영자의 발송 확인이다. 제공자의 전달/수신 증거를 의미하지 않는다."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM digests WHERE id=?', (digest_id,)).fetchone()
            if not row or row['day'] != (today or korean_day()):
                raise ValueError('오늘 준비한 초안만 발송 확인할 수 있습니다')
            if row['state'] == 'operator_confirmed':
                self.db.rollback()
                return False
            for item in json.loads(row['items']):
                repo, number = radar.issue_key(item)
                self.db.execute('INSERT INTO sent_issues VALUES (?,?,?,?)',
                                (row['user_id'], repo, number, digest_id))
            self.db.execute('UPDATE digests SET state=?,confirmed_at=? WHERE id=?',
                            ('operator_confirmed', datetime.now(timezone.utc).isoformat(), digest_id))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True,
                        help='공개 폴더 밖의 운영자 전용 SQLite 경로')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--input', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    confirm = commands.add_parser('confirm-sent')
    confirm.add_argument('digest_id')
    args = parser.parse_args()
    store = ManualDelivery(args.state)
    try:
        if args.command == 'prepare':
            import accounts
            prepared = store.prepare(radar.read_jsonl(args.input), accounts.delivery_subscribers())
            for item in prepared:
                store.export(item['id'], args.output)
                print(f"초안 {item['id']} - {item['count']}건")
            print('초안만 생성했습니다. 메일을 보내지 않았습니다.')
        else:
            changed = store.confirm_sent(args.digest_id)
            print('운영자 발송 확인을 기록했습니다.' if changed else '이미 확인한 발송입니다.')
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print('처리 실패: 입력·계정 DB·운영자 전용 저장 경로를 확인하세요.', file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == '__main__':
    sys.exit(main())
