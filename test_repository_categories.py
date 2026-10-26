"""실제 GitHub·Vertex·Redis 호출 없이 저장소 분류와 공개 결과를 검증한다."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import collection_worker as worker
import community
import public_feed
import radar
import repository_categories as categories
from test_radar import GOOD, ISSUE


INFO = {"private": False, "has_issues": True, "description": "AI agent workflow automation",
        "topics": ["ai", "agents", "automation"]}
CLASSIFIED = {"description": "AI 에이전트 워크플로 자동화 도구",
              "categories": ["ai-ml", "agents-automation"]}


class RepositoryCategoriesTest(unittest.TestCase):
    def test_unknown_repository_is_classified_once_and_reused_with_different_case(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            with patch.object(categories.vertex, "generate_json", return_value=CLASSIFIED) as generate:
                result = categories.categorize_repositories({"Q00/ouroboros": INFO}, cache)
                self.assertEqual(result["q00/ouroboros"], CLASSIFIED)
                self.assertEqual(categories.categorize_repositories({"q00/OUROBOROS": INFO}, cache), result)
                generate.assert_called_once()
                prompt, schema, model = generate.call_args.args
                self.assertIn(INFO["description"], prompt)
                self.assertIn('"topics": ["ai", "agents", "automation"]', prompt)
                self.assertIn("신뢰할 수 없는 저장소 데이터", prompt)
                self.assertEqual(set(schema["properties"]["categories"]["items"]["enum"]), set(categories.CATEGORIES))
                self.assertEqual(model, categories.vertex.DEFAULT_MODEL)
            issue = radar.normalize_issue("Q00/ouroboros", ISSUE)
            items = public_feed.public_items([issue], [{**issue, "grade": GOOD}], result)
            self.assertEqual(items[0]["categories"], CLASSIFIED["categories"])
            self.assertEqual(items[0]["description"], CLASSIFIED["description"])
            self.assertNotIn("body", items[0])

    def test_known_catalog_uses_case_insensitive_curated_categories_without_ai(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(categories.vertex, "generate_json") as generate:
            result = categories.categorize_repositories({"ML-EXPLORE/MLX": INFO}, Path(directory) / "cache.json")
            self.assertEqual(result["ml-explore/mlx"]["categories"], ["ai-ml"])
            self.assertEqual(public_feed.public_items([radar.normalize_issue("ml-explore/MLX", ISSUE)], [])[0]["categories"], ["ai-ml"])
            generate.assert_not_called()

    def test_invalid_ai_output_is_not_cached_and_next_collection_retries(self):
        invalid = [None, {**CLASSIFIED, "categories": ["invented"]},
                   {**CLASSIFIED, "categories": ["ai-ml", "ai-ml"]},
                   {**CLASSIFIED, "categories": list(categories.CATEGORIES)[:4]},
                   {**CLASSIFIED, "categories": [{}]}, {**CLASSIFIED, "description": ""},
                   {**CLASSIFIED, "description": "x" * 121},
                   {**CLASSIFIED, "description": "개행\n설명"}, {**CLASSIFIED, "private": True}]
        for value in invalid:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "cache.json"
                with patch.object(categories.vertex, "generate_json", return_value=value), redirect_stderr(io.StringIO()):
                    fallback = categories.categorize_repositories({"q00/ouroboros": INFO}, cache)
                self.assertEqual(fallback["q00/ouroboros"], {"description": INFO["description"], "categories": []})
                self.assertFalse(cache.exists())
                with patch.object(categories.vertex, "generate_json", return_value=CLASSIFIED) as generate:
                    self.assertEqual(categories.categorize_repositories({"q00/ouroboros": INFO}, cache)["q00/ouroboros"], CLASSIFIED)
                    generate.assert_called_once()

    def test_api_or_cache_failure_keeps_collection_results_and_safe_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            logs = io.StringIO()
            with patch.object(categories.vertex, "generate_json", side_effect=RuntimeError("sensitive-value")), redirect_stderr(logs):
                result = categories.categorize_repositories({"q00/ouroboros": INFO}, cache)
            self.assertEqual(result["q00/ouroboros"]["categories"], [])
            self.assertNotIn("sensitive-value", logs.getvalue())
            cache.write_text("invalid json", encoding="utf-8")
            with patch.object(categories.vertex, "generate_json", return_value=CLASSIFIED), patch.object(categories, "save_cache", side_effect=OSError), redirect_stderr(logs):
                self.assertEqual(categories.categorize_repositories({"q00/ouroboros": INFO}, cache)["q00/ouroboros"], CLASSIFIED)

    def test_no_evidence_does_not_guess_and_empty_categories_can_be_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            with patch.object(categories.vertex, "generate_json") as generate, redirect_stderr(io.StringIO()):
                result = categories.categorize_repositories({"a/b": {"description": None, "topics": []}}, cache)
                self.assertEqual(result["a/b"]["categories"], [])
                generate.assert_not_called()
                self.assertFalse(cache.exists())
            with patch.object(categories.vertex, "generate_json", return_value={**CLASSIFIED, "categories": []}) as generate:
                categories.categorize_repositories({"a/b": INFO}, cache)
                categories.categorize_repositories({"a/b": INFO}, cache)
                generate.assert_called_once()

    def test_category_ids_match_the_existing_ui(self):
        source = Path(__file__).with_name("repobite-app.mjs").read_text(encoding="utf-8")
        topics = source.split("const TOPICS = [", 1)[1].split("];", 1)[0]
        import re
        self.assertEqual(set(re.findall(r"\['([^']+)'", topics)), set(categories.CATEGORIES))

    def test_immediate_collection_publishes_metadata_even_without_issues(self):
        for has_issue in (True, False):
            with self.subTest(has_issue=has_issue), tempfile.TemporaryDirectory() as directory:
                def collect(args):
                    rows = [radar.normalize_issue("q00/ouroboros", ISSUE)] if has_issue else []
                    args.output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                    return 0
                def grade(args):
                    args.output.write_text("", encoding="utf-8")
                    return 0
                with patch.object(radar, "gh_json", return_value=INFO), patch.object(radar, "collect", side_effect=collect), patch.object(radar, "grade", side_effect=grade), patch.object(radar, "candidates", return_value=0), patch.object(categories.vertex, "generate_json", return_value=CLASSIFIED):
                    items, metadata = worker.collect_repository("q00/ouroboros", directory, Mock())
                self.assertEqual(len(items), int(has_issue))
                self.assertEqual(metadata["q00/ouroboros"], CLASSIFIED)
                previous = {"items": [{"repo": "other/repo", "number": 1}], "collected_repos": ["other/repo"],
                            "repositories": {"other/repo": {"description": "기존 저장소", "categories": ["mobile"]}}}
                with patch.object(community, "redis", side_effect=[json.dumps(previous), 1]) as redis:
                    worker.merge_repository("q00/ouroboros", items, Mock(token="lock"), metadata)
                snapshot = json.loads(redis.call_args.args[-1])
                self.assertEqual(snapshot["repositories"]["q00/ouroboros"], CLASSIFIED)
                self.assertEqual(snapshot["repositories"]["other/repo"], previous["repositories"]["other/repo"])
                self.assertEqual(snapshot["items"][0], previous["items"][0])

    def test_batch_backfills_existing_unknown_repo_and_never_sends_private_repo_to_ai(self):
        import accounts
        import community_batch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "repos.txt").write_text("Q00/ouroboros\nsecret/private\n", encoding="utf-8")
            def github(endpoint, **_):
                return {**INFO, "private": endpoint.endswith("private")}
            def batch(args):
                issue = radar.normalize_issue("Q00/ouroboros", ISSUE)
                args.issues.write_text(json.dumps(issue) + "\n", encoding="utf-8")
                args.grades.write_text(json.dumps({**issue, "grade": GOOD, "criteria_version": 2}) + "\n", encoding="utf-8")
                return 0
            with patch.object(accounts, "subscription_repositories", return_value=[]), patch.object(community_batch, "discovered_repositories", return_value=[]), patch.object(radar, "gh_json", side_effect=github), patch.object(radar, "batch", side_effect=batch), patch.object(categories.vertex, "generate_json", return_value=CLASSIFIED) as generate, patch.object(community, "redis", return_value=1) as redis, redirect_stdout(io.StringIO()):
                self.assertEqual(community_batch.collect_batch(root, lock=Mock(token="lock")), 0)
                snapshot = json.loads(redis.call_args.args[-1])
                self.assertEqual(snapshot["repositories"], {"q00/ouroboros": CLASSIFIED})
                self.assertEqual(snapshot["items"][0]["categories"], CLASSIFIED["categories"])
                self.assertNotIn("secret/private", generate.call_args.args[0])
                community_batch.collect_batch(root, lock=Mock(token="lock"))
                generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
