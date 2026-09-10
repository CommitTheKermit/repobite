"""로컬 HTTP 경계와 실제 작업 흐름 검사. 외부 네트워크 호출 없음."""

import json
from pathlib import Path
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import MagicMock, patch

import radar
import web
from test_radar import GOOD, ISSUE


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        issue = radar.normalize_issue("a/b", ISSUE)
        (root / "issues.jsonl").write_text(json.dumps(issue) + "\n")
        (root / "grades.jsonl").write_text(json.dumps({**issue, "grade": GOOD}) + "\n")
        (root / "repos.txt").write_text("a/b\n")
        server = web.make_server(0, root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def request(path, data=None, headers=None):
            actual = {"Origin": origin, "Content-Type": "application/json", "X-Radar-Request": "1"}
            actual.update(headers or {})
            body = json.dumps(data).encode() if data is not None else None
            req = Request(origin + path, data=body, headers=actual)
            try:
                with urlopen(req, timeout=5) as response:
                    return response.status, response.read()
            except HTTPError as error:
                return error.code, error.read()

        def state():
            code, body = request("/api/state")
            assert code == 200
            return json.loads(body)

        def wait_done():
            deadline = time.monotonic() + 5
            while state()["busy"]:
                assert time.monotonic() < deadline, "작업이 종료되지 않았습니다"
                time.sleep(.01)

        def fake_process(command, **kwargs):
            assert command[0] == web.sys.executable
            assert not kwargs.get("shell")
            output = Path(command[command.index("--output") + 1])
            if command[2] == "collect":
                result = {**issue, "number": 2, "title": "<script>untrusted</script>"}
            else:
                source = Path(command[command.index("--input") + 1])
                result = {**radar.read_jsonl(source)[0], "grade": GOOD, "model": "gpt-5.6-luna"}
            output.write_text(json.dumps(result) + "\n")
            process = MagicMock()
            process.__enter__.return_value = process
            process.stderr = iter(["작업 완료\n"])
            process.wait.return_value = 0
            return process

        try:
            assert request("/")[0] == 200
            assert state()["summary"]["target"] == 1
            assert state()["max_repos"] == 30
            assert state()["default_repos"] == "a/b\n"
            assert (state()["grade_count"], state()["deferred_count"]) == (1, 0)
            assert (state()["grade_limit"], state()["repo_grade_limit"]) == (100, 20)
            original_issues = (root / "issues.jsonl").read_bytes()
            large = [{**issue, "repo": f"owner/repo{repo}", "number": n}
                     for repo in range(6) for n in range(1, 31)]
            (root / "issues.jsonl").write_text("".join(json.dumps(row) + "\n" for row in large))
            assert (state()["count"], state()["grade_count"], state()["deferred_count"]) == (180, 100, 80)
            (root / "issues.jsonl").write_bytes(original_issues)
            assert request("/.env")[0] == request("/../radar.py")[0] == 404
            assert request("/api/state", headers={"Host": "attacker.example"})[0] == 403
            for headers in ({"Origin": "https://attacker.example"}, {"Origin": ""},
                            {"Content-Type": "text/plain"}, {"X-Radar-Request": ""}):
                assert request("/api/run", {"action": "grade"}, headers)[0] == 403
            for payload in ([], {"action": "exec"}, {"action": "collect", "repos": "../../secret", "since": "7d"},
                            {"action": "collect", "repos": "a/b", "since": "all"}):
                assert request("/api/run", payload)[0] == 400
            with patch.object(web.Application, "run"):
                assert request("/api/run", {"action": "grade"})[0] == 202
                assert request("/api/run", {"action": "grade"})[0] == 409
            server.app.busy = False
            defaults = (radar.ROOT / "repos.txt").read_text()
            names = [name for line in defaults.splitlines() if (name := line.split("#", 1)[0].strip())]
            assert len(names) == len(set(name.lower() for name in names)) == 30
            assert "nousresearch/hermes-agent" not in {name.lower() for name in names}
            with patch.object(web.Application, "run") as worker:
                assert request("/api/run", {"action": "collect", "repos": defaults, "since": "7d"})[0] == 202
                deadline = time.monotonic() + 5
                while not worker.called:
                    assert time.monotonic() < deadline
                    time.sleep(.01)
                assert len(worker.call_args.args[1].splitlines()) == 30
            server.app.busy = False
            assert request("/api/run", {"action": "collect", "repos": defaults + "\nowner/extra", "since": "7d"})[0] == 400
            assert not state()["busy"]
            original = (root / "grades.jsonl").read_bytes()
            with patch.object(web.subprocess, "Popen", side_effect=fake_process):
                assert request("/api/run", {"action": "collect", "repos": "a/b", "since": "7d"})[0] == 202
                wait_done()
                result = state()
                assert result["count"] == 1 and result["summary"]["valid"] == 0
                assert result["items"][0]["number"] == 2
                assert request("/api/run", {"action": "grade"})[0] == 202
                wait_done()
                assert state()["summary"]["target"] == 1
            assert (root / "grades.jsonl").read_bytes() == original
            assert web.Application(root).snapshot()["items"] == state()["items"]
            (root / "repos.txt").write_text("new/default\n")
            assert state()["repos"] == "a/b\n"
            assert state()["default_repos"] == "new/default\n"
            pointer = (server.app.data / "current").resolve()
            with patch.object(web.subprocess, "Popen", side_effect=FileNotFoundError):
                assert request("/api/run", {"action": "collect", "repos": "a/b", "since": "7d"})[0] == 202
                wait_done()
            assert (server.app.data / "current").resolve() == pointer
            assert state()["summary"]["target"] == 1
            def partial_failure(command, **kwargs):
                process = fake_process(command, **kwargs)
                process.wait.return_value = 1
                return process
            with patch.object(web.subprocess, "Popen", side_effect=partial_failure):
                assert request("/api/run", {"action": "collect", "repos": "a/b", "since": "7d"})[0] == 202
                wait_done()
            assert (server.app.data / "current").resolve() == pointer
            server.app.process = MagicMock(pid=12345)
            server.app.process.poll.return_value = None
            with patch.object(web.os, "killpg") as kill:
                server.app.stop()
                kill.assert_called_once_with(12345, web.signal.SIGTERM)
            assert request("/api/run", {"action": "grade"})[0] == 409
            print("통과: HTTP 실행·기본 30개·31개 거절·목록 복원·입력 검증·교차 출처 차단·중복 실행 방지·수집/판정 연결·실패 보존·재시작 복원")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
