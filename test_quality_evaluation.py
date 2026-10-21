"""유료 API 없이 평가 범위, 재사용 차단과 실패 보존을 검사한다."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quality_evaluation as evaluation
import radar


def issue(number, repo="test/repo"):
    return {"repo": repo, "number": number, "title": "fixture", "body": "fixture body",
            "created_at": "2026-10-20T00:00:00Z"}


class EvaluationTests(unittest.TestCase):
    def test_uniform_sample_is_reproducible_independent_of_pool_order(self):
        rows = [issue(i, f"test/repo{i % 5}") for i in range(1, 101)]
        first = evaluation.select_sample(rows, 52)
        self.assertEqual(first, evaluation.select_sample(list(reversed(rows)), 52))
        self.assertEqual(30, len(first))
        self.assertNotEqual(first, evaluation.select_sample(rows, 53))

    def test_small_pool_uses_every_issue_and_existing_repo_cap_is_not_bypassed(self):
        rows = [issue(i) for i in range(1, 5)]
        self.assertEqual(set(map(radar.issue_key, rows)),
                         set(map(radar.issue_key, evaluation.select_sample(rows, 1))))
        with self.assertRaises(ValueError):
            evaluation.select_sample([issue(i) for i in range(1, 31)], 1)

    def test_collect_uses_original_exclusions_without_image_vertex_calls(self):
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        source = {"number": 1, "title": "fixture", "body": "body", "html_url": "https://github.com/test/a/issues/1",
                  "updated_at": "2026-10-20T00:00:00Z", "created_at": "2026-10-20T00:00:00Z"}
        pages = [[source, {**source, "number": 2, "pull_request": {}},
                  {**source, "number": 3, "assignee": {}},
                  {**source, "number": 4, "user": {"type": "Bot"}},
                  {**source, "number": 5, "updated_at": "2026-10-22T00:00:00Z"}]]
        with tempfile.TemporaryDirectory() as folder:
            repos = Path(folder) / "repos.txt"
            repos.write_text("\n".join(f"test/repo{i}" for i in range(30)))
            with patch.object(radar, "gh_json", return_value=pages) as github, \
                    patch.object(radar.vertex, "generate_json", side_effect=AssertionError("paid")):
                rows, collection = evaluation.collect_pool(repos, now)
        self.assertEqual(30, len(rows))
        self.assertEqual(30, github.call_count)
        self.assertIn("state=open", github.call_args.args[0])
        self.assertEqual(30, collection["counts"]["PR"])
        self.assertEqual(30, collection["counts"]["담당자 있음"])
        self.assertEqual(30, collection["counts"]["봇 작성"])
        self.assertTrue(all(row["repository_image"] == "" for row in rows))

    def test_independent_passes_have_empty_reuse_and_failure_stays_in_denominator(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "new"
            calls = []

            def grade(args):
                self.assertFalse(args.all_issues)
                self.assertFalse(args.output.exists())
                self.assertEqual([], radar.read_jsonl(args.reuse))
                calls.append(args)
                evaluation.save_rows(args.output, [
                    {**issue(1), **evaluation.APPROVED_PROFILE, "grade": None, "error": "RuntimeError"}])
                return 1

            with patch.object(evaluation, "source_hashes", return_value={"fixture": "hash"}), \
                    patch.object(evaluation, "collect_pool", return_value=([issue(1)], {})), \
                    patch.object(radar, "grade", side_effect=grade):
                self.assertEqual(0, evaluation.evaluate(destination, 1))
                with self.assertRaises(FileExistsError):
                    evaluation.evaluate(destination, 1)
            manifest = json.loads((destination / "manifest.json").read_text())
            result = json.loads((destination / "quality.json").read_text())
            self.assertEqual(2, len(calls))
            self.assertNotEqual(calls[0].output, calls[1].output)
            self.assertEqual(1, result["supply"]["failed"])
            self.assertEqual(1, result["supply"]["profile_rows"])
            self.assertFalse(result["audit"]["human_audit_performed"])
            self.assertEqual("completed", manifest["status"])

    def test_collection_failure_does_not_request_paid_judgement(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(evaluation, "source_hashes", return_value={}), \
                patch.object(evaluation, "collect_pool", side_effect=RuntimeError("secret text")), \
                patch.object(radar, "grade") as grade:
            destination = Path(folder) / "new"
            with self.assertRaises(RuntimeError):
                evaluation.evaluate(destination, 1)
            grade.assert_not_called()
            text = (destination / "manifest.json").read_text()
            self.assertNotIn("secret text", text)
            self.assertEqual("interrupted_do_not_rerun", json.loads(text)["status"])

    def test_changed_source_stops_before_paid_calls(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(evaluation, "source_hashes", side_effect=[{"a": "1"}, {"a": "2"}]), \
                patch.object(evaluation, "collect_pool", return_value=([issue(1)], {})), \
                patch.object(radar, "grade") as grade:
            with self.assertRaises(ValueError):
                evaluation.evaluate(Path(folder) / "new", 1)
            grade.assert_not_called()

    def test_unapproved_profile_is_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(evaluation.quality_measurement, "current_profile", return_value={"model": "other"}):
            destination = Path(folder) / "new"
            with self.assertRaises(ValueError):
                evaluation.evaluate(destination, 1)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
