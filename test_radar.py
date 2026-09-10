"""네트워크 없이 실행: python3 test_radar.py"""

import argparse
from collections import Counter
from contextlib import redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import radar


GOOD = {"difficulty": 1, "readiness": "ready", "reason": "한 줄 수정 근거",
        "exclude": False, "exclude_reason": ""}
ISSUE = {"number": 1, "title": "제목", "body": None, "html_url": "https://github.com/a/b/issues/1",
         "created_at": "2026-09-10T00:00:00Z", "labels": [{"name": "bug"}],
         "user": {"login": "person", "type": "User"}, "assignee": None}


def rejects(function, *args):
    try:
        function(*args)
    except ValueError:
        return
    raise AssertionError("잘못된 입력이 통과했습니다")


def test_filters_and_collection():
    assert radar.exclusion_reason(ISSUE) == ""
    for changes in ({"pull_request": {}}, {"pull_request": None}, {"assignee": {}},
                    {"assignees": [{"login": "owner"}]}, {"user": {"type": "Bot"}},
                    {"user": {"type": "User", "login": "ci[bot]"}}):
        assert radar.exclusion_reason({**ISSUE, **changes})
    assert radar.normalize_issue("a/b", ISSUE)["body"] == ""
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    assert radar.since_timestamp("7d", now) == "2026-09-03T00:00:00Z"
    assert radar.since_timestamp("24h", now) == "2026-09-09T00:00:00Z"
    assert radar.since_timestamp("1w", now) == radar.since_timestamp("7d", now)
    for value in ("0d", "-1d", "7", "1.5d", "x", "999999999999w"):
        rejects(radar.since_timestamp, value)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        repos, output = root / "repos.txt", root / "issues.jsonl"
        repos.write_text("# comment\na/b\na/b\n")
        args = argparse.Namespace(sample=None, repos=repos, since="7d", output=output)
        pages = [[ISSUE, {**ISSUE, "number": 2, "pull_request": {}}],
                 [{**ISSUE, "number": 3}]]
        with patch.object(radar, "gh_json", return_value=pages) as api:
            assert radar.collect(args) == 0
            endpoint, *options = api.call_args.args
            assert endpoint.startswith("repos/a/b/issues?state=open&since=")
            assert options == ["--paginate", "--slurp"]
            assert api.call_count == 1
        rows = radar.read_jsonl(output)
        assert [row["number"] for row in rows] == [1, 3]
        assert rows[0]["labels"] == ["bug"]
        before = output.read_bytes()
        with patch.object(radar, "gh_json", side_effect=RuntimeError("API failure")):
            try:
                radar.collect(args)
            except RuntimeError:
                pass
            else:
                raise AssertionError("수집 오류를 숨겼습니다")
        assert output.read_bytes() == before
        sample = root / "sample.json"
        sample.write_text(json.dumps([{"repo": "a/b", "number": n} for n in (1, 2)]))
        args.sample = sample
        with patch.object(radar, "gh_json", side_effect=[{**ISSUE, "state": "closed"}, RuntimeError()]):
            assert radar.collect(args) == 1
        assert len(radar.read_jsonl(output)) == 1


