"""현행 판정 JSONL의 공급량, 반복 일치, 사람 감사를 오프라인 측정한다.

Python 3.14 표준 라이브러리만 사용하며 GitHub와 Vertex를 호출하지 않는다.
과거 파일을 읽을 수 있으나 현행 모델/사고 수준/기준과 다른 행은 합산하지 않는다.
"""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

import radar


PROFILE_FIELDS = ("model", "reasoning_effort", "criteria_version")
VERDICTS = {
    "plausible": "plausible", "바로추천가능": "plausible", "적합": "plausible",
    "conditional": "conditional", "조건부": "conditional", "추가확인필요": "conditional",
    "incorrect": "incorrect", "부적합": "incorrect", "추천부적합": "incorrect",
}


def current_profile():
    return {"model": radar.MODEL, "reasoning_effort": radar.REASONING_EFFORT,
            "criteria_version": radar.CRITERIA_VERSION}


def unique_rows(rows, source):
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{source}: JSON 객체가 필요합니다")
        key = radar.issue_key(row)
        if key in indexed:
            raise ValueError(f"{source}: 중복 이슈 키가 있습니다")
        indexed[key] = row
    return indexed


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
            "status": "measured" if denominator else "measurement_unavailable"}


def unavailable(reason):
    return {"status": "measurement_unavailable", "reason": reason}


def separate_current_rows(rows):
    """다른/미확인 판정 프로필을 현행 품질의 분모와 분자 모두에서 뺀다."""
    indexed = unique_rows(rows, "판정 입력")
    matching, excluded = {}, Counter()
    expected = current_profile()
    for key, row in indexed.items():
        mismatched = tuple(field for field in PROFILE_FIELDS
                           if type(row.get(field)) is not type(expected[field])
                           or row.get(field) != expected[field])
        if mismatched:
            excluded[mismatched] += 1
            continue
        if row.get("grade") is None:
            if not isinstance(row.get("error"), str) or not row["error"].strip():
                raise ValueError("현행 판정 실패 행에 error가 필요합니다")
        else:
            radar.validate_grade(row["grade"])
            if row.get("error"):
                raise ValueError("성공 판정과 error가 동시에 있습니다")
        matching[key] = row
    return matching, {"rows": len(indexed), "current_rows": len(matching),
                      "excluded_rows": len(indexed) - len(matching),
                      "excluded_by_profile_fields": [
                          {"fields": list(fields), "rows": count}
                          for fields, count in sorted(excluded.items())]}


def raw_recommendation(row):
    return radar.freshness.is_candidate(row)


def freshness_snapshot(row):
    """시간대 있는 검사 시각과 이진 결과를 가진 저장된 스냅샷만 인정한다."""
    snapshot = row.get("freshness")
    if not isinstance(snapshot, dict) or type(snapshot.get("eligible")) is not bool:
        return None
    try:
        checked = datetime.fromisoformat(snapshot["checked_at"])
        if checked.utcoffset() is None:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return snapshot["eligible"]


def measure_supply(rows):
    total = len(rows)
    successful = [row for row in rows.values() if row.get("grade") is not None]
    candidates = [row for row in successful if raw_recommendation(row)]
    snapshots = Counter(freshness_snapshot(row) for row in candidates)
    grades = [row["grade"] for row in successful]
    freshness_supply = ratio(snapshots[True], total)
    if snapshots[None]:
        freshness_supply.update(status="partial", unverified_candidates=snapshots[None],
                                limitation="confirmed_supply_lower_bound_not_complete_freshness_result")
    return {
        "status": "measured" if total else "measurement_unavailable",
        "denominator": "all_current_profile_rows_including_failures",
        "profile_rows": total, "successful": len(successful), "failed": total - len(successful),
        "limitation": "may_include_reused_judgements_row_count_is_not_model_call_count",
        "success": ratio(len(successful), total),
        "raw_lv1_ready_supply": ratio(len(candidates), total),
        "freshness_eligible_supply": freshness_supply,
        "raw_candidate_freshness": {"eligible": snapshots[True], "ineligible": snapshots[False],
                                    "unverified": snapshots[None]},
        "freshness_basis": "recorded_snapshot_only_no_live_recheck_or_age_guarantee",
        "excluded": sum(grade["exclude"] for grade in grades),
        "difficulty_among_successful": dict(sorted(Counter(str(g["difficulty"]) for g in grades).items())),
        "readiness_among_successful": dict(sorted(Counter(g["readiness"] for g in grades).items())),
        "v2_readiness_mapping_violations": sum(
            g["readiness"] != {1: "ready", 2: "needs_info", 3: "undecided"}[g["difficulty"]]
            for g in grades),
    }


