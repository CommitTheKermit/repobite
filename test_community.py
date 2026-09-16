"""실행: python3 test_community.py. 실제 DB와 GitHub를 변경하지 않는다."""

from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from api.repos import handler
import community
import community_batch
import radar
from test_radar import ISSUE, GOOD, rejects


def main():
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
              patch.object(radar, "gh_json", return_value={"private": True}),
              patch.object(radar, "batch") as batch, patch.object(community, "redis") as publish):
            rejects(community_batch.run, root)
            batch.assert_not_called()
            publish.assert_not_called()
    print("통과: 등록 검증·중복·요청 제한·HTTP 경계·목록 병합·정기 반영·실패 시 이전 공개 결과 보존")


if __name__ == "__main__":
    main()
