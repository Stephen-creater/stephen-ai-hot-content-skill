"""2026-09-21 b 批：图片视频过多、已写主题别名、发布前回读链接。"""
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from curator import score_item  # noqa: E402
from editorial_judgment import flags_for, validate_manual_review  # noqa: E402
from publish_batch import unreachable_links  # noqa: E402
from published import annotate  # noqa: E402
from scrape_aihot import count_videos, render_triage_markdown  # noqa: E402

PROFILE = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
REVIEW = {
    "status": "passed",
    "scores": {"topic_appeal": 2, "reader_change": 2, "material_increment": 2, "re_authorability": 2, "durability": 1, "rewrite_effort": 1},
    **{field: "正文给出了具体证据，足够支撑这一项的判断" for field in
       ("topic_appeal", "reader_change", "material_increment", "re_authorability", "durability", "rewrite_effort", "counterargument", "decision_driver")},
}


def failures_of(result: dict) -> list[str]:
    decision = result.get("editorial_decision") or {}
    found = list((decision.get("eligibility") or {}).get("failures") or [])
    penalty = result.get("penalty", [])
    found += [penalty] if isinstance(penalty, str) else list(penalty)
    return [str(item) for item in found]


def article(**extra):
    base = {"title": "豆包工作怎么用最爽？实测 6 个场景", "summary": "AI 办公 Agent 实测", "link": "https://mp.weixin.qq.com/s/abc",
            "content": "豆包工作" * 400, "content_status": "fulltext", "content_form": "article", "language": "zh",
            "published": "2026-09-20T10:00:00+08:00", "source_name": "测试号", "source_role": "candidate"}
    return {**base, **extra}


class VideoCountTest(unittest.TestCase):
    def test_wechat_and_bilibili_embeds_are_counted_once_each(self):
        html = ('<p>看视频</p><iframe class="video_iframe" data-mpvid="wxv_12345678901"></iframe>'
                '<mpvideo data-mpvid="wxv_12345678902"></mpvideo>'
                '<iframe src="https://player.bilibili.com/player.html?bvid=1"></iframe><video src="a.mp4"></video>')
        self.assertEqual(count_videos(html), 4)

    def test_plain_text_mentioning_video_is_not_an_embed(self):
        self.assertEqual(count_videos("<p>文中提到一个视频，但没有嵌入</p><img src='a.png'>"), 0)

    def test_triage_line_shows_video_count(self):
        line = render_triage_markdown([{"id": "x", "title": "标题", "link": "https://example.com", "content": "正文", "image_count": 3, "video_count": 2}])
        self.assertIn("视频 2 段", line)


class MediaGateTest(unittest.TestCase):
    def test_ten_images_or_two_videos_are_rejected_outright(self):
        ten = failures_of(score_item(article(image_count=10), PROFILE))
        self.assertTrue(any("配图 10 张" in failure for failure in ten), ten)
        videos = failures_of(score_item(article(image_count=3, video_count=2), PROFILE))
        self.assertTrue(any("视频 2 段" in failure for failure in videos), videos)

    def test_nine_images_or_one_video_only_need_a_plan(self):
        nine = failures_of(score_item(article(image_count=9, video_count=1), PROFILE))
        self.assertFalse([failure for failure in nine if "配图" in failure or "视频" in failure], nine)
        flags = flags_for({"image_count": 9, "video_count": 1}, maximum_images=PROFILE["maximum_images"])
        self.assertEqual(sorted(flags), ["has_video", "many_images"])
        self.assertFalse(validate_manual_review(REVIEW, flags=flags).ok)
        planned = {**REVIEW, "image_plan": "九张都是界面截图，功能文字讲得清；演示视频只是效果展示，二创不用"}
        self.assertTrue(validate_manual_review(planned, flags=flags).ok)

    def test_six_images_without_video_need_nothing(self):
        self.assertEqual(flags_for({"image_count": 6, "video_count": 0}, maximum_images=PROFILE["maximum_images"]), {})


class TopicAliasTest(unittest.TestCase):
    def test_alias_marks_a_differently_titled_candidate_as_written(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            (directory / "index.json").write_text(json.dumps([
                {"path": ["第八周", "9.14 为什么手机才是 Memory 最好的土壤？兼谈即将到来的豆包手机.md"], "chars": 3000}]), encoding="utf-8")
            (directory / "topic_aliases.json").write_text(json.dumps(
                {"为什么手机才是 Memory 最好的土壤？兼谈即将到来的豆包手机": ["AI OS", "豆包手机"]}, ensure_ascii=False), encoding="utf-8")
            rows = annotate([{"title": "苹果OV密集发布，涌现“AI OS元周”，到底谁更能打？"},
                             {"title": "一个开源 Skill，让 AI 学会选中文字体"}], directory)
        self.assertIn("豆包手机", rows[0]["written_topic_hint"])
        self.assertNotIn("written_topic_hint", rows[1])


class LinkReadbackTest(unittest.TestCase):
    def test_site_that_does_not_answer_blocks_publishing(self):
        rows = [{"title": "30086 组对局", "link": "https://www.jxxy.net/ai/articles/arena/"}]
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(socket.timeout("timed out"))):
            dead = unreachable_links(rows, timeout=1)
        self.assertEqual([title for title, _ in dead], ["30086 组对局"])

    def test_http_error_codes_still_count_as_reachable(self):
        rows = [{"title": "知乎回答", "link": "https://www.zhihu.com/question/1/answer/2"}]
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("u", 403, "forbidden", {}, None)):
            self.assertEqual(unreachable_links(rows, timeout=1), [])


if __name__ == "__main__":
    unittest.main()


class PaywallAndDoubtTest(unittest.TestCase):
    def test_paywalled_site_is_rejected_outright(self):
        from curator import score_item as score
        wired = failures_of(score(article(link="https://www.wired.com/story/how-to-use-memory-in-chatgpt", title="ChatGPT memory 怎么管"), PROFILE))
        self.assertTrue(any("付费墙" in failure for failure in wired), wired)
        clean = failures_of(score(article(link="https://www.qbitai.com/2026/09/492973.html", title="剪映发了个大的"), PROFILE))
        self.assertFalse(any("付费墙" in failure for failure in clean), clean)

    def test_doubt_naming_a_written_topic_requires_new_facts(self):
        doubted = {**REVIEW, "counterargument": "Stephen 9 月 15 日已经写过 RSI，那篇的结论和这篇一样；后半段是安全议题"}
        blocked = validate_manual_review(doubted)
        self.assertFalse(blocked.ok)
        self.assertTrue(any("new_progress" in error for error in blocked.errors), blocked.errors)
        allowed = validate_manual_review({**doubted, "new_progress": "这次官方公开了 1 万个智能体 88 小时的协作日志和成本数据，上一篇写时只有结论"})
        self.assertTrue(allowed.ok, allowed.errors)
        plain = validate_manual_review({**REVIEW, "counterargument": "数据来自厂商自述，没有第三方实测"})
        self.assertTrue(plain.ok, plain.errors)