def test_schema_and_grading():
    assert radar.validate_grade(GOOD) == GOOD
    for field in GOOD:
        rejects(radar.validate_grade, {key: value for key, value in GOOD.items() if key != field})
    for changes in ({"difficulty": True}, {"difficulty": 1.0}, {"difficulty": 4},
                    {"readiness": "later"}, {"readiness": []}, {"reason": " "},
                    {"exclude": 0}, {"exclude": True}, {"exclude_reason": "있음"}, {"extra": 1}):
        rejects(radar.validate_grade, {**GOOD, **changes})
    rejects(radar.validate_grade, [])
    issue = radar.normalize_issue("a/b", ISSUE)

    def fake_codex(command, **kwargs):
        assert command[:2] == ["codex", "exec"]
        assert command[command.index("-m") + 1] == "gpt-5.6-luna"
        assert command[command.index("-s") + 1] == "read-only"
        assert "--ephemeral" in command and "--ignore-user-config" in command
        assert "features.shell_tool=false" in command
        assert 'web_search="disabled"' in command
        assert kwargs["timeout"] == 300 and command[-1] == "-"
        assert "HUMAN_SECRET" not in kwargs["input"]
        Path(command[command.index("-o") + 1]).write_text(json.dumps(GOOD))
        return subprocess.CompletedProcess(command, 0)

    with patch.object(radar.subprocess, "run", side_effect=fake_codex):
        assert radar.grade_issue({**issue, "verdict": "HUMAN_SECRET"}) == GOOD
    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / "issues.jsonl", Path(directory) / "grades.jsonl"
        source.write_text(json.dumps(issue) + "\n" + json.dumps({**issue, "number": 2}) + "\n")
        args = argparse.Namespace(input=source, output=target, model="gpt-5.6-luna")

        def fake_grade(row, model):
            if row["number"] == 2:
                raise ValueError("invalid model response")
            return GOOD

        with patch.object(radar, "grade_issue", side_effect=fake_grade):
            assert radar.grade(args) == 1
        rows = radar.read_jsonl(target)
        assert rows[0]["grade"] == GOOD and rows[1]["grade"] is None
        assert radar.aggregate(rows)["failed"] == 1
        before = target.read_bytes()
        try:
            with radar.atomic_output(target) as stream:
                stream.write("incomplete")
                raise RuntimeError()
        except RuntimeError:
            pass
        assert target.read_bytes() == before
        args.output = source
        rejects(radar.grade, args)
        rejects(radar.unique_issues, [issue, issue])
        source.write_text("{broken json\n")
        rejects(radar.read_jsonl, source)


def test_report():
    rows = [{"repo": "a/b", "number": 1, "grade": GOOD},
            {"repo": "a/b", "number": 2, "grade": {**GOOD, "difficulty": 3}},
            {"repo": "c/d", "number": 3, "grade": {**GOOD, "readiness": "undecided"}},
            {"repo": "c/d", "number": 4, "grade": {**GOOD, "exclude": True, "exclude_reason": "원인 미상"}},
            {"repo": "e/f", "number": 5, "grade": None, "error": "TimeoutExpired"}]
    samples = [{"repo": row["repo"], "number": row["number"],
                "verdict": "부적합" if row["number"] in (2, 4) else "조건부"} for row in rows]
    stats = radar.aggregate(rows, samples)
    assert (stats["total"], stats["valid"], stats["failed"], stats["excluded"], stats["eligible"], stats["target"]) == (5, 4, 1, 1, 3, 1)
    assert stats["cross"] == Counter({(1, "ready"): 1, (3, "ready"): 1, (1, "undecided"): 1})
    assert sum(stats["cross"].values()) == stats["eligible"]
    assert stats["repos"] == Counter({"a/b": 2, "c/d": 2, "e/f": 1})
    assert stats["matched"] == 4 and len(stats["confusion"]) == 4
    output = radar.render_report(stats)
    assert "1/4 (25.0%)" in output and "1/3 (33.3%)" in output
    assert "2/4 (50.0%)" in output and "표본 매칭: 4/5" in output
    assert "5/5 (100.0%)" in output
    assert "측정 불가" in radar.render_report(radar.aggregate([], samples))
    rejects(radar.aggregate, [{"repo": "a/b", "number": 1}])
    fixture = json.loads((radar.ROOT / "fixtures/sample30.json").read_text())
    assert len(fixture) == 30
    assert Counter(row["verdict"] for row in fixture) == {"적합": 5, "조건부": 9, "부적합": 16}


if __name__ == "__main__":
    with redirect_stderr(io.StringIO()):
        test_filters_and_collection()
        test_schema_and_grading()
        test_report()
    print("통과: 제외 필터·페이지 수집·스키마·판정 실패 보존·원자적 저장·리포트 집계")
