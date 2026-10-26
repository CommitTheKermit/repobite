#!/usr/bin/env python3

from contextlib import contextmanager
from contextlib import redirect_stderr
import io
import json
import os
import tempfile
from urllib.error import HTTPError
from unittest.mock import patch
from types import SimpleNamespace

import vertex


@contextmanager
def response(payload):
    yield io.BytesIO(json.dumps(payload).encode())


def main():
    seen = {}

    def open_url(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return response({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]})

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    with (patch.dict(os.environ, {"GOOGLE_CLOUD_LOCATION": "global"}, clear=True),
          patch.object(vertex, "project_id", return_value="sample-project"),
          patch.object(vertex, "access_token", return_value="hidden-token")):
        assert vertex.generate_json("분류", schema, open_url=open_url) == {"ok": True}
    assert seen["url"].startswith("https://aiplatform.googleapis.com/v1/projects/sample-project/")
    assert seen["body"]["generationConfig"]["responseJsonSchema"] == schema
    assert seen["body"]["generationConfig"]["temperature"] == 0
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert seen["timeout"] == 300

    attempts = []
    delays = []

    def flaky_open(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "3"}, None)
        return response({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]})

    with (patch.dict(os.environ, {"GOOGLE_CLOUD_LOCATION": "global"}, clear=True),
          patch.object(vertex, "project_id", return_value="sample-project"),
          patch.object(vertex, "access_token", return_value="hidden-token")):
        assert vertex.generate_json("분류", schema, open_url=flaky_open,
                                    sleep=delays.append) == {"ok": True}
    assert len(attempts) == 2
    assert delays == [3]

    diagnostics_log = io.StringIO()
    attempts.clear()
    delays.clear()

    def exhausted_open(request, timeout):
        attempts.append(request)
        body = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "PRIVATE_PROMPT hidden-token",
                          "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                       "reason": "RATE_LIMIT_EXCEEDED",
                                       "metadata": {"token": "hidden-token"}}]}}
        raise HTTPError(request.full_url, 429, "hidden-token", {},
                        io.BytesIO(json.dumps(body).encode()))

    with (patch.object(vertex, "project_id", return_value="sample-project"),
          patch.object(vertex, "access_token", return_value="hidden-token"),
          redirect_stderr(diagnostics_log)):
        try:
            vertex.generate_json("PRIVATE_PROMPT", schema, open_url=exhausted_open, sleep=delays.append)
            raise AssertionError("재시도 소진은 실패해야 합니다")
        except vertex.VertexHTTPError as error:
            assert error.code == 429
            assert error.diagnostics["attempts"] == 5
            assert error.diagnostics["api_status"] == "RESOURCE_EXHAUSTED"
            assert error.diagnostics["reason"] == "RATE_LIMIT_EXCEEDED"
            assert "hidden-token" not in str(error)
    assert len(attempts) == 5 and delays == [1, 2, 4, 8]
    log = diagnostics_log.getvalue()
    assert log.count("http_status=429") == 5 and "retry=false" in log
    assert "hidden-token" not in log and "PRIVATE_PROMPT" not in log
    assert "sample-project" not in log and "https://" not in log
    for body in (b"not json", b"[]", b'{"error":{"details":null}}'):
        failure = vertex.VertexHTTPError(HTTPError("secret-url", 403, "secret", {}, io.BytesIO(body)), 1)
        assert failure.diagnostics["http_status"] == 403
        assert failure.diagnostics["cause"] == "권한 또는 API 사용 설정 오류"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete_on_close=False) as file:
        json.dump({"project_id": "service-account-project"}, file)
        file.flush()
        with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": file.name}, clear=True):
            assert vertex.project_id() == "service-account-project"

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="hidden-token\n")

    with patch.object(vertex.shutil, "which", return_value=r"C:\Tools\gcloud.CMD"):
        assert vertex.access_token(run=run) == "hidden-token"
    assert calls[0][0] == [r"C:\Tools\gcloud.CMD", "auth", "application-default",
                           "print-access-token"]
    print("통과: Vertex AI 전역 REST 호출과 JSON 스키마 응답")


if __name__ == "__main__":
    main()
