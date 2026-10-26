"""식별자 없이 일별 반응 횟수와 익명 의견만 보관한다."""

from datetime import datetime, timedelta, timezone
import json

import community

EVENTS = ("visit", "featured_click", "issue_click")
RETENTION_SECONDS = 90 * 24 * 60 * 60
FEEDBACK_KEY = "repobite:feedback"
RATE_SCRIPT = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],3600) end; return n"
COUNT_SCRIPT = "redis.call('HINCRBY',KEYS[1],ARGV[1],1); redis.call('EXPIRE',KEYS[1],ARGV[2]); return 1"
FEEDBACK_SCRIPT = ("redis.call('LPUSH',KEYS[1],ARGV[1]); redis.call('LTRIM',KEYS[1],0,499); "
                   "redis.call('HINCRBY',KEYS[2],'feedback',1); "
                   "redis.call('EXPIRE',KEYS[2],ARGV[2]); return 1")


def daily_key(day):
    return "repobite:events:" + day.isoformat()


def record_event(name):
    if not isinstance(name, str) or name not in EVENTS:
        raise ValueError("집계 항목을 확인하세요.")
    if community.redis("EVAL", RATE_SCRIPT, 1, "repobite:event-rate") > 3000:
        return
    day = datetime.now(timezone.utc).date()
    community.redis("EVAL", COUNT_SCRIPT, 1, daily_key(day), name, RETENTION_SECONDS)


def record_feedback(text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
        raise ValueError("의견은 앞뒤 공백을 뺀 1~500자로 입력하세요.")
    text = text.strip()
    if community.redis("EVAL", RATE_SCRIPT, 1, "repobite:feedback-rate") > 20:
        raise OverflowError("지금은 의견이 많이 접수되고 있습니다. 잠시 후 다시 시도하세요.")
    now = datetime.now(timezone.utc)
    row = {"text": text, "created_at": now.isoformat(timespec="seconds")}
    community.redis("EVAL", FEEDBACK_SCRIPT, 2, FEEDBACK_KEY, daily_key(now.date()),
                    json.dumps(row, ensure_ascii=False), RETENTION_SECONDS)


def event_counts(days):
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("조회 일수는 1~90일로 지정하세요.")
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset in reversed(range(days)):
        day = today - timedelta(days=offset)
        values = community.redis("HGETALL", daily_key(day)) or []
        counts = dict(zip(values[::2], values[1::2]))
        rows.append({"date": day.isoformat(), **{name: int(counts.get(name, 0))
                     for name in (*EVENTS, "feedback")}})
    return rows


def recent_feedback(limit):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("의견 조회 수는 1~500건으로 지정하세요.")
    return [json.loads(row) for row in community.redis("LRANGE", FEEDBACK_KEY, 0, limit - 1)]
