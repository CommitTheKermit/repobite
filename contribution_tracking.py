"""개인 착수 기록과 공개 GitHub PR 근거. 발송 성공이나 GitHub 선점은 추론하지 않는다.

PR 응답 근거: https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request
공개 레포 근거: https://docs.github.com/en/rest/repos/repos#get-a-repository
"""

from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re
from urllib.request import Request

import accounts
import community


ACTIONS = {"start", "cancel", "resume", "submit_pr", "verify_pr"}


class StateConflict(Exception):
    """이벤트 식별자 재사용 또는 현재 상태와 맞지 않는 요청."""


COMMIT_EVENT = """
local receipt = redis.call('HGET', KEYS[2], ARGV[1])
if receipt then
    local saved = cjson.decode(receipt)
    if saved.fingerprint ~= ARGV[2] then return cjson.encode({status='event_conflict'}) end
    return cjson.encode({status='replayed', result=saved.result})
end
local current = redis.call('HGET', KEYS[1], ARGV[3]) or ''
if current ~= ARGV[4] then return cjson.encode({status='retry'}) end
local receipt_value = cjson.decode(ARGV[6])
if receipt_value.result.changed then redis.call('HSET', KEYS[1], ARGV[3], ARGV[5]) end
redis.call('HSET', KEYS[2], ARGV[1], ARGV[6])
return cjson.encode({status='saved', result=receipt_value.result})
"""


def user_keys(user_id):
    accounts.subscriptions_key(user_id)  # 로그인에서 얻은 변경 불가능한 GitHub id 형식.
    prefix = "repobite:contributions:{" + user_id + "}:"
    return prefix + "records", prefix + "receipts"


def issue_identity(repo, number):
    repo = community.normalize_repo(repo).lower()
    if type(number) is not int or number <= 0:
        raise ValueError("이슈 번호를 확인하세요.")
    return repo, repo + "/" + str(number)


def pull_request_identity(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError("공개 GitHub PR 주소를 입력하세요.")
    match = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]*)/?", value)
    if not match:
        raise ValueError("공개 GitHub PR 주소를 입력하세요.")
    repo = community.normalize_repo(match[1]).lower()
    number = int(match[2])
    return repo, number, f"https://github.com/{repo}/pull/{number}"


def public_repository(repo):
    info = accounts.github_json(Request("https://api.github.com/repos/" + repo, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RepoBite"}))
    if (type(info.get("id")) is not int or info["id"] <= 0
            or not isinstance(info.get("full_name"), str)
            or info["full_name"].lower() != repo):
        raise RuntimeError("GitHub 저장소 정보를 확인하지 못했습니다.")
    if info.get("private") is not False or info.get("visibility", "public") != "public":
        raise ValueError("공개 GitHub 레포의 기여만 기록할 수 있습니다.")
    return info


def verified_issue(repo, number):
    """닫힌 이슈도 허용하되 존재하지 않는 번호나 PR 번호를 이슈로 저장하지 않는다."""
    info = accounts.github_json(Request(f"https://api.github.com/repos/{repo}/issues/{number}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RepoBite"}))
    url = info.get("html_url")
    if (type(info.get("number")) is not int or info["number"] != number
            or not isinstance(url, str) or url.lower() != f"https://github.com/{repo}/issues/{number}"
            or "pull_request" in info):
        raise ValueError("해당 레포의 실제 GitHub 이슈 번호인지 확인하세요. PR 번호는 사용할 수 없습니다.")


def verified_pull_request(user_id, issue_repo, value):
    repo, number, url = pull_request_identity(value)
    if repo != issue_repo:
        raise ValueError("이슈와 PR의 대상 레포가 같아야 합니다.")
    repository = public_repository(repo)
    api_url = f"https://api.github.com/repos/{repo}/pulls/{number}"
    info = accounts.github_json(Request(api_url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "RepoBite"}))
    author, base = info.get("user"), info.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (not isinstance(author, dict) or type(author.get("id")) is not int
            or str(author["id"]) != user_id):
        raise ValueError("현재 GitHub 계정이 작성한 PR만 기록할 수 있습니다.")
    if (not isinstance(base_repo, dict) or type(base_repo.get("id")) is not int
            or base_repo["id"] != repository["id"]
            or not isinstance(base_repo.get("full_name"), str)
            or base_repo["full_name"].lower() != repo or base_repo.get("private") is not False):
        raise ValueError("PR의 대상이 해당 공개 레포인지 확인하세요.")
    try:
        returned_repo, returned_number, _ = pull_request_identity(info.get("html_url"))
    except ValueError:
        raise RuntimeError("GitHub PR 정보를 확인하지 못했습니다.") from None
    if (returned_repo != repo or returned_number != number or type(info.get("number")) is not int
            or info["number"] != number or info.get("state") not in {"open", "closed"}
            or type(info.get("merged")) is not bool or "merged_at" not in info):
        raise RuntimeError("GitHub PR 정보를 확인하지 못했습니다.")
    merged_at = info["merged_at"]
    if merged_at is not None:
        try:
            if not isinstance(merged_at, str) or datetime.fromisoformat(merged_at).utcoffset() is None:
                raise ValueError()
        except (TypeError, ValueError):
            raise RuntimeError("GitHub 병합 정보를 확인하지 못했습니다.") from None
    if (info["merged"] != (merged_at is not None)
            or (merged_at is not None and info["state"] != "closed")):
        raise RuntimeError("GitHub 병합 정보를 확인하지 못했습니다.")
    return {"url": url, "number": number, "author_id": user_id, "base_repo": repo,
            "base_repo_id": repository["id"], "state": info["state"], "merged_at": merged_at,
            "provider": "github", "provider_api_url": api_url, "provider_checked_at": community.timestamp(),
            "issue_link_basis": "user_declared", "issue_closure_verified": False}


