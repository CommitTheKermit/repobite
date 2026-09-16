"""Windows 정기 실행 준비: python community_batch.py. 실제 작업 등록은 별도 수행."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import community
import radar
from web import public_items


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
    # gh가 비공개 레포 권한을 갖고 있어도 공개 피드에 그 내용을 올리지 않는다.
    for name in names.values():
        if radar.gh_json(f"repos/{name}").get("private") is not False:
            raise ValueError("공개 상태를 확인할 수 없는 레포가 있습니다.")
    data = root / ".radar-community"
    data.mkdir(exist_ok=True)
    # ponytail: 기존 스케줄러처럼 동시에 한 배치만 실행. 여러 실행기가 생기면 DB 잠금 추가.
    with tempfile.TemporaryDirectory(dir=data) as directory:
        repos = Path(directory) / "repos.txt"
        repos.write_text("\n".join(names.values()) + "\n", encoding="utf-8")
        args = argparse.Namespace(repos=repos, since=since, issues=data / "issues.jsonl",
                                  grades=data / "grades.jsonl", candidates=data / "candidates.jsonl",
                                  model=radar.MODEL)
        if result := radar.batch(args):
            return result
    snapshot = {"items": public_items(radar.read_jsonl(args.issues), radar.read_jsonl(args.grades)),
                "collected_repos": list(names), "collected_at": community.timestamp()}
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
