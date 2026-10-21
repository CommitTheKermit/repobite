"""Windows 정기 실행 준비: python community_batch.py. 실제 작업 등록은 별도 수행."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import accounts
import community
import radar
import repository_discovery
from public_feed import public_items


def discovered_repositories(root):
    data = Path(root) / ".radar-community"
    data.mkdir(exist_ok=True)
    result = repository_discovery.run_github_trending(
        limit=30, period="weekly", allow_partial_trend=True,
        output_path=data / "discovered-repositories.json")
    trend, famous = result.get("trend", {}), result.get("famous", {})
    if (result.get("method") != "github_trending_and_cumulative_stars"
            or result.get("requested_total") != 30 or result.get("quota") != {"trend": 15, "famous": 15}
            or not isinstance(trend.get("items"), list) or not 1 <= len(trend["items"]) <= 15
            or not isinstance(famous.get("items"), list) or len(famous["items"]) != 15
            or famous.get("status") != "complete" or famous.get("shortfall") != 0
            or trend.get("status") != ("complete" if len(trend["items"]) == 15 else "partial")
            or trend.get("shortfall") != 15 - len(trend["items"])):
        raise ValueError("자동 발굴 결과의 선정 근거를 확인하세요.")
    rows = trend["items"] + famous["items"]
    names = [community.normalize_repo(row["repo"]) for row in rows]
    if (result.get("repos") != names or result.get("actual_total") != len(names)
            or len({name.lower() for name in names}) != len(names)
            or any(row.get("period") != "weekly" for row in trend["items"])):
        raise ValueError("자동 발굴 결과의 저장소와 기간을 확인하세요.")
    return names


def public_repositories(names):
    """이번 실행에서 공개인 저장소만 수집한다. 등록과 구독 자체는 보존한다."""
    public = {}
    for key, name in names.items():
        try:
            info = radar.gh_json(f"repos/{name}", include_status=True)
        except radar.GitHubAPIError as error:
            if error.status == 404:
                continue
            raise
        if not isinstance(info, dict) or type(info.get("private")) is not bool:
            raise ValueError("저장소의 공개 상태를 확인하지 못했습니다.")
        if not info["private"]:
            public[key] = name
    return public


def run(root=radar.ROOT, since="24h"):
    root = Path(root)
    submitted = community.registrations()
    names = {}
    for line in (root / "repos.txt").read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.setdefault(community.normalize_repo(name).lower(), name)
    for row in submitted:
        name = community.normalize_repo(row["repo"])
        names.setdefault(name.lower(), name)
    # 개인 식별자·이메일은 수집 목록이나 공개 결과로 전달하지 않는다.
    for value in accounts.subscription_repositories():
        name = community.normalize_repo(value)
        names.setdefault(name.lower(), name)
    discovered = discovered_repositories(root)
    for value in discovered:
        name = community.normalize_repo(value)
        names.setdefault(name.lower(), name)
    # gh가 비공개 레포 권한을 갖고 있어도 수집하거나 공개하지 않는다.
    names = public_repositories(names)
    discovered = [name for name in discovered if name.lower() in names]
    data = root / ".radar-community"
    data.mkdir(exist_ok=True)
    # ponytail: 기존 스케줄러처럼 동시에 한 배치만 실행. 여러 실행기가 생기면 DB 잠금 추가.
    items = []
    if names:
        with tempfile.TemporaryDirectory(dir=data) as directory:
            repos = Path(directory) / "repos.txt"
            repos.write_text("\n".join(names.values()) + "\n", encoding="utf-8")
            args = argparse.Namespace(repos=repos, since=since, issues=data / "issues.jsonl",
                                      grades=data / "grades.jsonl", candidates=data / "candidates.jsonl",
                                      model=radar.MODEL)
            if result := radar.batch(args):
                return result
        issues = [row for row in radar.read_jsonl(args.issues) if row["repo"].lower() in names]
        items = public_items(issues, radar.read_jsonl(args.grades))
    snapshot = {"items": items,
                "collected_repos": list(names), "collected_at": community.timestamp(),
                "discovered_repos": discovered}
    # 등록 목록은 건드리지 않는다. 배치 도중 추가된 레포는 다음 실행까지 대기로 남는다.
    community.redis("SET", community.SNAPSHOT_KEY, json.dumps(snapshot, ensure_ascii=False))
    print(f"공용 수집 결과 반영: 레포 {len(names)}개, 이슈 {len(snapshot['items'])}개")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="24h")
    args = parser.parse_args()
    try:
        sys.exit(run(since=args.since))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.TimeoutExpired):
        print("공용 배치 실패: DB 연결, GitHub와 Vertex AI 인증, 입력 파일을 확인하세요.", file=sys.stderr)
        sys.exit(1)
