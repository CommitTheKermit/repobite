"""Vertex AI Gemini JSON 호출. 외부 패키지 없이 ADC와 REST를 사용한다."""

import json
import os
import re
import subprocess
from urllib.request import Request, urlopen


DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_LOCATION = "global"


def _safe_name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9._:-]+", value):
        raise ValueError(f"{label} 형식이 잘못되었습니다")
    return value


def project_id(run=subprocess.run):
    value = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if value:
        return _safe_name(value, "GOOGLE_CLOUD_PROJECT")
    result = run(["gcloud", "config", "get-value", "project"], capture_output=True,
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
        result = run(["gcloud", "auth", "application-default", "print-access-token"],
                     capture_output=True, text=True, timeout=30)
        token = result.stdout.strip() if result.returncode == 0 else ""
    if not token:
        raise RuntimeError("Vertex AI ADC 인증이 필요합니다")
    return token


def generate_json(prompt, schema, model=DEFAULT_MODEL, open_url=urlopen):
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
    with open_url(request, timeout=300) as response:
        payload = json.load(response)
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("Vertex AI가 잘못된 JSON을 반환했습니다") from None
