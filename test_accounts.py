"""계정별 격리와 OAuth/HTTP 보안 회귀. 실행: python3 test_accounts.py."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
import threading
import unittest
from unittest.mock import patch
import collection
from urllib.parse import parse_qs, urlsplit

import accounts
from api.account import handler, cookie_header


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.hashes = {}
        self.expiries = {}
        self.now = 0

    def __call__(self, command, *args):
        if command == "SET":
            key, value, _, seconds = args
            self.values[key] = value
            self.expiries[key] = self.now + seconds
            return "OK"
        if command == "GET":
            key, = args
            if self.expiries.get(key, float("inf")) <= self.now:
                self.values.pop(key, None)
            return self.values.get(key)
        if command == "DEL":
            return int(self.values.pop(args[0], None) is not None)
        if command == "HSET":
            key, field, value = args
            record = self.hashes.setdefault(key, {})
            created = field not in record
            record[field] = value
            return int(created)
        if command == "HMGET":
            return [self.hashes.get(args[0], {}).get(field) for field in args[1:]]
        if command == "HGET":
            return self.hashes.get(args[0], {}).get(args[1])
        if command == "HKEYS":
            return list(self.hashes.get(args[0], {}))
        if command == "HVALS":
            return list(self.hashes.get(args[0], {}).values())
        if command == "HDEL":
            return int(self.hashes.get(args[0], {}).pop(args[1], None) is not None)
        if command == "EVAL":
            script, count, key, *values = args
            assert count == 1
            if "local v=" in script:
                value = self("GET", key)
                self("DEL", key)
                return value
            if "INCR" in script:
                value = self("GET", key) or 0
                self.values[key] = value + 1
                if not value:
                    self.expiries[key] = self.now + 3600
                return value + 1
            if "HEXISTS" in script:
                record = self.hashes.setdefault(key, {})
                if values[0] in record:
                    return 0
                if len(record) >= 300:
                    return -1
                return self("HSET", key, *values)
        raise AssertionError((command, args))


class AccountsFixture:
    def setUp(self):
        self.db = MemoryRedis()
        collect_patch = patch.object(collection, "request", return_value={"stage": "queued"})
        collect_patch.start()
        self.addCleanup(collect_patch.stop)
        self.db_patch = patch.object(accounts.community, "redis", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.environment = patch.dict(accounts.os.environ, {
            "GITHUB_OAUTH_CLIENT_ID": "test-client-id", "GITHUB_OAUTH_CLIENT_SECRET": "test-only-placeholder"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def login(self, github_id=10, login="octocat", previous_session=None):
        location, state = accounts.start_login()
        with patch.object(accounts, "github_json", side_effect=[
                {"access_token": "test-only-ephemeral-value"}, {"id": github_id, "login": login}]):
            secret = accounts.complete_login("temporary-code", state, state, previous_session)
        return secret


class AccountsTest(AccountsFixture, unittest.TestCase):
    def test_oauth_binds_browser_state_and_uses_fixed_callback_and_pkce(self):
        location, state = accounts.start_login()
        params = parse_qs(urlsplit(location).query)
        self.assertEqual(params["redirect_uri"], [accounts.CALLBACK_URL])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(len(params["code_challenge"][0]), 43)
        with patch.object(accounts, "github_json") as github:
            with self.assertRaises(accounts.AuthenticationRequired):
                accounts.complete_login("code", state, "a" * 43)
            github.assert_not_called()
        verifier = self.db.values[accounts.state_key(state)]
        with patch.object(accounts, "github_json", side_effect=[
                {"access_token": "test-only-ephemeral-value"}, {"id": 42, "login": "octocat"}]) as github:
            secret = accounts.complete_login("temporary-code", state, state)
            exchange, identity = [call.args[0] for call in github.call_args_list]
        payload = parse_qs(exchange.data.decode())
        self.assertEqual(payload["redirect_uri"], [accounts.CALLBACK_URL])
        self.assertEqual(payload["code_verifier"], [verifier])
        import base64
        import hashlib
        expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(params["code_challenge"], [expected_challenge])
        self.assertEqual(identity.full_url, "https://api.github.com/user")
        self.assertEqual(accounts.session_snapshot(secret)["user"]["id"], "42")
        persisted = json.dumps([self.db.values, self.db.hashes])
        self.assertNotIn("test-only-ephemeral-value", persisted)
        self.assertNotIn(secret, persisted)
        self.assertNotIn(state, persisted)
        self.assertIn(accounts.session_key(secret), persisted)
        with patch.object(accounts, "github_json") as github:
            with self.assertRaises(accounts.AuthenticationRequired):
                accounts.complete_login("temporary-code", state, state)
            github.assert_not_called()

    def test_expired_state_never_exchanges_a_code(self):
        _, state = accounts.start_login()
        self.db.now += accounts.STATE_SECONDS + 1
        with patch.object(accounts, "github_json") as github:
            with self.assertRaises(accounts.AuthenticationRequired):
                accounts.complete_login("code", state, state)
            github.assert_not_called()

    def test_login_rotation_logout_and_session_expiry_revoke_access(self):
        secret = self.login()
        rotated = self.login(previous_session=secret)
        self.assertFalse(accounts.session_snapshot(secret)["authenticated"])
        self.assertTrue(accounts.session_snapshot(rotated)["authenticated"])
        accounts.logout(rotated)
        self.assertFalse(accounts.session_snapshot(rotated)["authenticated"])
        fresh = self.login()
        self.db.now += accounts.SESSION_SECONDS + 1
        self.assertFalse(accounts.session_snapshot(fresh)["authenticated"])

    def test_each_account_reads_and_edits_only_its_subscriptions_and_preferences(self):
        first, second = self.login(10), self.login(20)
        with patch.object(accounts, "verified_repository", return_value="Owner/Repo") as github:
            self.assertTrue(accounts.subscribe("10", "owner/repo")["created"])
            self.assertFalse(accounts.subscribe("10", "OWNER/REPO")["created"])
            github.assert_called_once()
        accounts.save_preferences("10", " Person@Example.COM ", True)
        a, b = accounts.session_snapshot(first), accounts.session_snapshot(second)
        self.assertEqual(a["subscriptions"], ["Owner/Repo"])
        self.assertEqual(b["subscriptions"], [])
        self.assertEqual(a["preferences"]["email"], "Person@example.com")
        self.assertFalse(b["preferences"]["delivery_enabled"])
        self.assertFalse(accounts.unsubscribe("20", "owner/repo")["removed"])
        self.assertEqual(accounts.subscription_repositories(), ["Owner/Repo"])
        self.assertEqual(accounts.delivery_subscribers(), [{"user_id": "10", "email": "Person@example.com",
            "daily_limit": 3, "subscriptions": ["Owner/Repo"]}])
        self.assertTrue(accounts.unsubscribe("10", "owner/repo")["removed"])
        self.assertFalse(accounts.unsubscribe("10", "owner/repo")["removed"])
        self.assertEqual(accounts.subscription_repositories(), [])

    def test_github_identity_is_revalidated_and_rename_keeps_personal_settings(self):
        original = self.login(10, "before-rename")
        accounts.save_preferences("10", "saved@example.com", True)
        current = self.login(10, "after-rename", original)
        snapshot = accounts.session_snapshot(current)
        self.assertEqual(snapshot["user"]["login"], "after-rename")
        self.assertEqual(snapshot["preferences"]["email"], "saved@example.com")
        _, state = accounts.start_login()
        with patch.object(accounts, "github_json", side_effect=[
                {"access_token": "test-only-ephemeral-value"}, {"id": True, "login": "wrong"}]):
            with self.assertRaises(accounts.AuthenticationRequired):
                accounts.complete_login("code", state, state, current)
        self.assertTrue(accounts.session_snapshot(current)["authenticated"])

    def test_invalid_email_or_consent_preserves_saved_preferences(self):
        accounts.save_preferences("10", "valid@example.com", True)
        for invalid in (None, [], "missing-at", "a@@example.com", ".a@example.com", "a..b@example.com",
                        "a@-bad.com", "a@example..com", "a@example.com\r\nBcc:other@example.com"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                accounts.save_preferences("10", invalid, True)
        for email, consent in (("", True), ("valid@example.com", "true")):
            with self.assertRaises(ValueError):
                accounts.save_preferences("10", email, consent)
        self.assertEqual(accounts.preferences("10")["email"], "valid@example.com")
        accounts.save_preferences("10", "", False)
        self.assertEqual(accounts.delivery_subscribers(), [])

    def test_subscription_checks_public_active_issue_repository_before_writing(self):
        profile = {"full_name": "Owner/Repo", "private": False, "has_issues": True, "archived": False}
        for changes in ({"private": True}, {"has_issues": False}, {"archived": True}, {"disabled": True}):
            with patch.object(accounts, "urlopen", return_value=io.BytesIO(json.dumps({**profile, **changes}).encode())):
                with self.assertRaises(ValueError):
                    accounts.subscribe("10", "owner/repo")
                self.assertEqual(accounts.subscriptions("10"), [])
        with patch.object(accounts, "urlopen", return_value=io.BytesIO(json.dumps(profile).encode())):
            self.assertEqual(accounts.subscribe("10", "owner/repo"), {"repo": "Owner/Repo", "created": True})
        self.assertFalse(self.db.hashes.get(accounts.community.REPOS_KEY))

    def test_subscription_limit_and_rate_reject_without_mutation(self):
        self.db.hashes[accounts.subscriptions_key("10")] = {f"owner/r{i}": f"owner/r{i}" for i in range(300)}
        with patch.object(accounts, "verified_repository", return_value="owner/new"):
            with self.assertRaises(OverflowError):
                accounts.subscribe("10", "owner/new")
        self.assertEqual(len(accounts.subscriptions("10")), 300)
        self.db.values["repobite:accounts:subscription-rate:20"] = 30
        with patch.object(accounts, "verified_repository") as github:
            with self.assertRaises(OverflowError):
                accounts.subscribe("20", "owner/new")
            github.assert_not_called()


class AccountsHTTPTest(AccountsFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, action="session", method="GET", payload=None, secret=None, origin=accounts.PUBLIC_ORIGIN,
                extra_query="", cookie=None, raw=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        if secret:
            headers["Cookie"] = accounts.SESSION_COOKIE + "=" + secret
        if cookie:
            headers["Cookie"] = cookie
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        connection.request(method, "/api/account?action=" + action + extra_query, body, headers)
        response = connection.getresponse()
        content = response.read()
        result = (response.status, json.loads(content) if content else None, response.getheaders())
        connection.close()
        return result

    def test_unauthenticated_and_cross_origin_mutations_never_save(self):
        self.assertEqual(self.request()[1], {"authenticated": False})
        for action in ("preferences", "subscriptions"):
            self.assertEqual(self.request(action, "POST", {"email": "x@example.com", "repo": "owner/repo"})[0], 401)
        secret = self.login()
        for origin in (None, "https://evil.test", "https://repobite.vercel.app.evil.test"):
            self.assertEqual(self.request("preferences", "POST", {"email": "x@example.com", "delivery_enabled": True},
                secret, origin)[0], 403)
        self.assertFalse(self.db.hashes.get(accounts.PREFERENCES_KEY))

    def test_payload_cannot_choose_another_account(self):
        secret, other = self.login(10), self.login(20)
        self.assertEqual(self.request("preferences", "POST", {"user_id": "20", "expected_user_id": "10", "email": "x@example.com",
            "delivery_enabled": True}, secret)[0], 200)
        self.assertEqual(self.request(secret=secret)[1]["preferences"]["email"], "x@example.com")
        self.assertEqual(self.request(secret=other)[1]["preferences"]["email"], "")
        with patch.object(accounts, "verified_repository", return_value="owner/repo"):
            self.assertEqual(self.request("subscriptions", "POST", {"repo": "owner/repo", "user_id": "20", "expected_user_id": "10"}, secret)[0], 201)
        self.assertEqual(self.request("subscriptions", "DELETE", {"repo": "OWNER/REPO", "expected_user_id": "20"}, other)[1]["removed"], False)
        self.assertEqual(self.request(secret=secret)[1]["subscriptions"], ["owner/repo"])

    def test_stale_tab_cannot_write_when_another_tab_switches_the_session_account(self):
        first, current = self.login(10), self.login(20)
        accounts.save_preferences("10", "a@example.com", True)
        accounts.save_preferences("20", "b@example.com", True)
        self.db("HSET", accounts.subscriptions_key("20"), "owner/b", "Owner/B")
        for action, method, payload in (
            ("preferences", "POST", {"email": "a-draft@example.com", "delivery_enabled": True}),
            ("subscriptions", "POST", {"repo": "Owner/A"}),
            ("subscriptions", "DELETE", {"repo": "Owner/B"}),
        ):
            with self.subTest(action=action, method=method), patch.object(accounts, "verified_repository") as github:
                status, body, _ = self.request(action, method, {**payload, "expected_user_id": "10"}, current)
                self.assertEqual(status, 409)
                self.assertEqual(body["code"], "account_changed")
                github.assert_not_called()
        self.assertEqual(accounts.preferences("10")["email"], "a@example.com")
        self.assertEqual(accounts.preferences("20")["email"], "b@example.com")
        self.assertEqual(accounts.subscriptions("20"), ["Owner/B"])
        self.assertEqual(self.request("preferences", "POST", {"email": "a-draft@example.com", "delivery_enabled": True}, current)[0], 409)
        self.assertEqual(self.request("logout", "POST", secret=current)[0], 200)
        self.assertFalse(accounts.session_snapshot(current)["authenticated"])
        self.assertTrue(accounts.session_snapshot(first)["authenticated"])

    def test_existing_snapshot_has_no_new_collection_notification(self):
        session = self.login(10)
        self.db.hashes[accounts.subscriptions_key("10")] = {"owner/repo": "owner/repo"}
        self.db.values[accounts.community.SNAPSHOT_KEY] = json.dumps({
            "collected_repos": ["owner/repo"], "collected_at": "previous-batch"})
        row = self.request("collection", secret=session)[1]["jobs"][0]
        self.assertEqual(row["stage"], "done")
        self.assertEqual(row["attempt"], 0)
        self.assertIsNone(row["completion_id"])
        self.assertFalse(row["acknowledged"])
        payload = {"repo": "owner/repo", "completion_id": "legacy-snapshot", "expected_user_id": "10"}
        self.assertEqual(self.request("collection_seen", "POST", payload, session)[0], 400)

    def test_collection_acknowledgement_is_durable_user_scoped_and_completion_specific(self):
        first, second = self.login(10, "first"), self.login(20, "second")
        for user_id in ("10", "20"):
            self.db.hashes[accounts.subscriptions_key(user_id)] = {"owner/repo": "owner/repo"}
        job = {"repo": "owner/repo", "stage": "done", "attempt": 1, "updated_at": "completed-once"}
        self.db.hashes[collection.JOBS_KEY] = {"owner/repo": json.dumps(job)}
        row = self.request("collection", secret=first)[1]["jobs"][0]
        self.assertFalse(row["acknowledged"])
        payload = {"repo": "Owner/Repo", "completion_id": row["completion_id"], "expected_user_id": "10"}
        self.assertEqual(self.request("collection_seen", "POST", payload)[0], 401)
        self.assertEqual(self.request("collection_seen", "POST", payload, first, origin="https://other.example")[0], 403)
        self.assertEqual(self.request("collection_seen", "POST", {**payload, "expected_user_id": "20"}, first)[0], 409)
        self.assertEqual(self.request("collection_seen", "POST", {**payload, "repo": "other/repo"}, first)[0], 400)
        self.assertEqual(self.request("collection_seen", "POST", {**payload, "completion_id": "f" * 64}, first)[0], 400)
        with patch.object(accounts, "acknowledge_collection", side_effect=OSError):
            self.assertEqual(self.request("collection_seen", "POST", payload, first)[0], 503)
        self.assertFalse(self.request("collection", secret=first)[1]["jobs"][0]["acknowledged"])
        for _ in range(2):
            status, saved, _ = self.request("collection_seen", "POST", payload, first)
            self.assertEqual(status, 200)
            self.assertTrue(saved["acknowledged"])
        self.assertTrue(self.request("collection", secret=first)[1]["jobs"][0]["acknowledged"])
        self.assertFalse(self.request("collection", secret=second)[1]["jobs"][0]["acknowledged"])
        new_session = self.login(10, "first")
        self.assertTrue(self.request("collection", secret=new_session)[1]["jobs"][0]["acknowledged"])
        job["updated_at"] = "new-completion"
        self.db.hashes[collection.JOBS_KEY]["owner/repo"] = json.dumps(job)
        current = self.request("collection", secret=new_session)[1]["jobs"][0]
        self.assertNotEqual(current["completion_id"], payload["completion_id"])
        self.assertFalse(current["acknowledged"])
        self.assertEqual(self.request("collection_seen", "POST", payload, new_session)[0], 400)
        job["stage"] = "grading"
        self.db.hashes[collection.JOBS_KEY]["owner/repo"] = json.dumps(job)
        self.assertEqual(self.request("collection_seen", "POST", {**payload, "completion_id": current["completion_id"]}, new_session)[0], 400)

    def test_cookie_settings_callback_failure_and_safe_service_errors(self):
        status, _, headers = self.request("start")
        self.assertEqual(status, 302)
        state_cookie = dict(headers)["Set-Cookie"]
        for attribute in ("__Host-", "Path=/", "Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(attribute, state_cookie)
        cookie = state_cookie.split(";", 1)[0]
        state = cookie.split("=", 1)[1]
        with patch.object(accounts, "github_json", side_effect=[{"access_token": "test-only-ephemeral-value"},
                {"id": 42, "login": "octocat"}]):
            status, _, headers = self.request("callback", extra_query="&state=" + state + "&code=code", cookie=cookie)
        self.assertEqual(status, 302)
        self.assertEqual(dict(headers)["Location"], accounts.PUBLIC_ORIGIN + "/#/topics")
        self.assertEqual(len([v for k, v in headers if k == "Set-Cookie"]), 2)
        status, _, headers = self.request("callback", extra_query="&state=bad&code=private-code")
        self.assertEqual(dict(headers)["Location"], accounts.PUBLIC_ORIGIN + "/?auth=failed")
        self.assertNotIn("private-code", str(headers))
        with patch.object(accounts, "session_snapshot", side_effect=RuntimeError("internal-secret-detail")):
            status, body, headers = self.request()
            self.assertEqual(status, 503)
            self.assertNotIn("internal-secret-detail", str(body))
            self.assertEqual(dict(headers)["Cache-Control"], "no-store")

    def test_bad_json_is_400_and_invalid_input_preserves_preferences(self):
        secret = self.login()
        accounts.save_preferences("10", "saved@example.com", True)
        for raw in (b"{", b"[]", b"\xff", b"{}" * 1500):
            self.assertEqual(self.request("preferences", "POST", secret=secret, raw=raw)[0], 400)
        self.assertEqual(accounts.preferences("10")["email"], "saved@example.com")
        status, body, headers = self.request("logout", "POST", secret=secret)
        self.assertEqual(body, {"authenticated": False})
        self.assertIn("Max-Age=0", dict(headers)["Set-Cookie"])
        self.assertFalse(self.request(secret=secret)[1]["authenticated"])


if __name__ == "__main__":
    unittest.main()