def new_record(repo, number, checked_at):
    return {"repo": repo, "number": number, "activity": "not_started", "pull_requests": {}, "events": [],
            "repository_public_verified_at": checked_at, "issue_existence_verified_at": checked_at,
            "created_at": checked_at, "updated_at": checked_at,
            "delivery_linkage": {"status": "not_connected", "delivery_id": None}}


def apply_action(existing, action, repo, number, event_id, checked_at, pull_request, delivery_id=None):
    record = deepcopy(existing) if existing else new_record(repo, number, checked_at)
    transitions = {"start": {"not_started": "active", "active": "active"},
                   "cancel": {"active": "cancelled", "cancelled": "cancelled"},
                   "resume": {"cancelled": "active", "active": "active"}}
    events = []
    if action in transitions:
        target = transitions[action].get(record["activity"])
        if target is None:
            raise StateConflict("현재 상태에서 해당 작업을 할 수 없습니다. 착수 또는 재개를 확인하세요.")
        if target != record["activity"]:
            record["activity"] = target
            events.append({"type": {"start": "started", "cancel": "cancelled", "resume": "resumed"}[action]})
    else:
        url = pull_request["url"]
        previous = record["pull_requests"].get(url)
        if action == "verify_pr" and previous is None:
            raise StateConflict("먼저 해당 PR을 신고하세요.")
        if previous and previous["merged_at"] and not pull_request["merged_at"]:
            raise RuntimeError("기존 병합 근거와 GitHub 응답이 다릅니다. 기존 기록을 유지합니다.")
        record["pull_requests"][url] = pull_request
        if previous is None:
            events.append({"type": "pr_submitted", "pr_url": url, "issue_link_basis": "user_declared"})
        else:
            events.append({"type": "pr_verified", "pr_url": url})
        if pull_request["merged_at"] and (previous is None or not previous["merged_at"]):
            events.append({"type": "pr_merged", "pr_url": url, "merged_at": pull_request["merged_at"]})
    if delivery_id is not None:
        linked = set(record["delivery_linkage"].get("delivery_ids", []))
        if delivery_id not in linked:
            linked.add(delivery_id)
            record["delivery_linkage"] = {"status": "operator_confirmed", "delivery_id": delivery_id,
                "delivery_ids": sorted(linked), "attestation_basis": "operator_confirmation",
                "provider_delivery_verified": False}
            events.append({"type": "delivery_linked", "delivery_id": delivery_id})
    for event in events:
        if delivery_id is not None:
            event["delivery_id"] = delivery_id
        record["events"].append({**event, "event_id": event_id, "occurred_at": checked_at})
    if events:
        record["updated_at"] = checked_at
    return record, bool(events)


def delivery_key(user_id):
    user_keys(user_id)
    return "repobite:contributions:{" + user_id + "}:deliveries"


def validate_delivery_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise ValueError("전달 식별자를 확인하세요.")


