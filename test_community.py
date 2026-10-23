"""담기 API 제거와 구독 기반 공개 피드·정기 수집 경계를 검증한다."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import accounts
import community
import community_batch
import radar
from test_radar import ISSUE, GOOD, rejects


def test_feed_contains_repository_names_without_account_details():
    with patch.object(accounts, 'subscription_repositories', return_value=['owner/repo']), patch.object(community, 'redis', return_value='{"items":[]}'):
        assert community.feed() == {'subscribed_repos':['owner/repo'], 'snapshot':{'items':[]}}


def test_batch_uses_defaults_subscriptions_and_discovery_without_registrations():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); (root / 'repos.txt').write_text('Base/Public\nBase/Private\n')
        def batch(args):
            assert args.repos.read_text().splitlines() == ['Base/Public', 'Personal/Repo', 'Trend/Repo']
            issue = radar.normalize_issue('Personal/Repo', ISSUE)
            args.issues.write_text(json.dumps(issue)+'\n')
            args.grades.write_text(json.dumps({**issue,'grade':GOOD,'criteria_version':2})+'\n')
            return 0
        lock = Mock(token='test-lock')
        with patch.object(accounts,'subscription_repositories',return_value=['Personal/Repo','BASE/PUBLIC']), patch.object(community_batch,'discovered_repositories',return_value=['Trend/Repo']), patch.object(radar,'gh_json',side_effect=lambda endpoint,**_: {'private':endpoint.endswith('Private')}), patch.object(radar,'batch',side_effect=batch), patch.object(community,'redis',return_value=1) as publish, redirect_stdout(io.StringIO()):
            assert community_batch.collect_batch(root,lock=lock) == 0
            snapshot=json.loads(publish.call_args.args[-1])
            assert snapshot['collected_repos'] == ['base/public','personal/repo','trend/repo']
            assert snapshot['discovered_repos'] == ['Trend/Repo']
            assert 'body' not in snapshot['items'][0]
            lock.check.assert_called_once()
            with patch.object(radar,'batch',return_value=1):
                publish.reset_mock()
                assert community_batch.collect_batch(root,lock=lock) == 1
                publish.assert_not_called()
            with patch.object(radar,'gh_json',side_effect=radar.GitHubAPIError(429)):
                publish.reset_mock()
                try:
                    community_batch.collect_batch(root, lock=lock)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('GitHub 장애를 숨겼습니다')
                publish.assert_not_called()


def test_discovery_contract():
    trend = [{"repo": f"trend{n}/repo", "period": "weekly"} for n in range(14)]
    famous = [{"repo": f"famous{n}/repo"} for n in range(15)]
    names = [row["repo"] for row in trend + famous]
    result = {"method": "github_trending_and_cumulative_stars", "requested_total": 30,
              "quota": {"trend": 15, "famous": 15}, "actual_total": 29, "repos": names,
              "trend": {"items": trend, "status": "partial", "shortfall": 1},
              "famous": {"items": famous, "status": "complete", "shortfall": 0}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "repos.txt").write_text("base/repo\n", encoding="utf-8")
        with patch.object(community_batch.repository_discovery, "run_github_trending", return_value=result) as discover:
            assert community_batch.discovered_repositories(root) == names
            assert discover.call_args.kwargs["allow_partial_trend"] is True
            assert discover.call_args.kwargs["period"] == "weekly"
        for bad in ({**result, "actual_total": 30}, {**result, "repos": names + [names[0]]},
                    {**result, "trend": {**result["trend"], "status": "complete"}}):
            with patch.object(community_batch.repository_discovery, "run_github_trending", return_value=bad):
                rejects(community_batch.discovered_repositories, root)


if __name__ == '__main__':
    test_feed_contains_repository_names_without_account_details()
    test_batch_uses_defaults_subscriptions_and_discovery_without_registrations()
    test_discovery_contract()
    print('통과: 구독 이름 공개·공용 등록 제외·공개 저장소만 수집·실패 시 snapshot 보존·자동 발굴 계약')
