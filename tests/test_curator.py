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
from scrape_aihot import inbox_item


class CuratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = json.loads((ROOT / "resources" / "editorial_profile.json").read_text())
        self.items = json.loads((ROOT / "tests" / "fixtures" / "sample_items.json").read_text())
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def test_personalized_ranking_and_exclusions(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)
        titles = [item["title"] for item in ranked]
        self.assertEqual(sum("Codex Harness" in title for title in titles), 1)
        self.assertTrue(any("Codex Harness" in item["title"] for item in ranked[:3]))
        self.assertIn("中文内容", ranked[0]["reason"])
        self.assertTrue(any("已有逐字稿" in item["reason"] for item in ranked[:3]))
        excluded = {item["title"]: item for item in ranked if item["penalty"]}
        self.assertIn("Weekly roundup of 25 AI benchmark leaderboard updates", excluded)
        self.assertIn("Election surveillance platform adds AI weapon detection", excluded)
        self.assertFalse(excluded["Election surveillance platform adds AI weapon detection"]["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "v2.1.241")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "Windows 11 arm64 image generally available")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "llm-anthropic 0.27")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"].startswith("DeepSeek上线多模态；"))["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "130亿美元，Hugging Face要卖了")["recommended"])

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
            self.assertIn("二创成熟度", report)
            self.assertIn("已自动保存到浏览器，尚未导出", report)
            self.assertIn("导出全部审核结果", report)
            self.assertIn("beforeunload", report)
            self.assertIn("review-counts", report)
            self.assertIn("state.dirty===undefined", report)

    def test_local_transcript_becomes_ready_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.txt"
            transcript.write_text("这是一份中文逐字稿。" * 100)
            item = inbox_item(
                {
                    "url": "https://www.bilibili.com/video/BVtest",
                    "platform": "bilibili",
                    "creator": "测试UP主",
                    "title": "Codex Agent 工作流深度复盘",
                    "published": "2026-08-24",
                    "transcript_path": str(transcript),
                },
                {"request_timeout_seconds": 1, "max_article_bytes": 1000},
            )
            self.assertEqual(item["content_status"], "transcript")
            self.assertEqual(item["language"], "zh")
            self.assertGreater(len(item["content"]), 500)


if __name__ == "__main__":
    unittest.main()
