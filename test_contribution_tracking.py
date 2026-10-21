"""기여 상태, GitHub 근거, Redis 원자적 재시도, 개인 API 경계의 모의 검사."""

from copy import deepcopy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch

import accounts
from api.contributions import handler
import contribution_tracking as tracking
from test_accounts import MemoryRedis


REPO = {"id": 100, "full_name": "Owner/Project", "private": False, "visibility": "public"}
PR_URL = "https://github.com/owner/project/pull/50"


def pull_request(**changes):
    value = {"number": 50, "html_url": PR_URL, "user": {"id": 10, "login": "renamed-user"},
             "base": {"repo": deepcopy(REPO)}, "state": "open", "merged": False, "merged_at": None}
    return {**value, **changes}


class ContributionRedis(MemoryRedis):
    """상태와 이벤트를 원자적으로 CAS 처리하는 Redis 테스트 대역."""

    def __init__(self):
        super().__init__()
        self.before_commit = None
        self.fail_before_commit = False
        self.fail_after_commit = False

    def __call__(self, command, *args):
        if command == "HSETNX":
            key, field, value = args
            if self("HGET", key, field) is not None:
                return 0
            return self("HSET", key, field, value)
        if command != "EVAL" or args[0] != tracking.COMMIT_EVENT:
            return super().__call__(command, *args)
        _, count, records, receipts, event_id, fingerprint, issue_key, expected, record, receipt = args
        assert count == 2
        if self.before_commit:
            callback, self.before_commit = self.before_commit, None
            callback()
        saved = self("HGET", receipts, event_id)
        if saved:
            saved = json.loads(saved)
            if saved["fingerprint"] != fingerprint:
                return json.dumps({"status": "event_conflict"})
            return json.dumps({"status": "replayed", "result": saved["result"]})
        if (self("HGET", records, issue_key) or "") != expected:
            return json.dumps({"status": "retry"})
        if self.fail_before_commit:
            raise RuntimeError("fixture storage error")
        decoded = json.loads(receipt)
        if decoded["result"]["changed"]:
            self("HSET", records, issue_key, record)
        self("HSET", receipts, event_id, receipt)
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise RuntimeError("fixture response lost after atomic commit")
        return json.dumps({"status": "saved", "result": decoded["result"]})


class Fixture:
    def setUp(self):
        self.db = ContributionRedis()
        self.db_patch = patch.object(tracking.community, "redis", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.github = patch.object(accounts, "github_json", side_effect=self.github_response)
        self.github_mock = self.github.start()
        self.addCleanup(self.github.stop)
        self.repo_info = deepcopy(REPO)
        self.pr_info = pull_request()
        self.issue_changes = {}
        self.issue_error = None
        self.event_number = 0

    def github_response(self, request):
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.get_header("Authorization"))
        if request.full_url == "https://api.github.com/repos/owner/project":
            return deepcopy(self.repo_info)
        if "/issues/" in request.full_url:
            if self.issue_error:
                raise self.issue_error
            number = int(request.full_url.rsplit("/", 1)[1])
            return {"number": number, "html_url": f"https://github.com/owner/project/issues/{number}",
                    "state": "open", **deepcopy(self.issue_changes)}
        self.assertEqual(request.full_url, "https://api.github.com/repos/owner/project/pulls/50")
        return deepcopy(self.pr_info)

    def event(self, action, *, user="10", number=7, event_id=None, pr_url=None, delivery_id=None):
        self.event_number += 1
        return tracking.record_event(user, action, "Owner/Project", number,
                                     event_id or f"fixture-event-{self.event_number}", pr_url, delivery_id)

    def saved(self, user="10"):
        return tracking.user_contributions(user)


