import contextlib
from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import patch

import community
import metrics
import metrics_report
from api.events import handler as EventsHandler
from api.feedback import handler as FeedbackHandler


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 26, 0, 30, tzinfo=timezone.utc)


class MetricsTests(unittest.TestCase):
    def test_allowed_events_use_utc_daily_hash_and_90_day_expiry(self):
        with patch.object(metrics, "datetime", FixedDatetime), patch.object(community, "redis", return_value=1) as redis:
            for name in metrics.EVENTS:
                metrics.record_event(name)
                self.assertEqual(redis.call_args.args, ("EVAL", metrics.COUNT_SCRIPT, 1,
                                 "repobite:events:2026-10-26", name, 7776000))
                self.assertIn("HINCRBY", metrics.COUNT_SCRIPT)
                self.assertIn("EXPIRE", metrics.COUNT_SCRIPT)
            for name in ("unknown", None, [], 1):
                with self.assertRaises(ValueError):
                    metrics.record_event(name)

    def test_hourly_event_limit_silently_drops_excess(self):
        with patch.object(community, "redis", return_value=3001) as redis:
            self.assertIsNone(metrics.record_event("visit"))
            redis.assert_called_once_with("EVAL", metrics.RATE_SCRIPT, 1, "repobite:event-rate")
        with patch.object(community, "redis", return_value=3000) as redis:
            metrics.record_event("visit")
            self.assertEqual(redis.call_count, 2)
        self.assertIn("3600", metrics.RATE_SCRIPT)

    def test_feedback_trim_length_rate_and_atomic_500_item_retention(self):
        with patch.object(metrics, "datetime", FixedDatetime), patch.object(community, "redis", return_value=20) as redis:
            metrics.record_feedback("  의견  ")
            args = redis.call_args.args
            self.assertEqual(args[:5], ("EVAL", metrics.FEEDBACK_SCRIPT, 2,
                             "repobite:feedback", "repobite:events:2026-10-26"))
            self.assertEqual(json.loads(args[5]), {"text": "의견", "created_at": "2026-10-26T00:30:00+00:00"})
            self.assertEqual(args[6], 7776000)
            self.assertIn("'LTRIM',KEYS[1],0,499", metrics.FEEDBACK_SCRIPT)
            self.assertIn("'HINCRBY',KEYS[2],'feedback',1", metrics.FEEDBACK_SCRIPT)
            metrics.record_feedback("a" * 500)
            for text in ("", "  ", "a" * 501, None, []):
                with self.assertRaises(ValueError):
                    metrics.record_feedback(text)
        with patch.object(community, "redis", return_value=21) as redis:
            with self.assertRaises(OverflowError):
                metrics.record_feedback("의견")
            redis.assert_called_once_with("EVAL", metrics.RATE_SCRIPT, 1, "repobite:feedback-rate")

    def test_query_functions_return_zero_filled_days_and_recent_feedback(self):
        with patch.object(metrics, "datetime", FixedDatetime), patch.object(community, "redis", side_effect=[[], ["visit", "3", "feedback", "1"]]) as redis:
            rows = metrics.event_counts(2)
            self.assertEqual([row["date"] for row in rows], ["2026-10-25", "2026-10-26"])
            self.assertEqual(rows[0]["visit"], 0)
            self.assertEqual(rows[1]["visit"], 3)
            self.assertEqual(rows[1]["feedback"], 1)
            self.assertEqual(rows[1]["issue_click"], 0)
            self.assertEqual(redis.call_args.args, ("HGETALL", "repobite:events:2026-10-26"))
        with patch.object(community, "redis", return_value=['{"text":"의견","created_at":"now"}']) as redis:
            self.assertEqual(metrics.recent_feedback(20)[0]["text"], "의견")
            redis.assert_called_once_with("LRANGE", "repobite:feedback", 0, 19)
        for value in (0, 91, True, "14"):
            with self.assertRaises(ValueError):
                metrics.event_counts(value)
        for value in (0, 501, True, "20"):
            with self.assertRaises(ValueError):
                metrics.recent_feedback(value)

    def test_report_removes_terminal_control_sequences_and_preserves_text(self):
        output = io.StringIO()
        with patch.object(metrics, "event_counts", return_value=[{"date": "2026-10-26", "visit": 1, "featured_click": 2, "issue_click": 3, "feedback": 1}]), patch.object(metrics, "recent_feedback", return_value=[{"created_at": "now", "text": "의견\x1b[31m빨강\x1b[0m\x07\n다음 줄"}]), contextlib.redirect_stdout(output):
            metrics_report.main(["--days", "14"])
        self.assertIn("| 2026-10-26 | 1 | 2 | 3 | 1 |", output.getvalue())
        self.assertIn("의견빨강\n다음 줄", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())
        self.assertEqual(metrics_report.terminal_text("a\x1b]0;title\x07b"), "ab")


