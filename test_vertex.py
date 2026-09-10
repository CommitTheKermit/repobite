#!/usr/bin/env python3

from contextlib import contextmanager
import io
import json
import os
import tempfile
from unittest.mock import patch

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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as file:
        json.dump({"project_id": "service-account-project"}, file)
        file.flush()
        with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": file.name}, clear=True):
            assert vertex.project_id() == "service-account-project"
    print("통과: Vertex AI 전역 REST 호출과 JSON 스키마 응답")


if __name__ == "__main__":
    main()
