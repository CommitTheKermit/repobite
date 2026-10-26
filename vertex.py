"""Vertex AI Gemini JSON 호출. 외부 패키지 없이 ADC와 REST를 사용한다."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_LOCATION = "global"


class VertexHTTPError(HTTPError):
    """HTTP 진단만 보관한다. 응답 원문, 요청 URL과 인증 헤더는 보관하지 않는다."""

    def __init__(self, error, attempts):
        causes = {400: "요청 형식 또는 모델 입력 조건 오류", 401: "인증 실패",
                  403: "권한 또는 API 사용 설정 오류", 404: "모델 또는 리소스를 찾을 수 없음",
                  408: "요청 시간 초과", 413: "입력 크기 초과",
                  429: "요청 한도 또는 처리 용량 초과"}
        cause = causes.get(error.code, "서비스 처리 오류" if error.code >= 500 else "HTTP 요청 실패")
        details = {"http_status": error.code, "cause": cause, "attempts": attempts}
        try:
            payload = json.loads(error.read(8192)).get("error", {})
            # API message나 metadata는 입력과 인증값을 반사할 수 있어 기록하지 않는다.
            status = payload.get("status")
            if isinstance(status, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", status):
                details["api_status"] = status
            for item in payload.get("details", []):
                if not isinstance(item, dict) or item.get("@type") != "type.googleapis.com/google.rpc.ErrorInfo":
                    continue
                reason = item.get("reason")
                if isinstance(reason, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", reason):
                    details["reason"] = reason
                    break
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            error.close()
        self.diagnostics = details
        super().__init__(None, error.code, cause, {}, None)

    def log_message(self):
        return " ".join(f"{key}={value}" for key, value in self.diagnostics.items())


def _gcloud():
    return shutil.which("gcloud") or "gcloud"


def _safe_name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]+", value):
        raise ValueError(f"{label} 형식이 잘못되었습니다")
    return value


def project_id(run=subprocess.run):
    value = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if value:
        return _safe_name(value, "GOOGLE_CLOUD_PROJECT")
    credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials:
        try:
            with open(credentials, encoding="utf-8") as file:
                value = json.load(file).get("project_id")
        except (OSError, json.JSONDecodeError, AttributeError) as error:
            raise RuntimeError("서비스 계정 파일을 읽을 수 없습니다") from error
        if not value:
            raise RuntimeError("서비스 계정 파일에 project_id가 없습니다")
        return _safe_name(value, "서비스 계정 project_id")
    result = run([_gcloud(), "config", "get-value", "project"], capture_output=True,
                 text=True, timeout=30)
    value = result.stdout.strip()
    if result.returncode or not value or value == "(unset)":
        raise RuntimeError("GOOGLE_CLOUD_PROJECT가 필요합니다")
    return _safe_name(value, "GCP 프로젝트")


def access_token(run=subprocess.run, open_url=urlopen):
    if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
        host = os.environ.get("GCE_METADATA_HOST", "metadata.google.internal")
        request = Request(
            f"http://{host}/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"})
        with open_url(request, timeout=10) as response:
            token = json.load(response).get("access_token")
    else:
        result = run([_gcloud(), "auth", "application-default", "print-access-token"],
                     capture_output=True, text=True, timeout=30)
        token = result.stdout.strip() if result.returncode == 0 else ""
    if not token:
        raise RuntimeError("Vertex AI ADC 인증이 필요합니다")
    return token


def generate_json(prompt, schema, model=DEFAULT_MODEL, open_url=urlopen, sleep=time.sleep):
    project = project_id()
    location = _safe_name(os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION),
                          "GOOGLE_CLOUD_LOCATION")
    model = _safe_name(model, "모델")
    endpoint = ("aiplatform.googleapis.com" if location == "global"
                else f"{location}-aiplatform.googleapis.com")
    url = (f"https://{endpoint}/v1/projects/{project}/locations/{location}/"
           f"publishers/google/models/{model}:generateContent")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "thinkingConfig": {"thinkingLevel": "MINIMAL"},
        },
    }).encode()
    request = Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {access_token()}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": project,
    })
    for attempt, delay in enumerate((1, 2, 4, 8, None)):
        try:
            with open_url(request, timeout=300) as response:
                payload = json.load(response)
            break
        except HTTPError as error:
            retry_after = (error.headers or {}).get("Retry-After")
            failure = VertexHTTPError(error, attempt + 1)
            retry = error.code in {429, 500, 502, 503, 504} and delay is not None
            print(f"Vertex AI HTTP 실패: {failure.log_message()} retry={str(retry).lower()}",
                  file=sys.stderr)
            if not retry:
                raise failure from None
            try:
                delay = max(delay, min(float(retry_after), 30))
            except (TypeError, ValueError):
                pass
            sleep(delay)
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("Vertex AI가 잘못된 JSON을 반환했습니다") from None
