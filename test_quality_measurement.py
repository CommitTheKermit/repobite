"""오프라인 fixture로 분모, 메타데이터 격리, 감사 선택 편향을 검증한다."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quality_measurement as quality


def judgement(number, *, level=1, excluded=False, eligible=True, **overrides):
    row = {
        "repo": "Example/Project", "number": number, "title": f"이슈 {number}", "body": "고정 본문",
        **quality.current_profile(),
        "grade": {"difficulty": level, "readiness": {1: "ready", 2: "needs_info", 3: "undecided"}[level],
                  "exclude": excluded, "exclude_reason": "이미 수정됨" if excluded else "",
                  "reason": "재현과 원인 및 수정 방향이 구체적임"},
        "freshness": {"eligible": eligible, "reason": "fixture", "checked_at": "2026-10-21T02:00:00Z"},
    }
    return {**row, **overrides}


def label(number, verdict="plausible", **overrides):
    return {"repo": "example/project", "number": number, "verdict": verdict,
            "reason": "사람이 제공한 fixture", **overrides}


class SupplyTests(unittest.TestCase):
    def test_failures_and_exclusions_remain_in_supply_denominator(self):
        rows = [judgement(1), judgement(2, eligible=False), judgement(3, level=2),
                judgement(4, excluded=True), judgement(5, grade=None, error="HTTPError")]
        result = quality.measure_quality(rows, scope="population", scope_description="fixture 모집단")
        supply = result["supply"]
        self.assertEqual(supply["profile_rows"], 5)
        self.assertEqual(supply["successful"], 4)
        self.assertEqual(supply["failed"], 1)
        self.assertEqual(supply["raw_lv1_ready_supply"], quality.ratio(2, 5))
        self.assertEqual(supply["freshness_eligible_supply"], quality.ratio(1, 5))
        self.assertEqual(supply["excluded"], 1)
        self.assertEqual(result["scope"]["kind"], "population")
        self.assertFalse(result["audit"]["human_audit_performed"])
        self.assertEqual(result["repeat"]["status"], "measurement_unavailable")

    def test_old_unknown_and_malformed_profiles_cannot_enter_current_totals(self):
        missing = judgement(3)
        del missing["criteria_version"]
        rows = [judgement(1), judgement(2, model="gpt-5.6-luna"), missing,
                judgement(4, reasoning_effort="low"), judgement(5, criteria_version=True),
                judgement(6, criteria_version=1)]
        result = quality.measure_quality(rows)
        self.assertEqual(result["input"]["excluded_rows"], 5)
        self.assertEqual(result["supply"]["profile_rows"], 1)
        self.assertEqual(result["policy"], quality.current_profile())

    def test_cumulative_rows_do_not_claim_model_attempt_count(self):
        rows = [judgement(1, graded_at="2026-10-20T02:00:00Z"),
                judgement(2, graded_at="2026-10-21T02:00:00Z"),
                judgement(3, grade=None, error="HTTPError", graded_at="2026-10-21T02:00:00Z")]
        supply = quality.measure_quality(rows)["supply"]
        self.assertEqual(supply["profile_rows"], 3)
        self.assertNotIn("attempted", supply)
        self.assertEqual(supply["limitation"],
                         "may_include_reused_judgements_row_count_is_not_model_call_count")
        self.assertEqual(supply["raw_lv1_ready_supply"], quality.ratio(2, 3))

    def test_only_historical_input_is_unavailable_instead_of_zero_quality(self):
        result = quality.measure_quality([judgement(1, criteria_version=1)])
        self.assertEqual(result["supply"]["status"], "measurement_unavailable")
        self.assertIsNone(result["supply"]["raw_lv1_ready_supply"]["rate"])

    def test_freshness_without_timezone_checked_at_is_unverified(self):
        rows = [judgement(1, freshness=None), judgement(2, freshness={"eligible": True}),
                judgement(3, freshness={"eligible": True, "checked_at": "2026-10-21"}),
                judgement(4, freshness={"eligible": 1, "checked_at": "2026-10-21T02:00:00Z"})]
        supply = quality.measure_quality(rows)["supply"]
        self.assertEqual(supply["raw_lv1_ready_supply"]["numerator"], 4)
        self.assertEqual(supply["freshness_eligible_supply"]["numerator"], 0)
        self.assertEqual(supply["freshness_eligible_supply"]["status"], "partial")
        self.assertEqual(supply["raw_candidate_freshness"]["unverified"], 4)

    def test_duplicate_keys_are_rejected_with_repository_case_normalization(self):
        with self.assertRaisesRegex(ValueError, "중복"):
            quality.measure_quality([judgement(1), judgement(1, repo="example/project")])

    def test_invalid_success_and_ambiguous_failure_are_rejected(self):
        invalid = judgement(1)
        invalid["grade"]["difficulty"] = True
        for row in (invalid, judgement(1, grade=None), judgement(1, error="HTTPError")):
            with self.subTest(row=row), self.assertRaises(ValueError):
                quality.measure_quality([row])

    def test_v2_mapping_drift_is_observed_without_erasing_judgement(self):
        row = judgement(1)
        row["grade"]["readiness"] = "needs_info"
        supply = quality.measure_quality([row])["supply"]
        self.assertEqual(supply["v2_readiness_mapping_violations"], 1)
        self.assertEqual(supply["successful"], 1)
        self.assertEqual(supply["raw_lv1_ready_supply"]["numerator"], 0)


class RepeatTests(unittest.TestCase):
    def test_repeat_uses_only_identical_successful_current_inputs(self):
        primary = [judgement(i) for i in range(1, 8)]
        repeat = deepcopy(primary)
        repeat[1]["body"] = "바뀐 본문"
        repeat[2]["grade"] = None
        repeat[2]["error"] = "TimeoutError"
        repeat[3]["model"] = "historical-model"
        del repeat[4]["title"]
        repeat[5]["grade"]["difficulty"] = 2
        repeat[5]["grade"]["readiness"] = "needs_info"
        repeat[6]["grade"]["exclude"] = True
        repeat[6]["grade"]["exclude_reason"] = "중복"
        result = quality.measure_quality(primary, repeat_rows=repeat)["repeat"]
        self.assertEqual(result["comparable"], 3)
        self.assertEqual(result["skipped"], {"changed_title_or_body": 1, "failed_judgement": 1,
                                             "input_text_unverified": 1})
        self.assertEqual(result["input"]["excluded_rows"], 1)
        self.assertEqual(result["agreement"]["difficulty"], quality.ratio(2, 3))
        self.assertEqual(result["agreement"]["readiness"], quality.ratio(2, 3))
        self.assertEqual(result["agreement"]["exclude"], quality.ratio(2, 3))
        self.assertEqual(result["agreement"]["all_three_fields"], quality.ratio(1, 3))
        self.assertEqual(result["agreement"]["raw_recommendation"], quality.ratio(1, 3))

    def test_unchanged_recommendation_is_distinct_from_fine_grained_labels(self):
        first, second = judgement(1, level=2), judgement(1, level=3)
        result = quality.measure_quality([first], repeat_rows=[second])["repeat"]
        self.assertEqual(result["agreement"]["difficulty"]["rate"], 0)
        self.assertEqual(result["agreement"]["raw_recommendation"]["rate"], 1)

    def test_changed_freshness_does_not_claim_model_instability(self):
        result = quality.measure_quality([judgement(1)], repeat_rows=[judgement(1, eligible=False)])
        self.assertEqual(result["repeat"]["agreement"]["raw_recommendation"]["rate"], 1)

    def test_no_comparable_successes_is_unavailable(self):
        result = quality.measure_quality([judgement(1)], repeat_rows=[judgement(2)])
        self.assertEqual(result["repeat"]["status"], "measurement_unavailable")


class AuditTests(unittest.TestCase):
    def test_candidate_only_audit_reports_precision_but_never_recall_or_zero_misses(self):
        rows = [judgement(1), judgement(2), judgement(3), judgement(4, level=2)]
        labels = [label(1, "바로 추천 가능"), label(2, "conditional"), label(3, "incorrect")]
        result = quality.measure_quality(rows, audit_labels=labels)["audit"]
        self.assertEqual(result["strict_precision"], quality.ratio(1, 3))
        self.assertEqual(result["conditional_inclusive_precision"], quality.ratio(2, 3))
        self.assertEqual(result["coverage_of_current_input"], quality.ratio(3, 4))
        self.assertEqual(result["strict_recall"]["status"], "measurement_unavailable")
        self.assertEqual(result["missed_plausible_in_audited_rows"]["status"], "measurement_unavailable")

    def test_complete_audit_recall_and_misses_use_audited_human_positive_denominator(self):
        rows = [judgement(1), judgement(2, level=2), judgement(3, level=3)]
        result = quality.measure_quality(rows, audit_labels=[label(1), label(2), label(3, "incorrect")],
                                         audit_scope="all-input")["audit"]
        self.assertEqual(result["strict_recall"], quality.ratio(1, 2))
        self.assertEqual(result["missed_plausible_in_audited_rows"], quality.ratio(1, 2))
        self.assertEqual(result["strict_precision"], quality.ratio(1, 1))

    def test_incomplete_or_failed_full_audit_cannot_claim_full_recall(self):
        for rows in ([judgement(1), judgement(2, level=2), judgement(3, level=2)],
                     [judgement(1), judgement(2, level=2), judgement(3, grade=None, error="HTTPError")]):
            result = quality.measure_quality(rows, audit_labels=[label(1), label(2)],
                                             audit_scope="all-input")["audit"]
            self.assertEqual(result["strict_recall"]["status"], "measurement_unavailable")

    def test_selected_mixed_audit_reports_observed_misses_but_no_population_recall(self):
        result = quality.measure_quality([judgement(1), judgement(2, level=2), judgement(3)],
                                         audit_labels=[label(1), label(2)])["audit"]
        self.assertEqual(result["missed_plausible_in_audited_rows"], quality.ratio(1, 2))
        self.assertEqual(result["strict_recall"]["status"], "measurement_unavailable")

    def test_stale_unmatched_failed_and_changed_content_labels_do_not_enter_precision(self):
        labels = [label(1), label(2), label(3), label(4, body="예전 본문"), label(99)]
        rows = [judgement(1), judgement(2, criteria_version=1),
                judgement(3, grade=None, error="HTTPError"), judgement(4)]
        result = quality.measure_quality(rows, audit_labels=labels)["audit"]
        self.assertEqual(result["strict_precision"], quality.ratio(1, 1))
        self.assertEqual(result["skipped"], {"not_in_current_input": 2, "failed_judgement": 1,
                                            "changed_title_or_body": 1})
        self.assertEqual(result["labels_with_verified_title_and_body"], 0)

    def test_freshness_precision_uses_only_audited_freshness_eligible_candidates(self):
        result = quality.measure_quality([judgement(1), judgement(2, eligible=False), judgement(3)],
                                         audit_labels=[label(1), label(2, "incorrect")])["audit"]
        self.assertEqual(result["strict_precision"], quality.ratio(1, 2))
        self.assertEqual(result["freshness_eligible_strict_precision"], quality.ratio(1, 1))

    def test_unknown_verdict_and_duplicate_labels_are_rejected(self):
        for labels in ([label(1, "unknown")], [label(1), label(1)], [label(1, title=None, body=None)]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                quality.measure_quality([judgement(1)], audit_labels=labels)

    def test_existing_committed_audit_format_is_read_without_modification(self):
        source = Path(__file__).with_name("docs") / "일반-모집단-추천-감사.json"
        before = source.read_bytes()
        labels = quality.read_audit(source)
        self.assertTrue(labels)
        self.assertTrue(all(label["verdict"] in quality.VERDICTS for label in labels))
        self.assertEqual(source.read_bytes(), before)


class CliTests(unittest.TestCase):
    def test_cli_writes_json_offline_and_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "grades.jsonl", Path(directory) / "quality.json"
            source.write_text(json.dumps(judgement(1), ensure_ascii=False) + "\n", encoding="utf-8")
            before = source.read_bytes()
            with (patch("subprocess.run", side_effect=AssertionError("오프라인만 허용")),
                  patch("vertex.generate_json", side_effect=AssertionError("유료 호출 금지"))):
                self.assertEqual(quality.main(["--input", str(source), "--output", str(output),
                                               "--scope", "sample", "--scope-description", "fixture"]), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["supply"]["raw_lv1_ready_supply"]["rate"], 1)
            self.assertEqual(result["scope"]["description"], "fixture")
            self.assertEqual(source.read_bytes(), before)

    def test_cli_rejects_source_overwrite_and_identical_repeat_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "grades.jsonl"
            source.write_text(json.dumps(judgement(1)) + "\n", encoding="utf-8")
            before = source.read_bytes()
            for argument in ("--output", "--repeat"):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    quality.main(["--input", str(source), argument, str(source)])
                self.assertEqual(error.exception.code, 2)
            self.assertEqual(source.read_bytes(), before)

    def test_cli_rejects_malformed_input_without_overwriting_prior_result_or_echoing_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "grades.jsonl", Path(directory) / "quality.json"
            source.write_text("PRIVATE_FIXTURE_CONTENT", encoding="utf-8")
            output.write_text("previous result", encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors), self.assertRaises(SystemExit):
                quality.main(["--input", str(source), "--output", str(output)])
            self.assertNotIn("PRIVATE_FIXTURE_CONTENT", errors.getvalue())
            self.assertEqual(output.read_text(encoding="utf-8"), "previous result")

    def test_cli_stdout_is_json_and_empty_input_is_explicitly_unmeasured(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "grades.jsonl"
            source.write_text("", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                quality.main(["--input", str(source)])
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["supply"]["status"], "measurement_unavailable")
            self.assertEqual(result["scope"]["kind"], "unspecified")


if __name__ == "__main__":
    unittest.main()
