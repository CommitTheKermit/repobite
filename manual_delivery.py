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
import re
from pathlib import Path
import sqlite3
import subprocess
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
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return False


def is_notification_candidate(row):
    grade = row.get('grade')
    return (isinstance(grade, dict) and not row.get('error')
            and grade.get('exclude') is False and grade.get('difficulty') in (1, 2, 3))


def refresh_notification_candidates(rows):
    return freshness.apply_freshness(rows, candidate=is_notification_candidate)


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
            CREATE TABLE IF NOT EXISTS delivery_outbox (
                digest_id TEXT PRIMARY KEY, payload TEXT NOT NULL, synced_at TEXT);
        ''')
        self.db.row_factory = sqlite3.Row

    def close(self):
        self.db.close()

    def prepare(self, rows, subscribers, day=None, refresh=refresh_notification_candidates,
                public_check=is_public_repository):
        """재생성 시 최신성을 재확인한다. 초안은 발송 실적으로 집계하지 않는다."""
        day = day or korean_day()
        subscribers = list(subscribers)
        date.fromisoformat(day)
        candidates = radar.unique_issues(rows)
        candidates = [row for row in candidates if is_notification_candidate(row)
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
            # 전달받은 전체 수신 목록을 기준으로 미발송 초안을 재작성한다.
            # 수신 거부·구독 해지·날짜 변경으로 빠진 초안을 재사용하지 않는다.
            self.db.execute("DELETE FROM digests WHERE state='prepared'")
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
                if current and current['state'] != 'prepared':
                    continue
                sent = {(row['repo'], row['number']) for row in self.db.execute(
                    'SELECT repo,number FROM sent_issues WHERE user_id=?', (user_id,))}
                selected = []
                for row in candidates:
                    repo, number = radar.issue_key(row)
                    if (repo in subscriptions and (repo, number) not in sent
                            and row.get('grade', {}).get('difficulty') == subscriber.get('difficulty', 1)):
                        selected.append({key: row.get(key) for key in (
                            'repo', 'number', 'url', 'title', 'grade', 'freshness',
                            'model', 'criteria_version')})
                    if len(selected) == DAILY_LIMIT:
                        break
                if not selected:
                    if current:
                        self.db.execute('DELETE FROM digests WHERE id=?', (current['id'],))
                    continue
                # 받는 주소나 실제 메일 내용이 달라지면 이전 초안 ID는 무효가 된다.
                content = [user_id, day, email, [
                    [item['repo'], item['number'], item['url'], item['title'],
                     item['grade']['difficulty']]
                    for item in selected]]
                digest_id = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()
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
                 '난이도: Lv.1 쉬움 / Lv.2 보통 / Lv.3 어려움', '']
        for item in items:
            level = item['grade']['difficulty']
            label = {1: '쉬움', 2: '보통', 3: '어려움'}[level]
            lines += [f"{item['repo']} #{item['number']} - Lv.{level} {label}", item['title'], item['url'], '']
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

    def export_prepared(self, prepared, directory):
        """현재 실행이 생성한 초안만 남긴다. 이미 복사한 외부 파일은 회수할 수 없다."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 새 준비가 끝난 뒤 이전 자동 생성 파일만 지운다. 수동 파일은 건드리지 않는다.
        for path in directory.glob('*.eml'):
            if re.fullmatch(r'[0-9a-f]{64}', path.stem):
                path.unlink()
        for item in prepared:
            self.export(item['id'], directory)

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
            if row['state'] != 'prepared':
                raise ValueError('자동 발송이 시작된 초안은 수동 확인할 수 없습니다')
            for item in json.loads(row['items']):
                repo, number = radar.issue_key(item)
                self.db.execute('INSERT INTO sent_issues VALUES (?,?,?,?)',
                                (row['user_id'], repo, number, digest_id))
            confirmed_at = datetime.now(timezone.utc).isoformat()
            self.db.execute('UPDATE digests SET state=?,confirmed_at=? WHERE id=?',
                            ('operator_confirmed', confirmed_at, digest_id))
            self.queue_delivery(dict(row), confirmed_at)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise


    def queue_delivery(self, row, confirmed_at):
        payload = {'user_id': row['user_id'], 'digest_id': row['id'], 'day': row['day'],
                   'items': [{key: item[key] for key in ('repo', 'number', 'url', 'title')}
                             for item in json.loads(row['items'])],
                   'confirmed_at': confirmed_at, 'state': 'operator_confirmed'}
        self.db.execute('INSERT OR IGNORE INTO delivery_outbox VALUES (?,?,NULL)',
                        (row['id'], json.dumps(payload, ensure_ascii=False)))

    def sync_deliveries(self, publish):
        # 이전 버전에서 기록한 발송 확인도 동일 ID로 한 번만 대기열에 넣는다.
        for row in self.db.execute("SELECT * FROM digests WHERE state='operator_confirmed'"):
            self.queue_delivery(dict(row), row['confirmed_at'])
        self.db.commit()
        count = 0
        for row in self.db.execute('SELECT * FROM delivery_outbox WHERE synced_at IS NULL').fetchall():
            publish(**json.loads(row['payload']))
            # 원격 성공 뒤에만 ACK한다. 중간 중단 시 서버 idempotency로 중복 처리한다.
            self.db.execute('UPDATE delivery_outbox SET synced_at=? WHERE digest_id=?',
                            (datetime.now(timezone.utc).isoformat(), row['digest_id']))
            self.db.commit()
            count += 1
        return count


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
    commands.add_parser('sync', help='발송 재전송 없이 운영자 확인 기록만 공유 DB로 재시도')
    args = parser.parse_args()
    store = ManualDelivery(args.state)
    try:
        if args.command == 'prepare':
            import accounts
            prepared = store.prepare(radar.read_jsonl(args.input), accounts.delivery_subscribers())
            store.export_prepared(prepared, args.output)
            for item in prepared:
                print(f"초안 {item['id']} - {item['count']}건")
            print('초안만 생성했습니다. 메일을 보내지 않았습니다.')
        else:
            if args.command == 'confirm-sent':
                changed = store.confirm_sent(args.digest_id)
                print('운영자 발송 확인을 로컬에 기록했습니다.' if changed else '이미 확인한 발송입니다.')
            from contribution_tracking import record_delivery, StateConflict
            try:
                count = store.sync_deliveries(record_delivery)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, StateConflict):
                print('공유 DB 동기화 대기: 로컬 발송 확인은 보존했습니다. 메일 재발송 없이 sync 명령으로 재시도하세요.', file=sys.stderr)
                return 1
            print(f'공유 DB 발송 확인 동기화: {count}건')
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
        print('처리 실패: 입력·계정 DB·운영자 전용 저장 경로를 확인하세요.', file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == '__main__':
    sys.exit(main())
