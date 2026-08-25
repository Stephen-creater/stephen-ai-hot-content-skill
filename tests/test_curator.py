from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from curator import rank_candidates
import import_feedback as feedback_module
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
            self.assertIn("selection_feedback-2026-08-25-120000.json", report)
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

    def test_feedback_patterns_downrank_hype_broad_and_niche_topics(self) -> None:
        common = {
            "summary": "一篇已经完成中文整合的 AI 长文。",
            "content": "文章包含完整的事件、判断和案例。" * 100,
            "published": "2026-08-24T08:00:00Z",
            "source_name": "中文媒体",
            "source_priority": 4,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {**common, "title": "硅谷押注的下一个 Harness，是整个桌面操作系统", "link": "https://example.com/harness"},
            {**common, "title": "阿里视频大模型 Wan3.0 正式上线", "link": "https://example.com/wan"},
            {**common, "title": "匿名模型被扒出智谱血缘，也有人怀疑 Cursor", "link": "https://example.com/gossip"},
            {**common, "title": "AI 重塑商业，信任决定未来商业能走多远", "link": "https://example.com/broad"},
            {**common, "title": "一篇论文改写 AI 科研评价规则", "link": "https://example.com/science"},
            {**common, "title": "阿里达摩院推出肝癌 AI 模型", "link": "https://example.com/medical"},
        ]
        ranked = rank_candidates(items, self.profile, now=self.now)
        lookup = {item["link"]: item for item in ranked}
        self.assertTrue(lookup["https://example.com/harness"]["recommended"])
        self.assertTrue(lookup["https://example.com/wan"]["recommended"])
        self.assertIn("炒作或猎奇", lookup["https://example.com/gossip"]["penalty"])
        self.assertIn("缺少具体切口", lookup["https://example.com/broad"]["penalty"])
        self.assertIn("大众切口偏弱", lookup["https://example.com/science"]["penalty"])
        self.assertIn("大众切口偏弱", lookup["https://example.com/medical"]["penalty"])

    def test_feedback_import_can_delete_verified_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / "selection_feedback.json"
            feedback.write_text(json.dumps({"exported_at": "2026-08-25T06:20:39Z", "reviews": {"x": {"status": "rejected"}}}))
            with patch.object(feedback_module, "ROOT", root):
                target, duplicate = feedback_module.import_feedback(feedback)
                self.assertFalse(duplicate)
                self.assertTrue(feedback.exists())
                _, duplicate = feedback_module.import_feedback(feedback, delete_source=True)
                self.assertTrue(duplicate)
                self.assertFalse(feedback.exists())
                self.assertEqual(len(target.read_text().splitlines()), 1)
                self.assertEqual(feedback_module.final_reviewed_ids(target), {"x"})

    def test_second_feedback_batch_prefers_authoritative_interview(self) -> None:
        common = {
            "content": "已完成中文整理的长文材料。" * 120,
            "published": "2026-08-25T08:00:00Z",
            "source_name": "中文媒体",
            "source_priority": 4,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "赛博义父 Tibo 最新访谈",
                "summary": "下一代 Agent 将走向云端",
                "content": "OpenAI Codex 负责人核心观点，以下是对话全文。" + common["content"],
                "link": "https://example.com/interview",
            },
            {
                **common,
                "title": "开源国产 8B 模型，比肩闭源 Image 2",
                "summary": "SenseNova U1.5 Lite",
                "link": "https://example.com/unnamed-model",
            },
            {
                **common,
                "title": "WAIC CONNECT 带你拿下马来西亚 AI 采购需求",
                "summary": "活动将在吉隆坡盛大开启",
                "link": "https://example.com/event",
            },
            {
                **common,
                "title": "出版社与小猿达成合作，学习智能体首落 AI 学习机",
                "summary": "双方签署合作协议",
                "link": "https://example.com/partnership",
            },
            {
                **common,
                "title": "前 TikTok 产品经理创业，AI 视频平台获千万美元融资",
                "summary": "融资与投资方信息",
                "link": "https://example.com/product-manager-funding",
            },
            {
                **common,
                "title": "具身创业里的香港教授们",
                "summary": "AI 创业者群像",
                "link": "https://example.com/people",
            },
        ]
        ranked = rank_candidates(items, self.profile, now=self.now)
        lookup = {item["link"]: item for item in ranked}
        self.assertTrue(lookup["https://example.com/interview"]["recommended"])
        self.assertIn("权威人物访谈", lookup["https://example.com/interview"]["reason"])
        self.assertIn("事件级别不足", lookup["https://example.com/unnamed-model"]["penalty"])
        self.assertIn("活动、采购或合作宣传稿", lookup["https://example.com/event"]["penalty"])
        self.assertIn("活动、采购或合作宣传稿", lookup["https://example.com/partnership"]["penalty"])
        self.assertIn("只有资本事件", lookup["https://example.com/product-manager-funding"]["penalty"])
        self.assertIn("纯人物群像", lookup["https://example.com/people"]["penalty"])


if __name__ == "__main__":
    unittest.main()