def request(handler_type, body, headers=None, method="POST"):
    handler = handler_type.__new__(handler_type)
    handler.command = method
    handler.headers = {"Origin": "https://repobite.vercel.app", "Content-Type": "application/json",
                       "Content-Length": str(len(body)), **(headers or {})}
    handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
    response = {}
    handler.send_response = lambda status: response.update(status=status)
    handler.send_header = lambda name, value: response.update({name: value})
    handler.end_headers = lambda: None
    getattr(handler, "do_" + method)()
    response["body"] = handler.wfile.getvalue()
    return response


class ApiTests(unittest.TestCase):
    def test_both_apis_require_production_origin_and_json_before_reading_or_writing(self):
        for handler in (EventsHandler, FeedbackHandler):
            for headers in ({"Origin": "https://evil.example"}, {"Origin": ""}, {"Content-Type": "text/plain"}, {"Content-Type": ""}):
                with patch.object(community, "redis") as redis:
                    self.assertEqual(request(handler, b'{}', headers)["status"], 403)
                    redis.assert_not_called()

    def test_invalid_json_and_body_limits_are_rejected(self):
        for handler, limit in ((EventsHandler, 256), (FeedbackHandler, 2048)):
            with patch.object(community, "redis") as redis:
                self.assertEqual(request(handler, b"a" * (limit + 1))["status"], 413)
                for body in (b"{", b"[]", b"null", b"\xff"):
                    self.assertEqual(request(handler, body)["status"], 400)
                for size in ("-1", "bad", "", "3"):
                    self.assertEqual(request(handler, b"{}", {"Content-Length": size})["status"], 400)
                redis.assert_not_called()

    def test_post_only(self):
        for handler in (EventsHandler, FeedbackHandler):
            for method in ("GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"):
                response = request(handler, b"", method=method)
                self.assertEqual(response["status"], 405)
                self.assertEqual(response["Allow"], "POST")

    def test_events_return_204_for_success_limit_and_db_failure_but_400_for_input(self):
        for count in (1, 3001):
            with patch.object(community, "redis", return_value=count):
                response = request(EventsHandler, b'{"name":"visit"}')
                self.assertEqual(response["status"], 204)
                self.assertEqual(response["body"], b"")
        with patch.object(community, "redis", side_effect=RuntimeError("db")):
            self.assertEqual(request(EventsHandler, b'{"name":"visit"}')["status"], 204)
        for body in (b'{}', b'{"name":"unknown"}', b'{"name":[]}'):
            self.assertEqual(request(EventsHandler, body)["status"], 400)

    def test_feedback_success_input_rate_and_database_errors(self):
        with patch.object(community, "redis", return_value=1):
            response = request(FeedbackHandler, b'{"text":"hello"}', {"Content-Type": "application/json; charset=utf-8"})
            self.assertEqual(response["status"], 201)
        self.assertEqual(request(FeedbackHandler, b'{"text":" "}')["status"], 400)
        with patch.object(community, "redis", return_value=21):
            self.assertEqual(request(FeedbackHandler, b'{"text":"hello"}')["status"], 429)
        with patch.object(community, "redis", side_effect=RuntimeError("secret db error")):
            response = request(FeedbackHandler, b'{"text":"hello"}')
            self.assertEqual(response["status"], 503)
            self.assertNotIn(b"secret", response["body"])


if __name__ == "__main__":
    unittest.main()
