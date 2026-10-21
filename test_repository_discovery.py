"""실행: python3.14 test_repository_discovery.py. GitHub 호출은 mock으로 대체한다."""

from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import repository_discovery as discovery

NOW = datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)


def sample(repo, repo_id, stars, when=NOW):
    return {"repo": repo, "id": repo_id, "stars": stars, "observed_at": when.isoformat(),
            "source": "https://api.github.com/repos/" + repo}


def api_repo(repo, repo_id, stars, **changes):
    return {"full_name": repo, "id": repo_id, "stargazers_count": stars,
            "private": False, "archived": False, "disabled": False,
            "has_issues": True, **changes}


def proposals(rows, past=(), limit=4, tolerance=timedelta(hours=1)):
    return discovery.select_proposals(rows, past, limit, lookback=timedelta(days=7), tolerance=tolerance)


def rejects(callback, *args, **kwargs):
    try:
        callback(*args, **kwargs)
    except (ValueError, TypeError, RuntimeError):
        return
    raise AssertionError("잘못된 입력이나 실패를 허용했습니다")


def test_missing_history_never_fills_trend_with_famous():
    rows = [sample("owner/high", 1, 9000), sample("owner/low", 2, 8000),
            sample("owner/extra", 3, 7000)]
    result = proposals(rows)
    assert result["quota"] == {"trend": 2, "famous": 2}
    assert result["trend"] == {"status": "unmeasured", "items": [], "shortfall": 2}
    assert [row["repo"] for row in result["famous"]["items"]] == ["owner/high", "owner/low"]
    assert result["measurement"]["unmeasured_count"] == 3


def test_deltas_identity_quota_and_actual_period():
    old = NOW - timedelta(days=7)
    rows = [sample("owner/renamed", 1, 1000), sample("owner/famous", 2, 20000),
            sample("owner/flat", 3, 50000), sample("owner/rising", 4, 90),
            sample("owner/reused-name", 8, 800)]
    past = [sample("owner/old-name", 1, 500, old - timedelta(minutes=15)),
            sample("owner/famous", 2, 19999, old), sample("owner/flat", 3, 50000, old),
            sample("owner/rising", 4, 10, old), sample("owner/reused-name", 7, 1, old)]
    result = proposals(rows, past)
    assert [row["id"] for row in result["trend"]["items"]] == [1, 4]
    assert [row["id"] for row in result["famous"]["items"]] == [3, 2]
    first = result["trend"]["items"][0]
    assert first["net_star_delta"] == 500
    assert first["baseline"]["repo"] == "owner/old-name"
    assert first["period_seconds"] == 7 * 86400 + 900
    assert first["source"] == "https://api.github.com/repos/owner/renamed"
    assert result["measurement"]["unmeasured"] == [{"repo": "owner/reused-name", "id": 8,
        "status": "unmeasured", "reason": "no_comparable_observation"}]
    # 별 수가 높아도 감소 또는 정체한 저장소는 트렌드 빈자리를 채우지 않는다.
    falling = proposals([sample("owner/drop", 1, 9)], [sample("owner/drop", 1, 10, old)], limit=2)
    assert falling["trend"]["status"] == "insufficient"
    assert falling["trend"]["shortfall"] == 1


def test_time_window_requires_explicit_tolerance():
    current = [sample("owner/a", 1, 100)]
    old = NOW - timedelta(days=7)
    outside = [sample("owner/a", 1, 1, old - timedelta(hours=1, seconds=1))]
    assert proposals(current, outside)["trend"]["status"] == "unmeasured"
    exact = [sample("owner/a", 1, 80, old), sample("owner/a", 1, 20, old + timedelta(minutes=10))]
    assert proposals(current, exact, limit=2)["trend"]["items"][0]["net_star_delta"] == 20
    rejects(proposals, current, tolerance=timedelta(days=7))
    rejects(proposals, current, tolerance=timedelta(seconds=-1))
    for value in (0, -2, 1, 3, 4.5, True):
        rejects(proposals, current, limit=value)
    rejects(proposals, [current[0], current[0]])


def test_repository_state_and_api_evidence():
    for field, value in (("private", True), ("archived", True), ("disabled", True), ("has_issues", False)):
        row, reason = discovery.observation(api_repo("owner/a", 1, 100, **{field: value}), NOW.isoformat())
        assert row is None and reason
    missing = api_repo("owner/a", 1, 100)
    del missing["disabled"]
    rejects(discovery.observation, missing, NOW.isoformat())
    rejects(discovery.repo_name, "owner/a?token=secret")
    rejects(discovery.repo_name, "owner/..")
    rejects(discovery.observation, api_repo("owner/a", 1, -1), NOW.isoformat())
    rejects(discovery.observation, api_repo("owner/a", 1, 1), "2026-10-21T02:00:00")


