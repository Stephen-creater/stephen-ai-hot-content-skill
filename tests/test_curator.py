from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from curator import rank_candidates
from report import generate_report


class CuratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((ROOT / "resources" / "editorial_profile.json").read_text())
        self.items = json.loads((ROOT / "tests" / "fixtures" / "sample_items.json").read_text())
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def test_personalized_ranking_and_exclusions(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)
        titles = [item["title"] for item in ranked]
        self.assertEqual(sum("Codex Harness" in title for title in titles), 1)
        self.assertIn("Codex Harness", ranked[0]["title"])
        excluded = {item["title"]: item for item in ranked if item["penalty"]}
        self.assertIn("Weekly roundup of 25 AI benchmark leaderboard updates", excluded)
        self.assertIn("Election surveillance platform adds AI weapon detection", excluded)
        self.assertFalse(excluded["Election surveillance platform adds AI weapon detection"]["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "v2.1.241")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "Windows 11 arm64 image generally available")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "llm-anthropic 0.27")["recommended"])

    def test_report_contains_review_controls(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)[:5]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report(ranked, path, "2026-08-25-120000")
            report = path.read_text()
            self.assertIn("应该入选", report)
            self.assertIn("不应入选", report)
            self.assertIn("补充遗漏选题", report)
            self.assertIn("selection_feedback.json", report)


if __name__ == "__main__":
    unittest.main()
