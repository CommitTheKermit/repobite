"""네트워크 없이 실행: python3 test_radar.py"""

import argparse
from collections import Counter
from contextlib import redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import threading
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
    html = '<p>소개 <img src="docs/banner.png" alt="제품 화면"></p><img src="https://img.example/badge.svg" alt="build">'
    candidates = radar.readme_image_candidates("a/b", html)
    assert candidates[0]["url"] == "https://raw.githubusercontent.com/a/b/HEAD/docs/banner.png"
    with (patch.object(radar, "gh_text", return_value=html),
          patch.object(radar.vertex, "generate_json", return_value={"selected_index": 1})):
        assert radar.repository_image("a/b") == candidates[0]["url"]
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

    def fake_vertex(prompt, schema, model):
        assert model == radar.MODEL
        assert schema == radar.SCHEMA
        assert "HUMAN_SECRET" not in prompt
        assert "실제 구현량, 기술 분야, 저장소 규모는 난이도에 반영하지 않는다" in prompt
        assert "40자 이내" in prompt
        return GOOD

    with patch.object(radar.vertex, "generate_json", side_effect=fake_vertex):
        assert radar.grade_issue({**issue, "verdict": "HUMAN_SECRET"}) == GOOD
    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / "issues.jsonl", Path(directory) / "grades.jsonl"
        source.write_text(json.dumps(issue) + "\n" + json.dumps({**issue, "number": 2}) + "\n")
        args = argparse.Namespace(input=source, output=target, model=radar.MODEL)

        def fake_grade(row, model):
            if row["number"] == 2:
                raise ValueError("invalid model response")
            return GOOD

        with (patch.object(radar, "grade_issue", side_effect=fake_grade),
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 1
        rows = radar.read_jsonl(target)
        assert rows[0]["grade"] == GOOD and rows[1]["grade"] is None
        assert rows[0]["criteria_version"] == radar.CRITERIA_VERSION
        assert radar.aggregate(rows)["failed"] == 1
        with (patch.object(radar, "grade_issue", return_value=GOOD) as model,
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 0
        assert model.call_count == 1
        assert len(radar.read_jsonl(target)) == 2
        before = target.read_bytes()
        try:
            with radar.atomic_output(target) as stream:
                stream.write("incomplete")
                raise RuntimeError()
        except RuntimeError:
            pass
        assert target.read_bytes() == before
        assert not list(target.parent.glob("*.tmp"))
        args.output = source
        rejects(radar.grade, args)
        rejects(radar.unique_issues, [issue, issue])
        source.write_text("{broken json\n")
        rejects(radar.read_jsonl, source)


def test_grading_parallelism():
    barrier = threading.Barrier(16, timeout=5)
    lock = threading.Lock()
    active = peak = 0

    def fake_grade(row, model):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait()
            return GOOD
        finally:
            with lock:
                active -= 1

    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / "issues.jsonl", Path(directory) / "grades.jsonl"
        issue = radar.normalize_issue("a/b", ISSUE)
        source.write_text("".join(json.dumps({**issue, "repo": "a/b" if n <= 16 else "c/d", "number": n}) + "\n"
                                  for n in range(1, 33)))
        args = argparse.Namespace(input=source, output=target, model=radar.MODEL)
        with (patch.object(radar, "grade_issue", side_effect=fake_grade),
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 0
        assert peak == 16
        assert sorted(row["number"] for row in radar.read_jsonl(target)) == list(range(1, 33))


def test_grading_limits():
    issue = radar.normalize_issue("a/b", ISSUE)
    issues = [{**issue, "repo": f"owner/repo{repo}", "number": n,
               "created_at": f"2026-09-{n:02d}T00:00:00Z"}
              for repo in range(6) for n in range(1, 31)]
    selected = radar.select_for_grading(issues)
    assert len(selected) == 100
    assert [row["repo"] for row in selected[:6]] == [f"owner/repo{n}" for n in range(6)]
    assert all(row["number"] == 30 for row in selected[:6])
    assert sorted(Counter(row["repo"] for row in selected).values()) == [16, 16, 17, 17, 17, 17]
    assert [row["number"] for row in radar.select_for_grading(issues[:30])] == list(range(30, 10, -1))
    assert len(radar.select_for_grading(issues[:150])) == 100
    uneven = radar.select_for_grading(issues[:2] + issues[30:60])
    assert Counter(row["repo"] for row in uneven) == {"owner/repo0": 2, "owner/repo1": 20}
    assert [row["repo"] for row in uneven[:4]] == ["owner/repo0", "owner/repo1"] * 2
    assert radar.select_for_grading([]) == []
    for stamp in (None, "bad", "2026-09-10T00:00:00"):
        rejects(radar.select_for_grading, [{**issue, "created_at": stamp}])
    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / "issues.jsonl", Path(directory) / "grades.jsonl"
        source.write_text("".join(json.dumps(row) + "\n" for row in issues))
        original = source.read_bytes()
        args = argparse.Namespace(input=source, output=target, model=radar.MODEL)
        with (patch.object(radar, "grade_issue", side_effect=RuntimeError("failure")) as model,
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 1
        assert model.call_count == 100  # 실패도 상한에 포함하며 다른 이슈로 보충하지 않는다.
        assert len(radar.read_jsonl(target)) == 100
        assert source.read_bytes() == original
        args.all_issues = True
        with (patch.object(radar, "grade_issue", return_value=GOOD) as model,
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 0
        assert model.call_count == 180
        assert radar.read_jsonl(target)[-1]["number"] == 30
        assert len(radar.read_jsonl(target)) == 180
        assert source.read_bytes() == original
        args.all_issues = False
        with (patch.object(radar, "grade_issue", return_value=GOOD) as model,
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 0
        assert model.call_count == 0
        assert len(radar.read_jsonl(target)) == 180
        changed = [{**row, "body": "changed"} if row["number"] == 1 and row["repo"] == "owner/repo0" else row
                   for row in issues]
        source.write_text("".join(json.dumps(row) + "\n" for row in changed))
        with (patch.object(radar, "grade_issue", return_value=GOOD) as model,
              patch.object(radar.freshness, "apply_freshness", side_effect=lambda rows: rows)):
            assert radar.grade(args) == 0
        assert model.call_count == 1
        assert len(radar.read_jsonl(target)) == 180


def test_report():
    rows = [{"repo": "a/b", "number": 1, "grade": GOOD,
             "freshness": {"eligible": True, "reason": "확인 완료", "checked_at": "now"}},
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
    fixture = json.loads((radar.ROOT / "fixtures/sample30.json").read_text(encoding="utf-8"))
    assert len(fixture) == 30
    assert Counter(row["verdict"] for row in fixture) == {"적합": 5, "조건부": 9, "부적합": 16}


def test_candidates_and_batch():
    def row(repo, number, eligible=True, grade=GOOD):
        return {"repo": repo, "number": number, "grade": grade,
                "freshness": {"eligible": eligible}}

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "grades.jsonl"
        target = Path(directory) / "candidates.jsonl"
        existing = row("a/b", 1)
        target.write_text(json.dumps(existing) + "\n")
        rows = ([row("a/b", number) for number in range(1, 8)]
                + [row("c/d", 1), row("c/d", 2, eligible=False),
                   row("e/f", 1, grade={**GOOD, "difficulty": 2})])
        source.write_text("".join(json.dumps(item) + "\n" for item in rows))
        args = argparse.Namespace(input=source, output=target)
        assert radar.candidates(args) == 0
        saved = radar.read_jsonl(target)
        assert [item["number"] for item in saved if item["repo"] == "a/b"] == [1, 2, 3, 4, 5, 6]
        assert Counter(item["repo"] for item in saved) == {"a/b": 6, "c/d": 1}
        assert radar.candidates(args) == 0
        saved = radar.read_jsonl(target)
        assert [item["number"] for item in saved if item["repo"] == "a/b"] == list(range(1, 8))
        assert radar.candidates(args) == 0
        assert radar.read_jsonl(target) == saved
        args.output = source
        rejects(radar.candidates, args)

    args = argparse.Namespace(repos=Path("repos.txt"), since="24h",
                              issues=Path("issues.jsonl"), grades=Path("grades.jsonl"),
                              candidates=Path("candidates.jsonl"), model=radar.MODEL)
    with (patch.object(radar, "collect", return_value=0) as collect,
          patch.object(radar, "grade", return_value=0) as grade,
          patch.object(radar, "candidates", return_value=0) as save):
        assert radar.batch(args) == 0
        assert collect.call_count == grade.call_count == save.call_count == 1
    with (patch.object(radar, "collect", return_value=1),
          patch.object(radar, "grade") as grade,
          patch.object(radar, "candidates") as save):
        assert radar.batch(args) == 1
        grade.assert_not_called()
        save.assert_not_called()
    with (patch.object(radar, "collect", return_value=0),
          patch.object(radar, "grade", return_value=1),
          patch.object(radar, "candidates") as save):
        assert radar.batch(args) == 1
        save.assert_not_called()
    args.candidates = args.issues
    rejects(radar.batch, args)


if __name__ == "__main__":
    with redirect_stderr(io.StringIO()):
        test_filters_and_collection()
        test_schema_and_grading()
        test_grading_parallelism()
        test_grading_limits()
        test_report()
        test_candidates_and_batch()
    print("통과: 수집·판정·후보·배치·원자적 저장·리포트 집계")