def measure_repeat(primary, repeat):
    compared = []
    skipped = Counter()
    for key in primary.keys() & repeat.keys():
        first, second = primary[key], repeat[key]
        if first.get("grade") is None or second.get("grade") is None:
            skipped["failed_judgement"] += 1
        elif any(not isinstance(row.get(field), str)
                 for row in (first, second) for field in ("title", "body")):
            skipped["input_text_unverified"] += 1
        elif any(first[field] != second[field] for field in ("title", "body")):
            skipped["changed_title_or_body"] += 1
        else:
            compared.append((first, second))
    metrics = {field: ratio(sum(a["grade"][field] == b["grade"][field] for a, b in compared),
                            len(compared)) for field in ("exclude", "difficulty", "readiness")}
    metrics["all_three_fields"] = ratio(sum(
        all(a["grade"][f] == b["grade"][f] for f in ("exclude", "difficulty", "readiness"))
        for a, b in compared), len(compared))
    metrics["raw_recommendation"] = ratio(sum(raw_recommendation(a) == raw_recommendation(b)
                                            for a, b in compared), len(compared))
    return {"status": "measured" if compared else "measurement_unavailable",
            "basis": "successful_common_keys_with_identical_title_body_and_current_profile",
            "shared_current_keys": len(primary.keys() & repeat.keys()),
            "primary_only_current_keys": len(primary.keys() - repeat.keys()),
            "repeat_only_current_keys": len(repeat.keys() - primary.keys()),
            "comparable": len(compared), "skipped": dict(sorted(skipped.items())),
            "agreement": metrics,
            "limitation": "raw_recommendation_excludes_freshness_changes_and_is_not_human_accuracy"}


def read_audit(path):
    """기존 docs/일반-모집단-추천-감사.json의 JSON 배열 형식을 사용한다."""
    labels = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(labels, list):
        raise ValueError("감사 파일은 JSON 배열이어야 합니다")
    return labels


def measure_audit(primary, labels, audit_scope):
    audit = unique_rows(labels, "사람 감사")
    matched = []
    skipped = Counter()
    for key, label in audit.items():
        verdict = label.get("verdict")
        verdict = VERDICTS.get("".join(verdict.split())) if isinstance(verdict, str) else None
        if verdict is None:
            raise ValueError("알 수 없는 사람 감사 verdict입니다")
        if any(field in label and not isinstance(label[field], str) for field in ("title", "body")):
            raise ValueError("감사 title/body를 제공하면 문자열이어야 합니다")
        row = primary.get(key)
        if row is None:
            skipped["not_in_current_input"] += 1
        elif row.get("grade") is None:
            skipped["failed_judgement"] += 1
        elif any(field in label and label[field] != row.get(field) for field in ("title", "body")):
            skipped["changed_title_or_body"] += 1
        else:
            matched.append((row, verdict, all(field in label for field in ("title", "body"))))

    positives = [(row, verdict) for row, verdict, _ in matched if raw_recommendation(row)]
    negatives = [(row, verdict) for row, verdict, _ in matched if not raw_recommendation(row)]
    counts = Counter(verdict for _, verdict in positives)
    missed = sum(verdict == "plausible" for _, verdict in negatives)
    human_positive = sum(verdict == "plausible" for _, verdict, _ in matched)
    full_coverage = len(matched) == len(primary) and bool(primary)
    if audit_scope != "all-input":
        recall = unavailable("선별된 감사의 누락률을 입력 전체로 추정하지 않습니다")
    elif not full_coverage:
        recall = unavailable("전체 입력 감사에 누락 또는 판정 실패가 있습니다")
    elif not negatives:
        recall = unavailable("추천 양성만 감사했으므로 recall을 추정하지 않습니다")
    else:
        recall = ratio(human_positive - missed, human_positive)
    verified_freshness = [(row, verdict) for row, verdict in positives
                          if freshness_snapshot(row) is True]
    return {
        "status": "measured" if matched else "measurement_unavailable",
        "human_audit_performed": bool(labels),
        "declared_scope": audit_scope, "labels": len(audit), "matched_successful": len(matched),
        "skipped": dict(sorted(skipped.items())),
        "coverage_of_current_input": ratio(len(matched), len(primary)),
        "labels_with_verified_title_and_body": sum(verified for _, _, verified in matched),
        "label_basis": "user_supplied_not_independently_audited_no_live_state_check",
        "metric_scope": "matched_audited_successful_rows_only",
        "audited_raw_candidates": len(positives), "audited_non_candidates": len(negatives),
        "candidate_verdicts": dict(sorted(counts.items())),
        "strict_precision": ratio(counts["plausible"], len(positives)),
        "conditional_inclusive_precision": ratio(counts["plausible"] + counts["conditional"], len(positives)),
        "freshness_eligible_strict_precision": ratio(
            sum(verdict == "plausible" for _, verdict in verified_freshness), len(verified_freshness)),
        "missed_plausible_in_audited_rows": (ratio(missed, human_positive) if negatives else
                                            unavailable("추천 양성만 감사해 누락을 측정할 수 없습니다")),
        "strict_recall": recall,
        "limitation": "selected_labels_do_not_estimate_population_accuracy_or_unaudited_misses",
    }


