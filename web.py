"""로컬 웹: python web.py (http://127.0.0.1:8765)."""

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
from urllib.parse import urlsplit

from api.account import handle_account
from api.contributions import handle_contributions
import community
import home_status
import radar
from public_feed import public_items

MAX_REPOS = 30

def stop_process(process):
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, timeout=15)
        if result.returncode and process.poll() is None:
            raise subprocess.SubprocessError("작업 프로세스를 종료하지 못했습니다")
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


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
        saved = self.data / "current.txt"
        if saved.exists():
            name = saved.read_text(encoding="utf-8")
            if not name.startswith("run-") or len(name) != 36 or any(
                    char not in "0123456789abcdef" for char in name[4:]):
                raise ValueError("저장된 작업 경로가 잘못되었습니다")
            directory = self.data / name
            return directory / "issues.jsonl", directory / "grades.jsonl"
        # 기존 Mac 심볼릭 링크는 다음 성공 실행 전까지 읽을 수 있다.
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
            samples = json.loads(sample_path.read_text(encoding="utf-8")) if sample_path.exists() else []
            stats = radar.aggregate(rows, samples)
            reusable = radar.reusable_grades(rows, issues, radar.MODEL)
            unresolved = [issue for issue in issues if radar.issue_key(issue) not in reusable]
            grade_count = len(radar.select_for_grading(unresolved))
            summary = {key: stats[key] for key in ("valid", "failed", "excluded", "target", "eligible")}
            summary["cross"] = [[stats["cross"][level, state] for state in radar.READINESS]
                                for level in (1, 2, 3)]
            items = public_items(issues, rows)
            repos = source.parent / "repos.txt"
            if not repos.exists():
                repos = self.root / "repos.txt"
            return {"busy": self.busy, "message": self.message, "logs": list(self.logs),
                    "repos": repos.read_text(encoding="utf-8") if repos.exists() else "",
                    "default_repos": (self.root / "repos.txt").read_text(encoding="utf-8"), "max_repos": MAX_REPOS,
                    "source": "웹 작업 결과" if source.parent != self.root else "기존 CLI 데이터",
                    "count": len(issues), "items": items, "summary": summary,
                    "grade_count": grade_count, "deferred_count": len(unresolved) - grade_count,
                    "unresolved_count": len(unresolved),
                    "grade_limit": radar.GRADE_LIMIT, "repo_grade_limit": radar.REPO_GRADE_LIMIT,
                    "report": radar.render_report(stats)}

    def start(self, payload):
        if not isinstance(payload, dict) or payload.get("action") not in ("collect", "sample", "grade", "grade_all"):
            raise ValueError("수집 또는 판정 작업을 선택하세요.")
        action = payload["action"]
        is_grading = action in ("grade", "grade_all")
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
            if is_grading and (not source.exists() or not radar.read_jsonl(source)):
                raise ValueError("먼저 이슈를 수집하세요.")
            self.busy = True
            self.message = ("전체 판정 중입니다." if action == "grade_all" else "판정 중입니다." if is_grading
                            else "이슈를 수집하고 있습니다.")
            self.logs.clear()
        threading.Thread(target=self.run, args=(action, repos, since), daemon=True).start()

    def run(self, action, repos, since):
        # ponytail: 로컬 작업 하나. 다중 사용자 서비스가 되면 작업 큐로 전환.
        is_grading = action in ("grade", "grade_all")
        try:
            self.data.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.data) as directory:
                work = Path(directory)
                command = [sys.executable, str(radar.ROOT / "radar.py")]
                if is_grading:
                    source, previous = self.paths()
                    (work / "issues.jsonl").write_bytes(source.read_bytes())
                    if previous.exists():
                        (work / "reuse.jsonl").write_bytes(previous.read_bytes())
                    saved_repos = source.parent / "repos.txt"
                    if saved_repos.exists():
                        (work / "repos.txt").write_bytes(saved_repos.read_bytes())
                    command += ["grade", "--input", str(work / "issues.jsonl"),
                                "--output", str(work / "grades.jsonl"), "--model", radar.MODEL]
                    if (work / "reuse.jsonl").exists():
                        command += ["--reuse", str(work / "reuse.jsonl")]
                    if action == "grade_all":
                        command.append("--all")
                else:
                    command += ["collect", "--output", str(work / "issues.jsonl")]
                    if action == "sample":
                        command += ["--sample", str(self.root / "fixtures/sample30.json")]
                    else:
                        (work / "repos.txt").write_text(repos, encoding="utf-8")
                        command += ["--repos", str(work / "repos.txt"), "--since", since]
                with subprocess.Popen(command, cwd=work, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                      start_new_session=os.name != "nt") as process:
                    with self.lock:
                        self.process = process
                        if self.stopping:
                            stop_process(process)
                    for line in process.stderr:
                        with self.lock:
                            self.logs.append(line.rstrip()[:500])
                    code = process.wait()
                with self.lock:
                    if not is_grading and code:
                        self.message = "수집에 실패했습니다. 이전 결과를 유지합니다. 실행 내역과 gh 로그인을 확인하세요."
                    elif is_grading and not (work / "grades.jsonl").exists():
                        self.message = "판정을 시작하지 못했습니다. 이전 결과를 유지합니다. 실행 내역을 확인하세요."
                    else:
                        saved = self.data / f"run-{uuid.uuid4().hex}"
                        work.rename(saved)
                        pointer = self.data / "current.txt.next"
                        pointer.unlink(missing_ok=True)
                        pointer.write_text(saved.name, encoding="utf-8")
                        pointer.replace(self.data / "current.txt")
                        self.message = ("일부 판정이 실패했습니다. 결과와 Vertex AI 인증을 확인하세요."
                                        if code else "판정이 완료됐습니다." if is_grading
                                        else "수집이 완료됐습니다. 건수를 확인하고 판정을 시작하세요.")
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                self.message = "작업을 실행하지 못했습니다. gh와 GCP 인증, 저장 폴더 권한을 확인하세요."
        finally:
            with self.lock:
                self.busy = False
                self.process = None

    def stop(self):
        with self.lock:
            self.stopping = True
            if self.process is not None and self.process.poll() is None:
                stop_process(self.process)


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
                         "style-src 'self' 'unsafe-inline'; img-src 'self' https://avatars.githubusercontent.com "
                         "https://opengraph.githubassets.com https://raw.githubusercontent.com data:; "
                         "connect-src 'self' https://api.github.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
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
        if urlsplit(self.path).path == "/api/account":
            handle_account(self)
        elif urlsplit(self.path).path == "/api/contributions":
            handle_contributions(self)
        elif self.path == "/":
            self.reply(200, (radar.ROOT / "web.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path in {"/account-ui.mjs", "/contribution-ui.mjs"}:
            self.reply(200, (radar.ROOT / self.path.lstrip("/")).read_bytes(), "text/javascript; charset=utf-8")
        elif self.path == "/api/repos":
            try:
                self.reply(200, community.feed())
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                self.reply(503, {"error": "공용 목록을 불러오지 못했습니다. 잠시 후 다시 시도하세요."})
        elif self.path in {"/api/state", "/data.json"}:
            try:
                self.reply(200, self.server.app.snapshot())
            except (OSError, ValueError, KeyError, TypeError):
                self.reply(500, {"error": "결과 파일을 읽지 못했습니다. JSONL 파일 형식을 확인하세요."})
        else:
            self.reply(404, {"error": "페이지가 없습니다."})

    def do_POST(self):
        if urlsplit(self.path).path == "/api/account":
            if self.local_request():
                handle_account(self)
            return
        if urlsplit(self.path).path == "/api/contributions":
            if self.local_request():
                handle_contributions(self)
            return
        if not self.local_request(mutation=True):
            return
        if self.path == "/api/repos":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("입력이 너무 깁니다.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("레포 주소를 입력하세요.")
                result = community.register(payload.get("repo"))
                self.reply(201 if result["created"] else 200, result)
            except ValueError:
                self.reply(400, {"error": "공개 GitHub 레포 주소와 이슈 기능 활성화 여부를 확인하세요."})
            except OverflowError as error:
                self.reply(429, {"error": str(error)})
            except (OSError, RuntimeError, KeyError, TypeError):
                self.reply(503, {"error": "등록하지 못했습니다. 잠시 후 다시 시도하세요."})
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


    def do_DELETE(self):
        if not self.local_request():
            return
        if urlsplit(self.path).path == "/api/account":
            handle_account(self)
        else:
            self.reply(404, {"error": "페이지가 없습니다."})


def make_server(port=8765, root=radar.ROOT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = Application(root)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--status-port", type=int, help="상태 조회 전용 loopback 포트")
    args = parser.parse_args()
    status_server = None
    if args.status_port:
        status_server = home_status.make_server(
            args.status_port, radar.ROOT, os.environ.get("HOME_STATUS_HOST", ""))
        threading.Thread(target=status_server.serve_forever, daemon=True).start()
    with make_server(args.port) as server:
        print(f"RepoBite: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.app.stop()
            if status_server:
                status_server.shutdown()
                status_server.server_close()
