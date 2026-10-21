"""실행: python3 test_community.py. 실제 DB와 GitHub를 변경하지 않는다."""

from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from api.repos import handler
import community
import community_batch
import radar
from public_feed import public_items
from test_radar import ISSUE, GOOD, rejects


def test_snapshot_recovery():
    """실패 후 공개 재조회, 중간 등록, 빈 결과와 재실행의 계약을 검사한다."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("a/b\n", encoding="utf-8")
        submitted = [{"repo": "Owner/Repo", "description": "소개", "added_at": "first"}]
        previous = {"items": [{"title": "이전 결과"}], "collected_repos": ["a/b"],
                    "collected_at": "previous"}
        saved = json.dumps(previous)
        fail_publish = False

        def redis(command, key, *values):
            nonlocal saved
            if (command, key) == ("HVALS", community.REPOS_KEY):
                return [json.dumps(row) for row in submitted]
            if (command, key) == ("GET", community.SNAPSHOT_KEY):
                return saved
            assert (command, key) == ("SET", community.SNAPSHOT_KEY)
            if fail_publish:
                raise RuntimeError("공개 결과 저장 실패")
            saved = values[0]
            return "OK"

        issue = radar.normalize_issue("Owner/Repo", ISSUE)
        graded = {**issue, "grade": GOOD, "criteria_version": radar.CRITERIA_VERSION}
        late = {"repo": "Late/Repo", "description": "중간 등록", "added_at": "later"}

        def batch(args):
            submitted.append(late)
            args.issues.write_text(json.dumps(issue) + "\n", encoding="utf-8")
            args.grades.write_text(json.dumps(graded) + "\n", encoding="utf-8")
            return 0

        with (patch.object(community, "redis", side_effect=redis),
              patch.object(radar, "gh_json", return_value={"private": False}),
              patch.object(radar, "batch", side_effect=batch), redirect_stdout(io.StringIO())):
            fail_publish = True
            try:
                community_batch.run(root)
            except RuntimeError:
                pass
            else:
                raise AssertionError("공개 저장 실패를 성공으로 처리했습니다")
            assert community.feed()["snapshot"] == previous
            # 실패 중 들어온 등록은 보존한다. 다음 실행 시작 이후의 등록만 대기다.
            submitted[:] = submitted[:1]
            fail_publish = False
            assert community_batch.run(root) == 0
            feed = community.feed()
            assert len(feed["repos"]) == 2
            assert feed["snapshot"]["collected_repos"] == ["a/b", "owner/repo"]
            assert "late/repo" not in feed["snapshot"]["collected_repos"]
            assert feed["snapshot"]["items"][0]["criteria_version"] == 2
            assert "body" not in feed["snapshot"]["items"][0]

            def empty_batch(args):
                args.issues.write_text("", encoding="utf-8")
                args.grades.write_text("", encoding="utf-8")
                return 0

            with patch.object(radar, "batch", side_effect=empty_batch):
                assert community_batch.run(root) == 0
                assert community.feed()["snapshot"]["items"] == []
                assert set(community.feed()["snapshot"]["collected_repos"]) == {
                    "a/b", "owner/repo", "late/repo"}
                assert community_batch.run(root) == 0
                assert len(community.feed()["repos"]) == 2
        assert public_items([issue], [{**issue, "grade": GOOD}])[0]["criteria_version"] is None
        assert public_items([issue], [{**graded, "body": "바뀐 본문"}])[0]["grade"] is None


def main():
    test_unavailable_repositories_do_not_block_public_collection()
    test_repository_check_failure_preserves_snapshot()
    test_snapshot_recovery()
    test_personal_subscriptions_join_collection()
    assert community.normalize_repo(" https://github.com/Owner/Repo/ ") == "Owner/Repo"
    for value in (None, [], "https://evil.test/a/b", "a/b?x=1", "a/..", "a/b/issues/1",
                  "https://github.com/a/b#x", "a/реро", "-a/b", "a/b\nInjected"):
        rejects(community.normalize_repo, value)
    row = {"repo": "Owner/Repo", "description": "소개", "added_at": "2026-09-16T00:00:00+00:00"}
    info = {"full_name": row["repo"], "description": row["description"],
            "private": False, "has_issues": True, "archived": False}
    with patch.object(community, "redis", return_value=json.dumps(row)), patch.object(community, "urlopen") as github:
        assert not community.register("owner/repo")["created"]
        github.assert_not_called()
    with (patch.object(community, "redis", side_effect=[None, 1, 1]) as db,
          patch.object(community, "urlopen", return_value=io.BytesIO(json.dumps(info).encode()))):
        assert community.register("owner/repo")["created"]
        assert db.call_args.args[-2] == "owner/repo"
    for changes in ({"private": True}, {"has_issues": False}, {"archived": True}):
        with (patch.object(community, "redis", side_effect=[None, 1]) as db,
              patch.object(community, "urlopen", return_value=io.BytesIO(json.dumps({**info, **changes}).encode()))):
            rejects(community.register, "owner/repo")
            assert db.call_count == 2
    with (patch.object(community, "redis", side_effect=[None, 1, 0, json.dumps(row)]),
          patch.object(community, "urlopen", return_value=io.BytesIO(json.dumps(info).encode()))):
        assert community.register("owner/repo") == {"repo": row, "created": False}
    with (patch.object(community, "redis", side_effect=[None, 31]),
          patch.object(community, "urlopen") as github):
        try:
            community.register("owner/repo")
        except OverflowError:
            pass
        else:
            raise AssertionError("요청 제한 누락")
        github.assert_not_called()
    with patch.dict(community.os.environ, {}, clear=True), patch.object(community, "urlopen") as request:
        try:
            community.redis("GET", "key")
        except RuntimeError:
            pass
        else:
            raise AssertionError("DB 미설정을 숨겼습니다")
        request.assert_not_called()

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(data=None, origin="https://repobite.vercel.app"):
        req = Request(f"http://127.0.0.1:{server.server_port}/api/repos",
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={"Origin": origin, "Content-Type": "application/json"})
        try:
            with urlopen(req) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    try:
        with patch.object(community, "feed", return_value={"repos": [row], "snapshot": None}):
            assert request()[1]["repos"] == [row]
        with patch.object(community, "register", return_value={"repo": row, "created": True}) as register:
            assert request({"repo": "owner/repo"})[0] == 201
            register.assert_called_once_with("owner/repo")
            assert request({"repo": "owner/repo"}, origin="https://evil.test")[0] == 403
            assert register.call_count == 1
            assert request([])[0] == request({"repo": "a" * 1100})[0] == 400
        for exception, code in ((ValueError("bad"), 400), (OverflowError("wait"), 429),
                                (RuntimeError("internal detail"), 503)):
            with patch.object(community, "register", side_effect=exception):
                status, data = request({"repo": "a/b"})
                assert status == code and "internal detail" not in str(data)
        with patch.object(community, "feed", side_effect=RuntimeError()):
            assert request()[0] == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("# defaults\na/b\nA/B\n")
        issue = radar.normalize_issue("Owner/Repo", ISSUE)

        def batch(args):
            assert args.repos.read_text().splitlines() == ["a/b", "Owner/Repo"]
            assert args.since == "24h"
            args.issues.write_text(json.dumps(issue) + "\n")
            args.grades.write_text(json.dumps({**issue, "grade": GOOD}) + "\n")
            return 0

        with (patch.object(community, "registrations", return_value=[row]),
              patch.object(radar, "gh_json", return_value={"private": False}),
              patch.object(radar, "batch", side_effect=batch),
              patch.object(community, "redis") as publish, redirect_stdout(io.StringIO())):
            assert community_batch.run(root) == 0
            command, key, body = publish.call_args.args
            assert (command, key) == ("SET", community.SNAPSHOT_KEY)
            snapshot = json.loads(body)
            assert snapshot["collected_repos"] == ["a/b", "owner/repo"]
            assert snapshot["items"][0]["grade"] == GOOD
            assert "body" not in snapshot["items"][0]
            # 이슈가 없는 레포도 수집 완료로 구분할 수 있다.
            assert "a/b" in snapshot["collected_repos"]
            assert (root / "repos.txt").read_text() == "# defaults\na/b\nA/B\n"
        with (patch.object(community, "registrations", return_value=[row]),
              patch.object(radar, "gh_json", return_value={"private": False}),
              patch.object(radar, "batch", return_value=1), patch.object(community, "redis") as publish):
            assert community_batch.run(root) == 1
            publish.assert_not_called()
        with (patch.object(community, "registrations", return_value=[row]),
              patch.object(radar, "gh_json", return_value={}),
              patch.object(radar, "batch") as batch, patch.object(community, "redis") as publish):
            rejects(community_batch.run, root)
            batch.assert_not_called()
            publish.assert_not_called()
    print("통과: 등록 검증·중복·요청 제한·HTTP 경계·목록 병합·정기 반영·실패 시 이전 공개 결과 보존")


def test_unavailable_repositories_do_not_block_public_collection():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = "Base/Good\nBase/Private\n"
        (root / "repos.txt").write_text(base, encoding="utf-8")
        registrations = [{"repo": "Gone/Repo"}]
        private = {"base/private", "personal/private"}
        gone = {"gone/repo", "trend/gone"}
        checked = []

        def github(endpoint, *, include_status):
            assert include_status is True
            name = endpoint.removeprefix("repos/").lower()
            checked.append(name)
            if name in gone:
                raise radar.GitHubAPIError(404)
            return {"private": name in private}

        def batch(args):
            expected = ["Base/Good", "Trend/Good"] if private else [
                "Base/Good", "Base/Private", "Personal/Private", "Trend/Good"]
            assert args.repos.read_text(encoding="utf-8").splitlines() == expected
            # 이전 캐시 행이 남아도 이번 실행에서 제외한 저장소를 공개하지 않는다.
            issues = [radar.normalize_issue(name, ISSUE) for name in ["Base/Good", "Base/Private", "Gone/Repo"]]
            args.issues.write_text("\n".join(json.dumps(row) for row in issues), encoding="utf-8")
            args.grades.write_text("", encoding="utf-8")
            return 0

        with (patch.object(community, "registrations", return_value=registrations),
              patch.object(community_batch.accounts, "subscription_repositories", return_value=["Personal/Private"]),
              patch.object(community_batch, "discovered_repositories", return_value=["Trend/Good", "Trend/Gone"]),
              patch.object(radar, "gh_json", side_effect=github),
              patch.object(radar, "batch", side_effect=batch) as collect,
              patch.object(community, "redis") as publish, redirect_stdout(io.StringIO())):
            assert community_batch.run(root) == 0
            snapshot = json.loads(publish.call_args.args[-1])
            assert snapshot["collected_repos"] == ["base/good", "trend/good"]
            assert snapshot["discovered_repos"] == ["Trend/Good"]
            assert [row["repo"] for row in snapshot["items"]] == ["Base/Good"]
            assert registrations == [{"repo": "Gone/Repo"}]
            assert (root / "repos.txt").read_text(encoding="utf-8") == base
            private.clear()
            assert community_batch.run(root) == 0
            assert "base/private" in json.loads(publish.call_args.args[-1])["collected_repos"]
            assert checked.count("base/private") == 2
            # 전부 제외된 실행은 이전 파일을 읽거나 판정하지 않고 빈 공개 결과를 만든다.
            collect.reset_mock()
            with patch.object(radar, "gh_json", return_value={"private": True}):
                assert community_batch.run(root) == 0
            collect.assert_not_called()
            snapshot = json.loads(publish.call_args.args[-1])
            assert snapshot["items"] == snapshot["collected_repos"] == snapshot["discovered_repos"] == []


def test_repository_check_failure_preserves_snapshot():
    failures = [radar.GitHubAPIError(code) for code in (401, 403, 429, 500, 503)]
    failures += [RuntimeError("HTTP 404 is only text"), subprocess.TimeoutExpired("gh", 180),
                 ValueError("broken JSON")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("a/public\nb/unknown\n", encoding="utf-8")
        for failure in failures:
            previous = json.dumps({"items": [{"title": "이전 결과"}]})
            saved = previous

            def publish(*args):
                nonlocal saved
                saved = args[-1]

            with (patch.object(community, "registrations", return_value=[]),
                  patch.object(radar, "gh_json", side_effect=[{"private": False}, failure]),
                  patch.object(radar, "batch") as batch,
                  patch.object(community, "redis", side_effect=publish)):
                try:
                    community_batch.run(root)
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    pass
                else:
                    raise AssertionError("GitHub 장애를 저장소 제외로 숨겼습니다")
                batch.assert_not_called()
                assert saved == previous


def test_personal_subscriptions_join_collection():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("a/b\n", encoding="utf-8")

        def batch(args):
            assert args.repos.read_text(encoding="utf-8").splitlines() == ['a/b', 'Personal/Repo']
            args.issues.write_text('', encoding='utf-8')
            args.grades.write_text('', encoding='utf-8')
            return 0

        with (patch.object(community, 'registrations', return_value=[]),
              patch.object(community_batch.accounts, 'subscription_repositories',
                           return_value=['A/B', 'Personal/Repo']),
              patch.object(radar, 'gh_json', return_value={'private': False}),
              patch.object(radar, 'batch', side_effect=batch),
              patch.object(community, 'redis') as publish, redirect_stdout(io.StringIO())):
            assert community_batch.run(root) == 0
            snapshot = json.loads(publish.call_args.args[-1])
            assert snapshot['collected_repos'] == ['a/b', 'personal/repo']
            assert set(snapshot) == {'items', 'collected_repos', 'collected_at', 'discovered_repos'}


def test_discovery_contract():
    trend = [{"repo": f"trend{n}/repo", "period": "weekly"} for n in range(14)]
    famous = [{"repo": f"famous{n}/repo"} for n in range(15)]
    names = [row["repo"] for row in trend + famous]
    result = {"method": "github_trending_and_cumulative_stars", "requested_total": 30,
              "quota": {"trend": 15, "famous": 15}, "actual_total": 29, "repos": names,
              "trend": {"items": trend, "status": "partial", "shortfall": 1},
              "famous": {"items": famous, "status": "complete", "shortfall": 0}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("base/repo\n", encoding="utf-8")
        with patch.object(community_batch.repository_discovery, "run_github_trending", return_value=result) as discover:
            assert community_batch.discovered_repositories(root) == names
            assert discover.call_args.kwargs["allow_partial_trend"] is True
            assert discover.call_args.kwargs["period"] == "weekly"
        for bad in ({**result, "actual_total": 30}, {**result, "repos": names + [names[0]]},
                    {**result, "trend": {**result["trend"], "status": "complete"}}):
            with patch.object(community_batch.repository_discovery, "run_github_trending", return_value=bad):
                rejects(community_batch.discovered_repositories, root)
        def batch(args):
            assert args.repos.read_text(encoding="utf-8").splitlines() == ["base/repo", "manual/repo", "personal/repo"] + names
            args.issues.write_text("", encoding="utf-8")
            args.grades.write_text("", encoding="utf-8")
            return 0
        with (patch.object(community, "registrations", return_value=[{"repo": "manual/repo"}]),
              patch.object(community_batch.accounts, "subscription_repositories", return_value=["personal/repo", "BASE/REPO"]),
              patch.object(community_batch.repository_discovery, "run_github_trending", return_value=result),
              patch.object(radar, "gh_json", return_value={"private": False}),
              patch.object(radar, "batch", side_effect=batch) as grading,
              patch.object(community, "redis") as publish, redirect_stdout(io.StringIO())):
            assert community_batch.run(root) == 0
            assert (root / "repos.txt").read_text(encoding="utf-8") == "base/repo\n"
            snapshot = json.loads(publish.call_args.args[-1])
            assert snapshot["collected_repos"] == ["base/repo", "manual/repo", "personal/repo"] + names
            assert snapshot["discovered_repos"] == names
            publish.reset_mock(); grading.reset_mock()
            with patch.object(community_batch.repository_discovery, "run_github_trending", side_effect=RuntimeError("API unavailable")):
                try:
                    community_batch.run(root)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("발굴 API 실패를 성공으로 처리했습니다")
            publish.assert_not_called()
            grading.assert_not_called()


if __name__ == "__main__":
    test_discovery_contract()
    with (patch.object(community_batch.accounts, "subscription_repositories", return_value=[]),
          patch.object(community_batch, "discovered_repositories", return_value=[])):
        main()