def measure_quality(rows, *, scope="unspecified", scope_description="", repeat_rows=None,
                    audit_labels=None, audit_scope="selected"):
    if scope not in {"population", "sample", "unspecified"}:
        raise ValueError("scope는 population, sample, unspecified 중 하나여야 합니다")
    if audit_scope not in {"selected", "all-input"}:
        raise ValueError("audit_scope는 selected 또는 all-input이어야 합니다")
    primary, inventory = separate_current_rows(rows)
    result = {
        "schema_version": 1, "policy": current_profile(),
        "scope": {"kind": scope, "description": scope_description,
                  "basis": "operator_declared_not_independently_verified",
                  "limitation": "input_scope_only_collection_filters_and_unselected_issues_not_measured"},
        "input": inventory, "supply": measure_supply(primary),
        "repeat": unavailable("반복 판정 입력이 없습니다"),
        "audit": {**unavailable("사람 감사 입력이 없습니다"), "human_audit_performed": False},
    }
    if repeat_rows is not None:
        repeat, repeat_inventory = separate_current_rows(repeat_rows)
        result["repeat"] = {**measure_repeat(primary, repeat), "input": repeat_inventory}
    if audit_labels is not None:
        result["audit"] = measure_audit(primary, audit_labels, audit_scope)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="성공/실패를 포함한 판정 JSONL")
    parser.add_argument("--repeat", type=Path, help="같은 입력을 독립적으로 반복 판정한 JSONL")
    parser.add_argument("--audit", type=Path, help="사람 verdict를 담은 JSON 배열")
    parser.add_argument("--audit-scope", choices=("selected", "all-input"), default="selected")
    parser.add_argument("--scope", choices=("population", "sample", "unspecified"), default="unspecified")
    parser.add_argument("--scope-description", default="", help="모집단/표본 선정과 실행 시점 설명")
    parser.add_argument("--output", type=Path, help="JSON 저장 위치, 생략하면 stdout")
    args = parser.parse_args(argv)
    if args.audit_scope != "selected" and args.audit is None:
        parser.error("--audit-scope에는 --audit가 필요합니다")
    sources = [path.resolve() for path in (args.input, args.repeat, args.audit) if path]
    if args.output and args.output.resolve() in sources:
        parser.error("출력 경로는 원본 입력과 달라야 합니다")
    if args.repeat and args.repeat.resolve() == args.input.resolve():
        parser.error("반복 비교에는 서로 다른 실행 파일이 필요합니다")
    try:
        result = measure_quality(
            radar.read_jsonl(args.input), scope=args.scope, scope_description=args.scope_description,
            repeat_rows=radar.read_jsonl(args.repeat) if args.repeat else None,
            audit_labels=read_audit(args.audit) if args.audit else None, audit_scope=args.audit_scope)
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with radar.atomic_output(args.output) as stream:
                stream.write(content)
        else:
            sys.stdout.write(content)
    except (OSError, ValueError) as error:
        # 원문 행, 이슈 본문, 오류 응답 또는 잘못된 JSON 내용을 출력하지 않는다.
        parser.exit(2, "측정 실패: " + (str(error) if isinstance(error, ValueError)
                                    and not isinstance(error, json.JSONDecodeError)
                                    else type(error).__name__) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
