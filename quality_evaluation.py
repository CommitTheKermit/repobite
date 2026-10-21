"""기본 저장소의 최근 갱신 이슈에서 고정 무작위 표본을 두 번 새 판정한다.

유료 실행 전용이다. 기존 radar 파일을 쓰지 않으며 새 출력 폴더만 허용한다.
README 이미지 판정은 호출하지 않는다. HTTP 재시도는 기존 Vertex 구현을 따른다.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
from urllib.parse import urlencode

import quality_measurement
import radar


APPROVED_PROFILE = {"model": "gemini-3.1-flash-lite", "reasoning_effort": "minimal",
                    "criteria_version": 2}
SAMPLE_SIZE = 30
REPEATS = 2
SOURCES = ("radar.py", "vertex.py", "freshness.py", "schema.json", "repos.txt",
           "quality_measurement.py", "quality_evaluation.py")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    with radar.atomic_output(path) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def save_rows(path, rows):
    with radar.atomic_output(path) as stream:
        for row in rows:
            radar.write_row(stream, row)


def source_hashes():
    return {name: file_hash(radar.ROOT / name) for name in SOURCES}


def collect_pool(repos_path, window_end):
    """radar와 같은 조회/제외 규칙, 이미지 AI 호출 없이 갱신 시각 범위를 고정한다."""
    window_start = window_end - timedelta(days=7)
    repos = list(dict.fromkeys(line.split("#", 1)[0].strip()
                              for line in repos_path.read_text(encoding="utf-8").splitlines()
                              if line.split("#", 1)[0].strip()))
    if len(repos) != 30:
        raise ValueError("승인된 기본 저장소 30개가 필요합니다")
    counts = Counter()
    rows = []
    for index, repo in enumerate(repos, 1):
        radar.issue_key({"repo": repo, "number": 1})
        query = urlencode({"state": "open", "since": window_start.isoformat(), "per_page": 100})
        pages = radar.gh_json(f"repos/{repo}/issues?{query}", "--paginate", "--slurp")
        for page in pages:
            for issue in page:
                counts["queried"] += 1
                updated = datetime.fromisoformat(issue["updated_at"])
                if updated.tzinfo is None:
                    raise ValueError("GitHub 갱신 시각에 시간대가 필요합니다")
                if not window_start <= updated <= window_end:
                    counts["outside_frozen_updated_window"] += 1
                    continue
                reason = radar.exclusion_reason(issue)
                if reason:
                    counts[reason] += 1
                    continue
                rows.append({**radar.normalize_issue(repo, issue),
                             "source_updated_at": issue["updated_at"]})
        print(f"pool_repositories={index}/{len(repos)} eligible_so_far={len(rows)}", flush=True)
    radar.unique_issues(rows)
    return rows, {"repositories": repos, "counts": dict(counts),
                  "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
                  "window_field": "updated_at", "state_at_collection": "open",
                  "image_selection": "omitted_no_vertex_calls"}


def select_sample(rows, seed):
    ordered = sorted(radar.unique_issues(rows), key=radar.issue_key)
    sample = random.Random(seed).sample(ordered, min(SAMPLE_SIZE, len(ordered)))
    if {radar.issue_key(row) for row in radar.select_for_grading(sample)} != {
            radar.issue_key(row) for row in sample}:
        raise ValueError("무작위 표본이 기존 판정 상한을 넘습니다. 유료 호출 전 중단합니다")
    return sample


def evaluate(output, seed, source_revision=""):
    if quality_measurement.current_profile() != APPROVED_PROFILE:
        raise ValueError("현행 프로필이 승인된 모델/기준과 다릅니다")
    # 기존 폴더는 실패 후 재실행도 거절해 이미 실행한 유료 판정의 반복을 막는다.
    output.mkdir(parents=False, exist_ok=False)
    sources = source_hashes()
    manifest = {"status": "collecting", "started_at": timestamp(), "seed": seed,
                "sample_size_limit": SAMPLE_SIZE, "repeats": REPEATS,
                "maximum_new_judgements": SAMPLE_SIZE * REPEATS,
                "http_retries": "unchanged_existing_vertex_policy_not_a_60_http_request_limit",
                "profile": APPROVED_PROFILE, "source_revision": source_revision,
                "source_sha256": sources, "passes": [], "human_audit_performed": False,
                "limitations": ["fixed_repository_list_is_not_all_github",
                                "open_unassigned_non_bot_issues_updated_within_seven_days",
                                "no_human_accuracy_precision_or_recall_measurement",
                                "freshness_is_a_separate_time_snapshot"]}
    manifest_path = output / "manifest.json"
    save_json(manifest_path, manifest)
    try:
        pool, collection = collect_pool(radar.ROOT / "repos.txt", datetime.now(timezone.utc))
        save_rows(output / "pool.jsonl", sorted(pool, key=radar.issue_key))
        sample = select_sample(pool, seed)
        sample_path = output / "sample.jsonl"
        save_rows(sample_path, sample)
        manifest.update(collection=collection, collection_completed_at=timestamp(),
                        pool_size=len(pool), sample_size=len(sample),
                        sample_keys=[{"repo": row["repo"], "number": row["number"]} for row in sample],
                        pool_sha256=file_hash(output / "pool.jsonl"),
                        sample_sha256=file_hash(sample_path))
        save_json(manifest_path, manifest)
        for number in range(1, REPEATS + 1):
            if source_hashes() != sources:
                raise ValueError("평가 중 원본 소스가 변경됐습니다")
            destination = output / f"repeat-{number}.jsonl"
            empty_reuse = output / f"empty-reuse-{number}.jsonl"
            empty_reuse.write_text("", encoding="utf-8")
            entry = {"number": number, "started_at": timestamp(), "status": "started",
                     "new_judgements_planned": len(sample), "reused": 0}
            manifest["passes"].append(entry)
            manifest["status"] = "grading"
            save_json(manifest_path, manifest)
            code = radar.grade(argparse.Namespace(input=sample_path, output=destination,
                                                  reuse=empty_reuse, model=radar.MODEL,
                                                  all_issues=False))
            rows = radar.read_jsonl(destination)
            if {radar.issue_key(row) for row in rows} != {radar.issue_key(row) for row in sample}:
                raise ValueError("판정 출력이 고정 표본과 다릅니다")
            entry.update(status="completed", completed_at=timestamp(), exit_code=code,
                         rows=len(rows), successful=sum(row.get("grade") is not None for row in rows),
                         failed=sum(row.get("grade") is None for row in rows), sha256=file_hash(destination))
            save_json(manifest_path, manifest)
            print(f"repeat={number} successful={entry['successful']} failed={entry['failed']}", flush=True)
        first, second = (radar.read_jsonl(output / f"repeat-{number}.jsonl") for number in (1, 2))
        description = f"기본 30개 저장소, 최근 7일 갱신 이슈 pool {len(pool)}건의 고정 무작위 {len(sample)}건"
        save_json(output / "quality.json", quality_measurement.measure_quality(
            first, repeat_rows=second, scope="sample", scope_description=description))
        save_json(output / "quality-repeat-2.json", quality_measurement.measure_quality(
            second, scope="sample", scope_description=description))
        manifest.update(status="completed", completed_at=timestamp())
        save_json(manifest_path, manifest)
        return 0
    except Exception as error:
        # 외부 오류 메시지는 인증값/본문을 반사할 수 있어 유형만 보관한다.
        manifest.update(status="interrupted_do_not_rerun", interrupted_at=timestamp(),
                        error_type=type(error).__name__)
        save_json(manifest_path, manifest)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="존재하지 않는 비공개 평가 폴더")
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--source-revision", default="", help="실제 실행 소스의 Git 커밋")
    args = parser.parse_args(argv)
    try:
        return evaluate(args.output, args.seed, args.source_revision)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"evaluation_failed={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