class ContributionTests(Fixture, unittest.TestCase):
    def test_start_cancel_resume_are_separate_persistent_events_and_duplicates_are_noops(self):
        first = self.event("start")
        self.assertEqual(first["record"]["activity"], "active")
        self.assertTrue(first["changed"])
        self.assertFalse(self.event("start")["changed"])
        self.assertEqual(self.event("cancel")["record"]["activity"], "cancelled")
        self.assertFalse(self.event("cancel")["changed"])
        self.assertEqual(self.event("resume")["record"]["activity"], "active")
        self.assertFalse(self.event("resume")["changed"])
        record, = self.saved()["records"]
        self.assertEqual([event["type"] for event in record["events"]], ["started", "cancelled", "resumed"])
        self.assertEqual(record["delivery_linkage"], {"status": "not_connected", "delivery_id": None})
        self.assertFalse(self.saved()["summary"]["delivery_conversion_measured"])
        self.assertFalse(self.saved()["summary"]["automatic_level_expansion"])
        self.assertEqual(self.github_mock.call_count, 2)

    def test_invalid_transitions_preserve_prior_state(self):
        for action in ("cancel", "resume", "verify_pr"):
            with self.subTest(action=action), self.assertRaises(tracking.StateConflict):
                self.event(action, pr_url=PR_URL if action == "verify_pr" else None)
        self.event("start")
        self.event("cancel")
        before = self.saved()
        with self.assertRaises(tracking.StateConflict):
            self.event("start")
        self.assertEqual(self.saved(), before)

    def test_same_event_retry_is_replayed_without_revalidating_github_or_adding_events(self):
        original = self.event("submit_pr", event_id="one-immutable-event", pr_url=PR_URL)
        self.github_mock.reset_mock()
        replay = self.event("submit_pr", event_id="one-immutable-event", pr_url=PR_URL.replace("owner/project", "OWNER/PROJECT"))
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["record"], original["record"])
        self.github_mock.assert_not_called()
        self.assertEqual(len(self.saved()["records"][0]["events"]), 1)
        with self.assertRaises(tracking.StateConflict):
            self.event("submit_pr", number=8, event_id="one-immutable-event", pr_url=PR_URL)

    def test_account_namespace_prevents_reads_cancellations_and_event_key_collisions(self):
        self.event("start", event_id="shared-event-key")
        self.assertEqual(self.saved("20")["records"], [])
        with self.assertRaises(tracking.StateConflict):
            self.event("cancel", user="20")
        self.event("start", user="20", event_id="shared-event-key")
        self.event("cancel", user="20")
        self.assertEqual(self.saved()["records"][0]["activity"], "active")
        self.assertEqual(self.saved("20")["records"][0]["activity"], "cancelled")

    def test_pr_submission_is_not_an_implicit_start_or_success_and_records_user_declared_link(self):
        record = self.event("submit_pr", pr_url=PR_URL)["record"]
        self.assertEqual(record["activity"], "not_started")
        self.assertEqual([event["type"] for event in record["events"]], ["pr_submitted"])
        evidence = record["pull_requests"][PR_URL]
        self.assertEqual(evidence["author_id"], "10")
        self.assertEqual(evidence["issue_link_basis"], "user_declared")
        self.assertFalse(evidence["issue_closure_verified"])
        self.assertEqual(evidence["provider_api_url"], "https://api.github.com/repos/owner/project/pulls/50")
        self.assertTrue(evidence["provider_checked_at"])
        self.assertEqual(self.saved()["summary"]["merged_pr_count"], 0)

    def test_only_verified_author_id_and_merged_at_count_as_success_even_after_cancellation(self):
        self.event("start")
        self.event("submit_pr", pr_url=PR_URL)
        self.pr_info = pull_request(state="closed", merged=True, merged_at="2026-10-21T02:00:00Z")
        record = self.event("verify_pr", pr_url=PR_URL)["record"]
        self.assertEqual([event["type"] for event in record["events"]], ["started", "pr_submitted", "pr_verified", "pr_merged"])
        self.event("cancel")
        self.assertEqual(self.saved()["summary"]["merged_pr_count"], 1)
        self.assertEqual(self.saved()["records"][0]["activity"], "cancelled")
        self.event("verify_pr", pr_url=PR_URL)
        self.assertEqual(sum(event["type"] == "pr_merged" for event in self.saved()["records"][0]["events"]), 1)

    def test_closed_unmerged_pr_is_not_success_and_same_merged_pr_is_counted_once_across_issues(self):
        self.pr_info = pull_request(state="closed")
        self.event("submit_pr", pr_url=PR_URL)
        self.assertEqual(self.saved()["summary"]["merged_pr_count"], 0)
        self.pr_info = pull_request(state="closed", merged=True, merged_at="2026-10-21T02:00:00Z")
        self.event("verify_pr", pr_url=PR_URL)
        self.event("submit_pr", number=8, pr_url=PR_URL)
        summary = self.saved()["summary"]
        self.assertEqual(summary["tracked_issues"], 2)
        self.assertEqual(summary["merged_pr_count"], 1)

    def test_forged_author_or_base_or_provider_identity_never_saves(self):
        variants = [pull_request(user={"id": 20, "login": "same-name"}),
                    pull_request(user={"id": True}), pull_request(number=51),
                    pull_request(html_url="https://evil.test/pr/50"),
                    pull_request(base={"repo": {**REPO, "id": 999}}),
                    pull_request(base={"repo": {**REPO, "full_name": "other/project"}}),
                    pull_request(base={"repo": {**REPO, "private": True}})]
        for value in variants:
            self.pr_info = value
            with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                self.event("submit_pr", pr_url=PR_URL)
            self.assertEqual(self.saved()["records"], [])

    def test_private_or_unverified_repository_is_rejected_before_persisting(self):
        for changes in ({"private": True}, {"private": None}, {"visibility": "internal"},
                        {"id": None}, {"full_name": "different/repo"}):
            self.repo_info = {**REPO, **changes}
            for action in ("start", "submit_pr"):
                with self.subTest(changes=changes, action=action), self.assertRaises((ValueError, RuntimeError)):
                    self.event(action, pr_url=PR_URL if action == "submit_pr" else None)
                self.assertEqual(self.saved()["records"], [])

    def test_first_start_and_pr_report_require_a_real_issue_instead_of_a_pr_or_wrong_number(self):
        for changes in ({"number": 999}, {"html_url": "https://github.com/other/project/issues/7"},
                        {"html_url": "https://github.com/owner/project/pull/7"},
                        {"pull_request": {"url": "https://api.github.com/repos/owner/project/pulls/7"}},
                        {"pull_request": None}):
            self.issue_changes = changes
            for action in ("start", "submit_pr"):
                with self.subTest(changes=changes, action=action), self.assertRaises(ValueError):
                    self.event(action, pr_url=PR_URL if action == "submit_pr" else None)
                self.assertEqual(self.saved()["records"], [])

    def test_nonexistent_issue_and_issue_api_failure_preserve_existing_records(self):
        self.event("start")
        before = self.saved()
        for failure in (RuntimeError("fixture GitHub 404"), OSError("fixture timeout")):
            self.issue_error = failure
            for action in ("start", "submit_pr"):
                with self.subTest(action=action), self.assertRaises((RuntimeError, OSError)):
                    self.event(action, number=8, pr_url=PR_URL if action == "submit_pr" else None)
                self.assertEqual(self.saved(), before)

    def test_closed_real_issue_allows_historical_contribution_record(self):
        self.issue_changes = {"state": "closed"}
        record = self.event("submit_pr", pr_url=PR_URL)["record"]
        self.assertEqual(record["activity"], "not_started")
        self.assertTrue(record["issue_existence_verified_at"])

    def test_external_or_mismatched_pr_url_is_never_fetched(self):
        for url in ("https://evil.test/owner/project/pull/50", "http://github.com/owner/project/pull/50",
                    "https://github.com@evil.test/owner/project/pull/50", PR_URL + "?secret=value",
                    PR_URL + "#fragment", "https://github.com/other/repo/pull/50", PR_URL.replace("/pull/", "/issues/")):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.event("submit_pr", pr_url=url)
        self.github_mock.assert_not_called()
        self.assertEqual(self.saved()["records"], [])

    def test_inconsistent_or_malformed_merged_fields_do_not_create_success(self):
        for changes in ({"merged": True}, {"merged_at": "2026-10-21T02:00:00Z"},
                        {"merged": True, "merged_at": "not-a-timestamp", "state": "closed"},
                        {"merged": True, "merged_at": "2026-10-21", "state": "closed"},
                        {"merged": True, "merged_at": "2026-10-21T02:00:00Z"}, {"state": "unknown"}):
            self.pr_info = pull_request(**changes)
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.event("submit_pr", pr_url=PR_URL)
            self.assertEqual(self.saved()["summary"]["merged_pr_count"], 0)

    def test_github_failure_and_invalid_regression_preserve_previous_evidence(self):
        self.event("submit_pr", pr_url=PR_URL)
        before = self.saved()
        for failure in (RuntimeError("fixture GitHub unavailable"), OSError("fixture timeout")):
            with patch.object(accounts, "github_json", side_effect=failure), self.assertRaises((RuntimeError, OSError)):
                self.event("verify_pr", pr_url=PR_URL)
            self.assertEqual(self.saved(), before)
        self.pr_info = pull_request(state="closed", merged=True, merged_at="2026-10-21T02:00:00Z")
        self.event("verify_pr", pr_url=PR_URL)
        before = self.saved()
        self.pr_info = pull_request()
        with self.assertRaises(RuntimeError):
            self.event("verify_pr", pr_url=PR_URL)
        self.assertEqual(self.saved(), before)

    def test_before_commit_failure_preserves_state_and_retry_can_succeed(self):
        self.event("start")
        before = self.saved()
        self.db.fail_before_commit = True
        with self.assertRaises(RuntimeError):
            self.event("cancel", event_id="retry-cancel-event")
        self.assertEqual(self.saved(), before)
        self.db.fail_before_commit = False
        result = self.event("cancel", event_id="retry-cancel-event")
        self.assertFalse(result["replayed"])
        self.assertEqual(result["record"]["activity"], "cancelled")

    def test_lost_commit_response_can_be_retried_without_duplicate_events(self):
        self.event("start")
        self.db.fail_after_commit = True
        with self.assertRaises(RuntimeError):
            self.event("cancel", event_id="lost-response-event")
        replay = self.event("cancel", event_id="lost-response-event")
        self.assertTrue(replay["replayed"])
        self.assertEqual([event["type"] for event in self.saved()["records"][0]["events"]], ["started", "cancelled"])

    def test_concurrent_resume_reloads_new_state_without_losing_intervening_cancellation(self):
        self.event("start")
        self.db.before_commit = lambda: self.event("cancel", event_id="concurrent-cancel")
        self.event("resume", event_id="outer-resume")
        self.assertEqual([event["type"] for event in self.saved()["records"][0]["events"]], ["started", "cancelled", "resumed"])

class HTTPFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.secret = "a" * 43
        self.other_secret = "b" * 43
        for secret, user_id in ((self.secret, "10"), (self.other_secret, "20")):
            self.db("SET", accounts.session_key(secret), user_id, "EX", accounts.SESSION_SECONDS)
            self.db("HSET", accounts.USERS_KEY, user_id, json.dumps({"id": user_id, "login": "current"}))

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, *, action="", method="GET", payload=None, secret=None, origin=accounts.PUBLIC_ORIGIN, raw=None, expected="auto"):
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if secret is not None:
            headers["Cookie"] = accounts.SESSION_COOKIE + "=" + secret
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        query = "/api/contributions?action=" + action
        if method == "GET":
            expected = ("20" if secret == self.other_secret else "10") if expected == "auto" else expected
            if expected is not None:
                query += "&expected_user_id=" + expected
        connection.request(method, query, body, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), dict(response.getheaders())
        connection.close()
        return result

    def payload(self, **changes):
        return {"expected_user_id": "10", "event_id": "http-event-start", "repo": "owner/project", "number": 7, **changes}


class ContributionHTTPTests(HTTPFixture, unittest.TestCase):
    def test_session_canonical_origin_and_expected_account_are_write_preconditions(self):
        self.assertEqual(self.request()[0], 401)
        for origin in (None, "https://evil.test", "https://repobite.vercel.app.evil.test"):
            self.assertEqual(self.request(action="start", method="POST", payload=self.payload(), secret=self.secret, origin=origin)[0], 403)
        self.assertEqual(self.request(action="start", method="POST", payload=self.payload())[0], 401)
        for expected in (None, "20", 10):
            status, body, _ = self.request(action="start", method="POST", payload=self.payload(expected_user_id=expected), secret=self.secret)
            self.assertEqual((status, body["code"]), (409, "account_changed"))
        self.assertEqual(self.saved()["records"], [])
        self.github_mock.assert_not_called()

    def test_stale_account_cannot_read_other_accounts_records(self):
        for expected in (None, "20", ""):
            status, body, _ = self.request(secret=self.secret, expected=expected)
            self.assertEqual((status, body["code"]), (409, "account_changed"))
            self.assertNotIn("records", body)
        self.assertEqual(self.request(secret=self.secret, expected="10")[0], 200)

    def test_private_list_and_mutation_are_bound_to_current_session_and_no_store(self):
        status, result, headers = self.request(action="start", method="POST", payload=self.payload(), secret=self.secret)
        self.assertEqual(status, 200)
        self.assertEqual(result["record"]["activity"], "active")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request(secret=self.other_secret)[1]["records"], [])
        status, body, _ = self.request(action="cancel", method="POST", payload=self.payload(event_id="other-cancel-event", expected_user_id="20"), secret=self.other_secret)
        self.assertEqual((status, body["code"]), (409, "state_conflict"))
        self.assertEqual(self.request(secret=self.secret)[1]["records"][0]["activity"], "active")

    def test_unknown_fields_fake_delivery_links_and_bad_json_cannot_mutate(self):
        for payload in (self.payload(user_id="20"), self.payload(number=True)):
            self.assertEqual(self.request(action="start", method="POST", payload=payload, secret=self.secret)[0], 400)
        self.assertEqual(self.request(action="start", method="POST", payload=self.payload(delivery_id="fake-delivery"), secret=self.secret)[0], 409)
        for raw in (b"{", b"[]", b"\xff", b"{}" * 1500):
            self.assertEqual(self.request(action="start", method="POST", secret=self.secret, raw=raw)[0], 400)
        self.assertEqual(self.saved()["records"], [])

    def test_github_failure_keeps_previous_record_and_does_not_expose_provider_detail(self):
        self.event("start")
        before = self.saved()
        with patch.object(accounts, "github_json", side_effect=RuntimeError("private-provider-error")):
            status, body, _ = self.request(action="submit_pr", method="POST", payload=self.payload(pr_url=PR_URL), secret=self.secret)
        self.assertEqual((status, body["code"]), (503, "service_unavailable"))
        self.assertNotIn("private-provider-error", str(body))
        self.assertEqual(self.saved(), before)


