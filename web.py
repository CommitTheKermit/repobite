"""Mac 로컬 웹: python3 web.py (http://127.0.0.1:8765)."""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import uuid

import radar

MAX_REPOS = 30


class Application:
    def __init__(self, root=radar.ROOT):
        self.root = Path(root)
        self.data = self.root / ".radar-web"
        self.lock = threading.Lock()
        self.busy = False
        self.stopping = False
        self.process = None
        self.message = "수집할 레포를 선택하거나 기존 판정 결과를 확인하세요."
        self.logs = deque(maxlen=80)

    def paths(self):
        pointer = self.data / "current"
        directory = pointer.resolve() if pointer.is_symlink() else self.root
        return directory / "issues.jsonl", directory / "grades.jsonl"

    def snapshot(self):
        with self.lock:
            source, output = self.paths()
            issues = radar.unique_issues(radar.read_jsonl(source)) if source.exists() else []
            rows = radar.read_jsonl(output) if output.exists() else []
            originals = {radar.issue_key(row): row for row in issues}
            # CLI 파일을 직접 바꾼 경우에도 이전 수집분의 판정이 섞이지 않게 한다.
            rows = [row for row in rows if radar.issue_key(row) in originals and all(
                row.get(key) == originals[radar.issue_key(row)].get(key)
                for key in ("title", "body"))]
            sample_path = self.root / "fixtures/sample30.json"
            samples = json.loads(sample_path.read_text()) if sample_path.exists() else []
            stats = radar.aggregate(rows, samples)
            grade_count = len(radar.select_for_grading(issues))
            summary = {key: stats[key] for key in ("valid", "failed", "excluded", "target", "eligible")}
            summary["cross"] = [[stats["cross"][level, state] for state in radar.READINESS]
                                for level in (1, 2, 3)]
            grades = {radar.issue_key(row): row for row in rows}
            items = []
            for issue in issues:
                row = grades.get(radar.issue_key(issue), {})
                items.append({"repo": issue["repo"], "number": issue["number"],
                              "title": issue["title"], "grade": row.get("grade"),
                              "error": row.get("error"), "model": row.get("model")})
            repos = source.parent / "repos.txt"
            if not repos.exists():
                repos = self.root / "repos.txt"
            return {"busy": self.busy, "message": self.message, "logs": list(self.logs),
                    "repos": repos.read_text() if repos.exists() else "",
                    "default_repos": (self.root / "repos.txt").read_text(), "max_repos": MAX_REPOS,
                    "source": "웹 작업 결과" if source.parent != self.root else "기존 CLI 데이터",
                    "count": len(issues), "items": items, "summary": summary,
                    "grade_count": grade_count, "deferred_count": len(issues) - grade_count,
                    "grade_limit": radar.GRADE_LIMIT, "repo_grade_limit": radar.REPO_GRADE_LIMIT,
                    "report": radar.render_report(stats)}

    def start(self, payload):
        if not isinstance(payload, dict) or payload.get("action") not in ("collect", "sample", "grade"):
            raise ValueError("수집 또는 판정 작업을 선택하세요.")
        action = payload["action"]
        repos, since = "", "7d"
        if action == "collect":
            text = payload.get("repos")
            if not isinstance(text, str):
                raise ValueError("레포 목록을 입력하세요.")
            names = list(dict.fromkeys(line.split("#", 1)[0].strip() for line in text.splitlines()))
            names = [name for name in names if name]
            if not 1 <= len(names) <= MAX_REPOS:
                raise ValueError(f"레포를 1개 이상 {MAX_REPOS}개 이하로 입력하세요.")
            for name in names:
                radar.issue_key({"repo": name, "number": 1})
            repos = "\n".join(names) + "\n"
            since = payload.get("since")
            if since not in ("1d", "3d", "7d", "14d"):
                raise ValueError("수집 기간을 선택하세요.")
        with self.lock:
            if self.busy or self.stopping:
                raise RuntimeError("실행 중인 작업이 끝난 뒤 다시 시도하세요.")
            source, _ = self.paths()
            if action == "grade" and (not source.exists() or not radar.read_jsonl(source)):
                raise ValueError("먼저 이슈를 수집하세요.")
            self.busy = True
            self.message = "판정 중입니다." if action == "grade" else "이슈를 수집하고 있습니다."
            self.logs.clear()
        threading.Thread(target=self.run, args=(action, repos, since), daemon=True).start()

    def run(self, action, repos, since):
        # ponytail: Mac 한 사용자당 작업 하나. 다중 사용자 서비스가 되면 작업 큐로 전환.
        try:
            self.data.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.data) as directory:
                work = Path(directory)
                command = [sys.executable, str(radar.ROOT / "radar.py")]
                if action == "grade":
                    source, _ = self.paths()
                    (work / "issues.jsonl").write_bytes(source.read_bytes())
                    saved_repos = source.parent / "repos.txt"
                    if saved_repos.exists():
                        (work / "repos.txt").write_bytes(saved_repos.read_bytes())
                    command += ["grade", "--input", str(work / "issues.jsonl"),
                                "--output", str(work / "grades.jsonl"), "--model", "gpt-5.6-luna"]
                else:
                    command += ["collect", "--output", str(work / "issues.jsonl")]
                    if action == "sample":
                        command += ["--sample", str(self.root / "fixtures/sample30.json")]
                    else:
                        (work / "repos.txt").write_text(repos)
                        command += ["--repos", str(work / "repos.txt"), "--since", since]
                with subprocess.Popen(command, cwd=work, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, text=True, start_new_session=True) as process:
                    with self.lock:
                        self.process = process
                        if self.stopping:
                            os.killpg(process.pid, signal.SIGTERM)
                    for line in process.stderr:
                        with self.lock:
                            self.logs.append(line.rstrip()[:500])
                    code = process.wait()
                with self.lock:
                    if action != "grade" and code:
                        self.message = "수집에 실패했습니다. 이전 결과를 유지합니다. 실행 내역과 gh 로그인을 확인하세요."
                    elif action == "grade" and not (work / "grades.jsonl").exists():
                        self.message = "판정을 시작하지 못했습니다. 이전 결과를 유지합니다. 실행 내역을 확인하세요."
                    else:
                        saved = self.data / f"run-{uuid.uuid4().hex}"
                        work.rename(saved)
                        pointer = self.data / "current.next"
                        pointer.unlink(missing_ok=True)
                        pointer.symlink_to(saved.name, target_is_directory=True)
                        pointer.replace(self.data / "current")
                        self.message = ("일부 판정이 실패했습니다. 결과의 실패 항목과 Codex 로그인을 확인하세요."
                                        if code else "판정이 완료됐습니다." if action == "grade"
                                        else "수집이 완료됐습니다. 건수를 확인하고 판정을 시작하세요.")
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                self.message = "작업을 실행하지 못했습니다. gh·codex 설치와 저장 폴더 권한을 확인하세요."
        finally:
            with self.lock:
                self.busy = False
                self.process = None

    def stop(self):
        with self.lock:
            self.stopping = True
            if self.process is not None and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def reply(self, status, content, kind="application/json; charset=utf-8"):
        body = json.dumps(content, ensure_ascii=False).encode() if isinstance(content, dict) else content
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def local_request(self, mutation=False):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host")
        valid = host in hosts
        if mutation:
            valid = valid and self.headers.get("Origin") == f"http://{host}"
            valid = valid and self.headers.get("Content-Type") == "application/json"
            valid = valid and self.headers.get("X-Radar-Request") == "1"
        if not valid:
            self.reply(403, {"error": "로컬 웹 화면에서 실행하세요."})
        return valid

    def do_GET(self):
        if not self.local_request():
            return
        if self.path == "/":
            self.reply(200, (radar.ROOT / "web.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            try:
                self.reply(200, self.server.app.snapshot())
            except (OSError, ValueError, KeyError, TypeError):
                self.reply(500, {"error": "결과 파일을 읽지 못했습니다. JSONL 파일 형식을 확인하세요."})
        else:
            self.reply(404, {"error": "페이지가 없습니다."})

    def do_POST(self):
        if not self.local_request(mutation=True):
            return
        if self.path != "/api/run":
            self.reply(404, {"error": "작업 경로가 없습니다."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                raise ValueError("입력 크기가 잘못되었습니다.")
            payload = json.loads(self.rfile.read(length))
            self.server.app.start(payload)
            self.reply(202, {"started": True})
        except (ValueError, TypeError, OSError):
            self.reply(400, {"error": f"입력을 확인하세요. owner/repo 형식으로 최대 {MAX_REPOS}개를 입력하고, 판정 전에는 수집하세요."})
        except RuntimeError as error:
            self.reply(409, {"error": str(error)})


def make_server(port=8765, root=radar.ROOT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = Application(root)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print(f"oss-radar: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.app.stop()