def test_search_history_refresh_casefold_and_exclusion():
    calls = []
    old = sample("owner/old", 2, 1, NOW - timedelta(days=7))

    def github(endpoint):
        calls.append(endpoint)
        if endpoint.startswith("search/"):
            return {"items": [{"full_name": "Owner/Current"}, {"full_name": "owner/current"},
                              {"full_name": "owner/private"}], "incomplete_results": False, "total_count": 3}
        if endpoint.lower() == "repos/owner/current":
            return api_repo("Owner/Current", 1, 100)
        if endpoint == "repos/owner/private":
            return api_repo("owner/private", 3, 10000, private=True)
        assert endpoint == "repos/owner/old"
        return api_repo("owner/renamed", 2, 400)

    current, source = discovery.collect_observations([old], "language:Python", 100, gh=github, clock=lambda: NOW)
    assert len(current) == 2
    assert any(row["repo"] == "owner/renamed" for row in current)
    assert calls.count("repos/owner/current") == 1
    assert "q=language%3APython" in calls[0] and "sort=stars" in calls[0]
    assert source["excluded"] == {"private": 1}
    assert source["search_urls"][0].startswith("https://api.github.com/search/repositories?")
    assert source["prior_repository_count"] == 1


def test_search_pagination_uses_constant_page_size():
    calls = []

    def github(endpoint):
        calls.append(endpoint)
        if endpoint.startswith("search/"):
            start = (int(parse_qs(urlsplit(endpoint).query)["page"][0]) - 1) * 100
            return {"items": [{"full_name": f"owner/r{i}"} for i in range(start, start + 100)],
                    "incomplete_results": False, "total_count": 1000}
        number = int(endpoint.split("r")[-1])
        return api_repo("owner/r" + str(number), number + 1, 500 - number)

    current, source = discovery.collect_observations([], "stars:>=0", 150, gh=github, clock=lambda: NOW)
    assert len(current) == 150
    assert "per_page=100&page=1" in calls[0] and "per_page=100&page=2" in calls[1]
    assert source["search_rows_read"] == 150 and source["search_truncated"]


def test_persistence_error_preserves_previous_output_and_history():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        history, output = root / "history.jsonl", root / "proposal.jsonl"
        history.write_text(json.dumps({"version": 1, "observations": []}))
        output.write_text("previous proposal")
        original_history = history.read_bytes()
        options = dict(limit=2, tolerance_hours=1, history_path=history, output_path=output, clock=lambda: NOW)
        with patch.object(discovery.radar, "gh_json", side_effect=RuntimeError("API error")):
            rejects(discovery.run, **options)
        assert history.read_bytes() == original_history and output.read_text() == "previous proposal"
        # 검색과 첫 저장소 확인 이후의 API 실패도 부분 결과를 저장하지 않는다.
        with patch.object(discovery.radar, "gh_json", side_effect=[
                {"items": [{"full_name": "owner/a"}, {"full_name": "owner/b"}],
                 "incomplete_results": False, "total_count": 2},
                api_repo("owner/a", 1, 100), RuntimeError("second repository failed")]):
            rejects(discovery.run, **options)
        assert history.read_bytes() == original_history and output.read_text() == "previous proposal"
        incomplete = {"items": [], "incomplete_results": True, "total_count": 0}
        with patch.object(discovery.radar, "gh_json", return_value=incomplete):
            rejects(discovery.run, **options)
        assert history.read_bytes() == original_history and output.read_text() == "previous proposal"
        with patch.object(discovery.radar, "gh_json", return_value={"items": [{"full_name": "owner/a"}],
                "incomplete_results": False, "total_count": 1}) as gh:
            gh.side_effect = [gh.return_value, api_repo("owner/a", 1, 100)]
            result = discovery.run(**options)
        assert json.loads(output.read_text()) == result
        assert result["trend"]["status"] == "unmeasured"
        stored = discovery.read_history(history)
        assert stored == [sample("owner/a", 1, 100)]
        later = NOW + timedelta(days=7)
        with patch.object(discovery.radar, "gh_json", side_effect=[
                {"items": [{"full_name": "owner/a"}], "incomplete_results": False, "total_count": 1},
                api_repo("owner/a", 1, 120)]):
            second = discovery.run(**{**options, "clock": lambda: later})
        assert second["trend"]["items"][0]["net_star_delta"] == 20
        assert second["famous"]["shortfall"] == 1
        assert len(discovery.read_history(history)) == 2
        assert not list(root.glob("*.tmp"))
        # 잘못된 기록은 새 측정으로 덮어쓰지 않는다.
        history.write_text('{"version":1,"observations":[{}]}')
        previous = output.read_bytes()
        rejects(discovery.run, **options)
        assert output.read_bytes() == previous
        rejects(discovery.run, **{**options, "history_path": output})
        rejects(discovery.run, **{**options, "output_path": discovery.radar.ROOT / "repos.txt"})
        with patch.object(discovery, "run", side_effect=RuntimeError("sensitive detail")), redirect_stderr(io.StringIO()) as errors:
            assert discovery.main(["--limit", "2", "--tolerance-hours", "1"]) == 1
            assert "sensitive detail" not in errors.getvalue()


if __name__ == "__main__":
    test_missing_history_never_fills_trend_with_famous()
    test_deltas_identity_quota_and_actual_period()
    test_time_window_requires_explicit_tolerance()
    test_repository_state_and_api_evidence()
    test_search_history_refresh_casefold_and_exclusion()
    test_search_pagination_uses_constant_page_size()
    test_persistence_error_preserves_previous_output_and_history()
    print("통과: 1:1 할당·자체 관측 7일 순증가·부족분·중복제외·저장소 상태·API 실패 보존")