class DeliveryLinkTests(Fixture, unittest.TestCase):
    def delivery(self, *, user="10", digest="fixture-digest-001", number=7, **changes):
        return tracking.record_delivery(user, digest, changes.get("day", "2026-10-21"),
            changes.get("items", [{"repo": "Owner/Project", "number": number, "email": "not-stored@example.com"}]),
            changes.get("confirmed_at", "2026-10-21T02:10:00Z"), changes.get("state", "operator_confirmed"))

    def test_server_import_is_idempotent_operator_attestation_with_minimal_private_payload(self):
        imported = self.delivery()
        self.assertTrue(imported["created"])
        replay = self.delivery()
        self.assertFalse(replay["created"])
        self.assertEqual(imported["delivery"], replay["delivery"])
        saved, = self.saved()["deliveries"]
        self.assertEqual(saved["state"], "operator_confirmed")
        self.assertEqual(saved["attestation_basis"], "operator_confirmation")
        self.assertFalse(saved["provider_delivery_verified"])
        self.assertEqual(saved["items"], [{"repo": "owner/project", "number": 7}])
        self.assertNotIn("email", json.dumps(saved))
        self.assertNotIn("user_id", json.dumps(saved))
        self.assertEqual(self.saved("20")["deliveries"], [])
        self.assertEqual(self.saved()["summary"]["operator_confirmed_digest_count"], 1)
        self.assertFalse(self.saved()["summary"]["delivery_conversion_measured"])
        self.github_mock.assert_not_called()

    def test_server_import_cannot_replace_existing_digest_or_record_prepared_provider_success(self):
        self.delivery()
        before = self.saved()
        with self.assertRaises(tracking.StateConflict):
            self.delivery(number=8)
        for changes in ({"state": "prepared"}, {"state": "provider_sent"}, {"day": "20261021"},
                        {"confirmed_at": "2026-10-21"}, {"items": []},
                        {"items": [{"repo": "owner/project", "number": 7}] * 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.delivery(digest="another-digest-id", **changes)
        self.assertEqual(self.saved(), before)

    def test_actions_link_only_server_verified_current_user_and_matching_issue_digest(self):
        self.delivery()
        self.delivery(user="20", digest="other-user-digest", number=8)
        for digest, number in (("other-user-digest", 8), ("fixture-digest-001", 8), ("unknown-digest-id", 7)):
            with self.subTest(digest=digest, number=number), self.assertRaises(tracking.StateConflict):
                self.event("start", number=number, delivery_id=digest)
        self.assertEqual(self.saved()["records"], [])
        record = self.event("start", delivery_id="fixture-digest-001")["record"]
        self.assertEqual(record["delivery_linkage"]["delivery_ids"], ["fixture-digest-001"])
        self.assertFalse(record["delivery_linkage"]["provider_delivery_verified"])
        self.assertTrue(all(event["delivery_id"] == "fixture-digest-001" for event in record["events"]))
        self.assertEqual(self.saved()["summary"]["merged_pr_count"], 0)

    def test_linking_a_noop_action_records_attestation_without_duplicating_start(self):
        self.event("start")
        self.delivery()
        linked = self.event("start", event_id="attach-delivery-event", delivery_id="fixture-digest-001")
        self.assertTrue(linked["changed"])
        replay = self.event("start", event_id="attach-delivery-event", delivery_id="fixture-digest-001")
        self.assertTrue(replay["replayed"])
        self.assertFalse(self.event("start", delivery_id="fixture-digest-001")["changed"])
        events = self.saved()["records"][0]["events"]
        self.assertEqual([event["type"] for event in events], ["started", "delivery_linked"])
        with self.assertRaises(tracking.StateConflict):
            self.event("start", event_id="attach-delivery-event")

    def test_delivery_storage_failure_can_be_retried_without_forged_success(self):
        def unavailable(command, *args):
            if command == "HSETNX":
                raise RuntimeError("fixture unavailable")
            return self.db(command, *args)
        with patch.object(tracking.community, "redis", side_effect=unavailable):
            with self.assertRaises(RuntimeError):
                self.delivery()
        self.assertEqual(self.saved()["deliveries"], [])
        self.assertTrue(self.delivery()["created"])
        self.assertFalse(self.delivery()["created"])


class DeliveryLinkHTTPTests(HTTPFixture, unittest.TestCase):
    def test_browser_can_link_its_digest_but_cannot_create_or_modify_deliveries(self):
        tracking.record_delivery("10", "http-digest-owner", "2026-10-21",
            [{"repo": "owner/project", "number": 7}], "2026-10-21T02:10:00Z")
        status, response, _ = self.request(action="start", method="POST",
            payload=self.payload(delivery_id="http-digest-owner"), secret=self.secret)
        self.assertEqual(status, 200)
        self.assertEqual(response["record"]["delivery_linkage"]["status"], "operator_confirmed")
        other = self.payload(expected_user_id="20", delivery_id="http-digest-owner")
        self.assertEqual(self.request(action="start", method="POST", payload=other, secret=self.other_secret)[0], 409)
        self.assertEqual(self.request(action="record_delivery", method="POST", payload=self.payload(), secret=self.secret)[0], 400)
        self.assertEqual(self.request(secret=self.other_secret)[1]["deliveries"], [])
        body = self.request(secret=self.secret)[1]
        self.assertEqual(len(body["deliveries"]), 1)
        self.assertNotIn("email", json.dumps(body))
        self.assertNotIn("user_id", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