def record_delivery(user_id, digest_id, day, items, confirmed_at, state="operator_confirmed", provider_id=None):
    """서버 outbox 전용. 운영자 확인과 제공자 접수를 구분하고 실제 수신으로 간주하지 않는다."""
    key = delivery_key(user_id)
    validate_delivery_id(digest_id)
    try:
        if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                or not isinstance(confirmed_at, str) or datetime.fromisoformat(confirmed_at).utcoffset() is None):
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("운영자 확인 날짜와 시각을 확인하세요.") from None
    if state not in ("operator_confirmed", "provider_accepted"):
        raise ValueError("발송 기록의 상태를 확인하세요.")
    if state == "provider_accepted" and (not isinstance(provider_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', provider_id)):
        raise ValueError("제공자 접수 식별자를 확인하세요.")
    if not isinstance(items, list) or not 0 < len(items) <= accounts.DAILY_LIMIT:
        raise ValueError("수동 발송 항목을 확인하세요.")
    identities = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("수동 발송 항목을 확인하세요.")
        repo, _ = issue_identity(item.get("repo"), item.get("number"))
        identity = repo, item["number"]
        if identity in identities:
            raise ValueError("수동 발송 항목에 중복 이슈가 있습니다.")
        identities.add(identity)
    normalized = [{"repo": repo, "number": number} for repo, number in sorted(identities)]
    record = {"id": digest_id, "day": day, "items": normalized, "confirmed_at": confirmed_at,
              "state": state, "attestation_basis": "operator_confirmation", "provider_delivery_verified": False}
    if state == "provider_accepted":
        record.update(attestation_basis="provider_acceptance", provider_id=provider_id)
    value = json.dumps(record, ensure_ascii=False, sort_keys=True)
    created = community.redis("HSETNX", key, digest_id, value)
    if not created:
        previous = community.redis("HGET", key, digest_id)
        if not previous or json.loads(previous) != record:
            raise StateConflict("기존 전달 식별자의 수신자 또는 항목을 바꿀 수 없습니다.")
    return {"delivery": record, "created": bool(created)}


def user_deliveries(user_id):
    records = [json.loads(value) for value in community.redis("HVALS", delivery_key(user_id)) or []]
    return sorted(records, key=lambda record: (record["day"], record["id"]), reverse=True)


def require_issue_delivery(user_id, digest_id, repo, number):
    validate_delivery_id(digest_id)
    saved = community.redis("HGET", delivery_key(user_id), digest_id)
    record = json.loads(saved) if saved else None
    if (not record or record.get("state") != "operator_confirmed"
            or not any(item["repo"] == repo and item["number"] == number for item in record["items"])):
        raise StateConflict("현재 계정과 이슈에 해당하는 운영자 확인 전달 기록이 없습니다.")


def record_event(user_id, action, repo, number, event_id, pr_url=None, delivery_id=None):
    records_key, receipts_key = user_keys(user_id)
    repo, key = issue_identity(repo, number)
    if action not in ACTIONS:
        raise ValueError("기여 기록 동작을 확인하세요.")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", event_id):
        raise ValueError("이벤트 식별자를 확인하세요.")
    if action in {"submit_pr", "verify_pr"}:
        _, _, pr_url = pull_request_identity(pr_url)
    elif pr_url is not None:
        raise ValueError("착수 기록에는 PR 주소가 필요하지 않습니다.")
    request_identity = [action, repo, number, pr_url]
    if delivery_id is not None:
        request_identity.append(delivery_id)
    fingerprint = hashlib.sha256(json.dumps(request_identity).encode()).hexdigest()
    receipt = community.redis("HGET", receipts_key, event_id)
    if receipt:
        saved = json.loads(receipt)
        if saved["fingerprint"] != fingerprint:
            raise StateConflict("이벤트 식별자를 다른 요청에 다시 사용할 수 없습니다.")
        return {**saved["result"], "replayed": True}
    existing_raw = community.redis("HGET", records_key, key)
    existing = json.loads(existing_raw) if existing_raw else None
    if delivery_id is not None:
        require_issue_delivery(user_id, delivery_id, repo, number)
    if action == "verify_pr" and (not existing or pr_url not in existing["pull_requests"]):
        raise StateConflict("먼저 해당 PR을 신고하세요.")
    pull_request = verified_pull_request(user_id, repo, pr_url) if pr_url else None
    checked_at = pull_request["provider_checked_at"] if pull_request else community.timestamp()
    if not existing and pull_request is None:
        if action != "start":
            raise StateConflict("먼저 이슈에 착수하세요.")
        public_repository(repo)
    if not existing:
        verified_issue(repo, number)
        checked_at = community.timestamp()
    for _ in range(4):
        existing = json.loads(existing_raw) if existing_raw else None
        record, changed = apply_action(existing, action, repo, number, event_id, checked_at, pull_request, delivery_id)
        result = {"record": record, "changed": changed}
        receipt = {"fingerprint": fingerprint, "result": result}
        response = json.loads(community.redis(
            "EVAL", COMMIT_EVENT, 2, records_key, receipts_key, event_id, fingerprint, key,
            existing_raw or "", json.dumps(record, ensure_ascii=False), json.dumps(receipt, ensure_ascii=False)))
        if response["status"] == "event_conflict":
            raise StateConflict("이벤트 식별자를 다른 요청에 다시 사용할 수 없습니다.")
        if response["status"] != "retry":
            return {**response["result"], "replayed": response["status"] == "replayed"}
        existing_raw = community.redis("HGET", records_key, key)
    raise StateConflict("기여 기록이 변경됐습니다. 현재 상태를 확인하고 다시 시도하세요.")


def user_contributions(user_id):
    records_key, _ = user_keys(user_id)
    records = [json.loads(value) for value in community.redis("HVALS", records_key) or []]
    records.sort(key=lambda row: (row["repo"], row["number"]))
    merged = {pr["url"] for record in records for pr in record["pull_requests"].values() if pr["merged_at"]}
    deliveries = user_deliveries(user_id)
    return {"records": records, "deliveries": deliveries,
            "summary": {"tracked_issues": len(records), "merged_pr_count": len(merged),
            "operator_confirmed_digest_count": sum(d['state'] == 'operator_confirmed' for d in deliveries),
            "provider_accepted_digest_count": sum(d['state'] == 'provider_accepted' for d in deliveries),
            "provider_delivery_verified": False,
            "success_basis": "verified_github_author_id_and_merged_at_unique_pr_url",
            "issue_link_basis": "user_declared", "delivery_conversion_measured": False,
            "automatic_level_expansion": False}}
