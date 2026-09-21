from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import browser_fetch
import harvest_leads
from scrape_aihot import looks_blocked


class BlockedPageTest(unittest.TestCase):
    def test_a_verification_page_is_not_short_text(self):
        self.assertTrue(looks_blocked("环境异常 当前环境异常，完成验证后即可继续访问。 去验证"))
        self.assertFalse(looks_blocked("这是一篇正常的短文，讲了作者怎么用 Agent 重构运维流程。" * 30))

    def test_browser_output_is_read_from_either_stream(self):
        payload = json.dumps([{"url": "https://mp.weixin.qq.com/s/abc", "ok": True, "title": "标题", "text": "正文" * 300, "images": 3}])
        result = type("R", (), {"stdout": "", "stderr": f"EGO_JSON_START{payload}EGO_JSON_END"})()
        with patch("browser_fetch.subprocess.run", return_value=result):
            got = browser_fetch.fetch(["https://mp.weixin.qq.com/s/abc"])
        self.assertEqual(len(got["https://mp.weixin.qq.com/s/abc"]["text"]), 600)


class HarvestTest(unittest.TestCase):
    def test_chinese_and_hot_leads_come_first_and_known_ones_are_skipped(self):
        leads = [
            {"link": "https://x.com/a/status/1", "title": "English only post", "engagement": 900},
            {"link": "https://x.com/b/status/2", "title": "中文长帖：实测 Agent 的三种用法", "engagement": 10},
            {"link": "https://x.com/c/status/3", "title": "已经登记过的", "engagement": 999},
        ]
        picked = harvest_leads.pick(leads, 2, {"https://x.com/c/status/3"})
        self.assertEqual([row["link"] for row in picked], ["https://x.com/b/status/2", "https://x.com/a/status/1"])

    def test_video_leads_are_registered_for_the_scraper_to_transcribe(self):
        leads = [{"link": "https://www.youtube.com/watch?v=abc", "title": "一个访谈", "source_name": "频道"}]
        with tempfile.TemporaryDirectory() as raw:
            inbox = Path(raw) / "inbox.json"
            result = harvest_leads.harvest(leads, {}, {"minimum_article_chars": 800}, inbox=inbox,
                                           text_dir=Path(raw) / "text", use_browser=False)
            rows = json.loads(inbox.read_text(encoding="utf-8"))
        self.assertEqual(result["registered"], 1)
        self.assertEqual(rows[0]["platform"], "youtube")
        self.assertEqual(rows[0]["content_file"], "")

    def test_short_leads_are_not_registered(self):
        leads = [{"link": "https://m.okjike.com/originalPosts/1", "title": "一条短动态", "source_name": "即刻"}]
        with tempfile.TemporaryDirectory() as raw:
            inbox = Path(raw) / "inbox.json"
            with patch("harvest_leads.hydrate", side_effect=lambda item, settings: {**item, "content": "太短了"}):
                result = harvest_leads.harvest(leads, {}, {"minimum_article_chars": 800}, inbox=inbox,
                                               text_dir=Path(raw) / "text", use_browser=False)
            self.assertFalse(inbox.exists())
        self.assertEqual(result["registered"], 0)


if __name__ == "__main__":
    unittest.main()


class SocialPostLengthTest(unittest.TestCase):
    def test_a_five_hundred_character_x_post_counts_as_a_full_piece(self):
        import json as _json
        from curator import score_item
        from datetime import datetime, timezone
        profile = _json.loads((ROOT / "resources" / "editorial_profile.json").read_text(encoding="utf-8"))
        base = {"title": "实测 Agent 的三种用法", "summary": "作者自己跑了一周", "published": "2026-09-19",
                "source_name": "歸藏", "source_priority": 5, "source_type": "x", "source_role": "candidate",
                "language": "zh", "maturity": "primary", "content_form": "article", "content_status": "fulltext",
                "link": "https://x.com/a/status/1", "content": "我用 Agent 跑了一周的真实任务，记录每一步的成本和失败。" * 20}
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.assertGreaterEqual(len(base["content"]), 500)
        self.assertLess(len(base["content"]), 800)
        social = score_item({**base, "social_post": True}, profile, now=now)
        article = score_item(base, profile, now=now)
        self.assertNotIn("正文偏短", social["penalty"])
        self.assertIn("正文偏短", article["penalty"])
