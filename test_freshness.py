#!/usr/bin/env python3

import json
from types import SimpleNamespace
import unittest

import freshness


def row(number, grade=None, error=None):
    value = {"repo": "owner/project", "number": number, "grade": grade}
    if error:
        value["error"] = error
    return value


CANDIDATE = {"exclude": False, "difficulty": 1, "readiness": "ready"}


class FreshnessTest(unittest.TestCase):
    def test_only_candidates_are_checked_and_each_blocker_is_reported(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            data = {
                "i0": {"issue": {"state": "OPEN", "assignees": {"totalCount": 0},
                                   "closedByPullRequestsReferences": {"totalCount": 0}}},
                "i1": {"issue": {"state": "CLOSED", "assignees": {"totalCount": 0},
                                   "closedByPullRequestsReferences": {"totalCount": 0}}},
                "i2": {"issue": {"state": "OPEN", "assignees": {"totalCount": 1},
                                   "closedByPullRequestsReferences": {"totalCount": 0}}},
                "i3": {"issue": {"state": "OPEN", "assignees": {"totalCount": 0},
                                   "closedByPullRequestsReferences": {"totalCount": 1}}},
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps({"data": data}))

        rows = [row(number, dict(CANDIDATE)) for number in range(1, 5)]
        rows += [row(5, {**CANDIDATE, "difficulty": 2}), row(6, None, "실패")]
        result = freshness.apply_freshness(rows, run=run, checked_at="2026-09-11T00:00:00Z")

        self.assertEqual(1, len(calls))
        self.assertIn("closedByPullRequestsReferences", calls[0][0][6])
        self.assertEqual([True, False, False, False],
                         [item["freshness"]["eligible"] for item in result[:4]])
        self.assertEqual(["확인 완료", "이슈 닫힘", "담당자 있음", "연결된 열린 PR 있음"],
                         [item["freshness"]["reason"] for item in result[:4]])
        self.assertNotIn("freshness", result[4])
        self.assertNotIn("freshness", result[5])

    def test_graphql_error_never_marks_candidate_eligible(self):
        failed = lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="")
        result = freshness.apply_freshness(
            [row(1, dict(CANDIDATE))], run=failed, checked_at="2026-09-11T00:00:00Z")
        self.assertEqual({"eligible": False, "reason": "최신 상태 확인 실패",
                          "checked_at": "2026-09-11T00:00:00Z"}, result[0]["freshness"])


if __name__ == "__main__":
    unittest.main()
