"""실행: python3.14 test_repository_discovery.py. GitHub 호출은 mock으로 대체한다."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from email.message import Message
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
            assert discovery.main(["--source", "own-history", "--limit", "2", "--tolerance-hours", "1"]) == 1
            assert "sensitive detail" not in errors.getvalue()


def trending_html(names, period="weekly"):
    rows = [f'<article class="Box-row"><h2><a href="/{name}">{name}</a></h2>'
            f'<span>{1000-rank:,} stars {discovery.PERIOD_LABELS[period]}</span></article>'
            for rank, name in enumerate(names)]
    return '<html><h1>Trending</h1>' + "".join(rows) + '</html>'


class HTMLResponse(io.BytesIO):
    def __init__(self, html, url="https://github.com/trending?since=weekly"):
        content = html.encode()
        super().__init__(content)
        self.status = 200
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"
        self.headers["Content-Length"] = str(len(content))


def test_trending_parser_and_transport_fail_closed():
    html = trending_html(["owner/one", "owner/two"])
    rows = discovery.parse_trending(html, "weekly")
    assert rows == [{"repo": "owner/one", "rank": 1, "period_stars": 1000},
                    {"repo": "owner/two", "rank": 2, "period_stars": 999}]
    for malformed in (html[:-7], html.replace('Box-row', 'Changed'),
                      html.replace('this week', 'today'),
                      html.replace('owner/two', 'owner/one'),
                      html.replace('1,000', '1,00'),
                      html.replace('<h2>', '<h3>').replace('</h2>', '</h3>'),
                      html.replace('Trending</h1>', 'Sign in</h1>')):
        rejects(discovery.parse_trending, malformed, "weekly")
    for change in ("redirect", "partial", "type", "status"):
        response = HTMLResponse(html)
        if change == "redirect":
            response.url = "https://github.com/login"
        elif change == "partial":
            response.headers.replace_header("Content-Length", "999999")
        elif change == "type":
            response.headers.replace_header("Content-Type", "application/json")
        else:
            response.status = 206
        rejects(discovery.fetch_trending, "weekly", open_url=lambda *a, **k: response)
    def opener(request, timeout):
        assert request.full_url == "https://github.com/trending?since=weekly" and timeout == 30
        return HTMLResponse(html)
    fetched, source = discovery.fetch_trending("weekly", open_url=opener, clock=lambda: NOW)
    assert fetched == rows and source["period"] == "weekly" and source["rows"] == 2
    assert source["fetched_at"] == NOW.isoformat() and len(source["sha256"]) == 64


def test_trending_quota_fills_from_next_source_rank():
    names = ["owner/disabled", "owner/trend-first", "owner/trend-next"]
    infos = {"owner/disabled": api_repo("owner/disabled", 10, 250000, has_issues=False),
             "owner/trend-first": api_repo("owner/trend-first", 1, 240000),
             "owner/trend-next": api_repo("owner/trend-next", 2, 230000),
             "owner/famous-one": api_repo("owner/famous-one", 3, 220000),
             "owner/famous-two": api_repo("owner/famous-two", 4, 210000)}
    def github(endpoint):
        if endpoint.startswith("search/"):
            items = list(infos.values())
            return {"items": items, "total_count": len(items), "incomplete_results": False}
        return infos[endpoint[6:]]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "discovery.json"
        result = discovery.run_github_trending(limit=4, period="weekly", output_path=output,
            gh=github, clock=lambda: NOW, open_url=lambda *a, **k: HTMLResponse(trending_html(names)))
        assert json.loads(output.read_text()) == result
        assert result["repos"] == ["owner/trend-first", "owner/trend-next", "owner/famous-one", "owner/famous-two"]
        assert result["trend"]["items"][0]["rank"] == 2
        assert result["trend"]["items"][0]["period"] == "weekly"
        assert result["source"]["famous_searches"][0]["total_count"] == 5
        assert result["source"]["famous_searches"][0]["returned_count"] == 5
        assert result["quota"] == {"trend": 2, "famous": 2}
        assert result["famous"]["shortfall"] == result["trend"]["shortfall"] == 0
        assert not list(Path(directory).glob("*.tmp"))


def test_famous_threshold_is_search_optimization_not_selection_cutoff():
    infos = {"owner/trend-one": api_repo("owner/trend-one", 1, 200000),
             "owner/trend-two": api_repo("owner/trend-two", 2, 190000),
             "owner/famous-one": api_repo("owner/famous-one", 3, 90000),
             "owner/famous-two": api_repo("owner/famous-two", 4, 80000)}
    calls = []
    def github(endpoint):
        calls.append(endpoint)
        if endpoint.startswith("search/"):
            query = parse_qs(urlsplit(endpoint).query)["q"][0]
            threshold = int(query.split()[0].split(">=")[1])
            items = [row for row in infos.values() if row["stargazers_count"] >= threshold]
            return {"items": items, "total_count": len(items), "incomplete_results": False}
        return infos[endpoint[6:]]
    with tempfile.TemporaryDirectory() as directory:
        result = discovery.run_github_trending(limit=4, period="weekly", output_path=Path(directory)/"out.json",
            gh=github, clock=lambda: NOW,
            open_url=lambda *a, **k: HTMLResponse(trending_html(["owner/trend-one", "owner/trend-two"])))
        assert [row["threshold"] for row in result["source"]["famous_searches"]] == [100000, 50000]
        assert result["famous"]["items"][-1]["stars"] == 80000
        assert all("fork%3Atrue" in call for call in calls if call.startswith("search/"))


def test_trending_failures_preserve_previous_output():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "out.json"
        output.write_text("previous")
        infos = {"owner/a": api_repo("owner/a", 1, 200000),
                 "owner/b": api_repo("owner/b", 2, 190000)}
        options = dict(limit=4, period="weekly", output_path=output, clock=lambda: NOW,
                       open_url=lambda *a, **k: HTMLResponse(trending_html(list(infos))))
        def incomplete(endpoint):
            if endpoint.startswith("search/"):
                return {"items": [], "total_count": 0, "incomplete_results": True}
            return infos[endpoint[6:]]
        rejects(discovery.run_github_trending, gh=incomplete, **options)
        assert output.read_text() == "previous"
        rejects(discovery.run_github_trending, gh=incomplete,
                **{**options, "open_url": lambda *a, **k: HTMLResponse(trending_html(["owner/a"]))})
        assert output.read_text() == "previous"
        for response in ({"items": [], "total_count": 2, "incomplete_results": False},
                         {"items": [], "total_count": 1001, "incomplete_results": False},
                         {"items": [infos["owner/b"], infos["owner/a"]], "total_count": 2, "incomplete_results": False}):
            rejects(discovery.famous_search, 100000, lambda endpoint: response)
        def mismatched_id(endpoint):
            if endpoint.startswith("search/"):
                return {"items": [api_repo("owner/c", 3, 300000), api_repo("owner/d", 4, 250000)],
                        "total_count": 2, "incomplete_results": False}
            if endpoint[6:] in infos:
                return infos[endpoint[6:]]
            return api_repo(endpoint[6:], 99, 300000)
        rejects(discovery.run_github_trending, gh=mismatched_id, **options)
        assert output.read_text() == "previous"


def test_exact_fifteen_each_and_full_famous_pagination():
    names = [f"owner/r{i}" for i in range(30)]
    infos = {name: api_repo(name, i+1, 300000-i) for i, name in enumerate(names)}
    def github(endpoint):
        if endpoint.startswith("search/"):
            return {"items": list(infos.values()), "total_count": 30, "incomplete_results": False}
        return infos[endpoint[6:]]
    with tempfile.TemporaryDirectory() as directory:
        result = discovery.run_github_trending(limit=30, period="weekly", output_path=Path(directory)/"out.json",
            gh=github, clock=lambda: NOW,
            open_url=lambda *a, **k: HTMLResponse(trending_html(names[:15])))
        assert result["quota"] == {"trend": 15, "famous": 15}
        assert len(result["trend"]["items"]) == len(result["famous"]["items"]) == 15
        assert result["repos"] == names
        assert len({row["id"] for group in ("trend", "famous") for row in result[group]["items"]}) == 30
    def paginated(endpoint):
        page = int(parse_qs(urlsplit(endpoint).query)["page"][0])
        return {"items": [api_repo(f"owner/r{i}", i+1, 300000-i)
                          for i in range((page-1)*100, min(page*100,150))],
                "total_count": 150, "incomplete_results": False}
    records, evidence = discovery.famous_search(100000, paginated)
    assert len(records) == evidence["returned_count"] == evidence["total_count"] == 150
    assert len(evidence["urls"]) == 2
    assert "page=2" in evidence["urls"][1]


def test_partial_trending_requires_opt_in_and_preserves_source_evidence():
    names = [f"owner/r{i}" for i in range(30)]
    infos = {name: api_repo(name, i+1, 300000-i, has_issues=(i != 0))
             for i, name in enumerate(names)}
    def github(endpoint):
        if endpoint.startswith("search/"):
            return {"items": list(infos.values()), "total_count": 30, "incomplete_results": False}
        return infos[endpoint[6:]]
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)/"out.json"
        output.write_text("previous")
        options = dict(limit=30, period="weekly", output_path=output, gh=github, clock=lambda: NOW,
            open_url=lambda *a, **k: HTMLResponse(trending_html(names[:15])))
        rejects(discovery.run_github_trending, **options)
        assert output.read_text() == "previous"
        result = discovery.run_github_trending(**options, allow_partial_trend=True)
        assert result["requested_total"] == 30 and result["actual_total"] == 29
        assert result["trend"]["status"] == "partial" and result["trend"]["shortfall"] == 1
        assert len(result["trend"]["items"]) == 14
        assert result["famous"]["status"] == "complete" and result["famous"]["shortfall"] == 0
        assert len(result["famous"]["items"]) == 15
        assert result["source"]["trending"]["rows"] == 15
        assert result["source"]["excluded"] == {"issues_disabled": 1}
        assert len(set(result["repos"])) == result["actual_total"] == 29
        assert json.loads(output.read_text()) == result
        with patch.object(discovery, "run_github_trending", return_value=result) as runner, redirect_stdout(io.StringIO()) as stdout:
            assert discovery.main(["--source", "github-trending", "--limit", "30", "--period", "weekly",
                                   "--allow-partial-trending", "--output", str(output)]) == 0
            assert runner.call_args.kwargs["allow_partial_trend"] is True
            assert stdout.getvalue().strip() == "저장소 후보: 트렌드 14개, 유명 15개"


def test_partial_trending_does_not_hide_source_or_famous_failures():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)/"out.json"
        output.write_text("previous")
        infos = {"owner/disabled": api_repo("owner/disabled", 1, 300000, has_issues=False),
                 "owner/trend": api_repo("owner/trend", 2, 290000),
                 "owner/famous": api_repo("owner/famous", 3, 280000)}
        def github(endpoint):
            if endpoint.startswith("search/"):
                return {"items": list(infos.values()), "total_count": 3, "incomplete_results": False}
            return infos[endpoint[6:]]
        options = dict(limit=4, period="weekly", output_path=output, gh=github, clock=lambda: NOW,
                       allow_partial_trend=True)
        html = trending_html(["owner/disabled", "owner/trend"])
        # 적격 유명 후보가 2개 미만이면 Trending 일부 허용과 관계없이 실패한다.
        rejects(discovery.run_github_trending, **options, open_url=lambda *a, **k: HTMLResponse(html))
        assert output.read_text() == "previous"
        for invalid_html in (trending_html([]), html[:-7], html.replace("Box-row", "Changed"),
                             trending_html(["owner/disabled"])):
            rejects(discovery.run_github_trending, **options,
                    open_url=lambda *a, **k: HTMLResponse(invalid_html))
            assert output.read_text() == "previous"
        response = HTMLResponse(html)
        response.headers.replace_header("Content-Length", "999999")
        rejects(discovery.run_github_trending, **options, open_url=lambda *a, **k: response)
        assert output.read_text() == "previous"
        for failure in (RuntimeError("API failure"),
                        {"items": [], "total_count": 0, "incomplete_results": True}):
            def failing(endpoint):
                if isinstance(failure, RuntimeError):
                    raise failure
                return failure if endpoint.startswith("search/") else github(endpoint)
            rejects(discovery.run_github_trending, **{**options, "gh": failing},
                    open_url=lambda *a, **k: HTMLResponse(html))
            assert output.read_text() == "previous"


if __name__ == "__main__":
    test_missing_history_never_fills_trend_with_famous()
    test_deltas_identity_quota_and_actual_period()
    test_time_window_requires_explicit_tolerance()
    test_repository_state_and_api_evidence()
    test_search_history_refresh_casefold_and_exclusion()
    test_search_pagination_uses_constant_page_size()
    test_persistence_error_preserves_previous_output_and_history()
    test_trending_parser_and_transport_fail_closed()
    test_trending_quota_fills_from_next_source_rank()
    test_famous_threshold_is_search_optimization_not_selection_cutoff()
    test_trending_failures_preserve_previous_output()
    test_exact_fifteen_each_and_full_famous_pagination()
    test_partial_trending_requires_opt_in_and_preserves_source_evidence()
    test_partial_trending_does_not_hide_source_or_famous_failures()
    print("통과: GitHub Trending 순위·기간·15:15 할당·원천별 다음 순위·완전 검색·오류 보존")
    print("통과: 1:1 할당·자체 관측 7일 순증가·부족분·중복제외·저장소 상태·API 실패 보존")
