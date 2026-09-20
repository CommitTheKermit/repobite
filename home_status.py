"""Read-only home-server status, isolated from RepoBite's management API."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def windows_status():
    if os.name != "nt":
        return {"available": False, "reason": "Windows에서 확인할 수 있습니다."}
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts/read-home-status.ps1")],
            capture_output=True, timeout=20, check=True, encoding="utf-8")
        return json.loads(result.stdout.lstrip("\ufeff"))
    except (OSError, subprocess.SubprocessError, ValueError):
        # Never send raw PowerShell errors, paths or environment values to clients.
        return {"available": False, "reason": "서비스 조회 실패. SSH로 상태를 확인하세요."}


def collection_status(root):
    results = {}
    for mode, directory in (("local", root), ("community", root / ".radar-community")):
        files = {}
        for name in ("issues", "grades", "candidates"):
            path = directory / f"{name}.jsonl"
            try:
                modified = path.stat().st_mtime
                with path.open(encoding="utf-8") as stream:
                    count = sum(1 for line in stream if line.strip())
                files[name] = {"rows": count,
                               "updated_at": datetime.fromtimestamp(modified, timezone.utc).isoformat(),
                               "stale": time.time() - modified > 36 * 3600}
            except FileNotFoundError:
                files[name] = {"missing": True}
            except (OSError, UnicodeError):
                files[name] = {"unavailable": True}
        results[mode] = files
    return results


class StatusSnapshot:
    """Cache bounded system queries; failures replace old success rather than hiding it."""

    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.cached = None
        self.expires = 0

    def read(self):
        with self.lock:
            if self.cached is None or time.monotonic() >= self.expires:
                system = windows_status()
                notes = []
                try:
                    raw = json.loads((self.root / ".home-status-notes.json").read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        notes = [note[:500] for note in raw[:10] if isinstance(note, str)]
                except FileNotFoundError:
                    pass
                except (OSError, ValueError):
                    notes = ["운영 메모를 읽지 못했습니다."]
                self.cached = {"checked_at": utc_now(), "refresh_seconds": 30,
                               "system": system, "collections": collection_status(self.root),
                               "notes": notes}
                self.expires = time.monotonic() + 30
            return self.cached


class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                         "style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Host") not in self.server.allowed_hosts:
            self.respond(403, b"Forbidden", "text/plain")
        elif self.path in ("/", "/status"):
            self.respond(200, (ROOT / "home-status.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/status.json":
            self.respond(200, json.dumps(self.server.snapshot.read(), ensure_ascii=False).encode(),
                         "application/json; charset=utf-8")
        else:
            self.respond(404, b"Not found", "text/plain")


def make_server(port, root, public_host):
    # Only Tailscale Serve and local clients can reach this listener. It has no mutation routes.
    server = ThreadingHTTPServer(("127.0.0.1", port), StatusHandler)
    server.allowed_hosts = {f"127.0.0.1:{server.server_port}", f"localhost:{server.server_port}"}
    if public_host:
        server.allowed_hosts.add(public_host)
    server.snapshot = StatusSnapshot(root)
    return server
