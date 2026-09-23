from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editorial_judgment import flags_for, validate_manual_review
from review_answers import passing_answers
from published import annotate


ARTICLES = [
    "火爆全网的Jev到底是什么？",
    "DeepSeek Harness开源，Agent自进化的前夕",
    "一个开源Skill，让AI学会选中文字体",
    "Claude Code之父：模型越聪明，AI产品越要做减法",
    "一文讲透FDE的本质与实践",
]


def fake_articles(directory: Path) -> None:
    index = []
    for number, title in enumerate(ARTICLES):
        name = f"{number}.md"
        (directory / name).write_text(title, encoding="utf-8")
        index.append({"path": ["第一周", title], "file": name, "chars": 2000})
    (directory / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


class PublishedTopicTest(unittest.TestCase):
    def test_written_topics_are_flagged_and_new_ones_are_not(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            fake_articles(directory)
            items = [
                {"title": "比 LLM 快 193 倍：Jev 的判断模型路线靠谱吗？"},
                {"title": "DeepSeek Harness：重新设计 Agent 运行时"},
                {"title": "字节发布新版豆包，主打长任务"},
                {"title": "Cursor 2.0 发布：内置多 Agent 并行"},
            ]
            annotate(items, directory)
        self.assertEqual([bool(item.get("written_topic_hint")) for item in items], [True, True, False, False])

    def test_a_flagged_candidate_cannot_be_delivered_without_saying_what_is_new(self):
        review = {
            "status": "passed",
            "answers": passing_answers(),
            "counterargument": "正文给出了具体证据，但数据只来自一次实测",
            "decision_driver": "正文给出了具体证据，足够支撑推荐",
        }
        flags = flags_for({"written_topic_hint": "火爆全网的Jev到底是什么？", "image_count": 14})
        self.assertEqual(sorted(flags), ["many_images", "written_topic_hint"])
        blocked = validate_manual_review(review, flags=flags)
        allowed = validate_manual_review(
            {**review,
             "new_progress": "官方这次开源了模型权重，上一篇发布时还只有云端 API",
             "image_plan": "十四张都是截图，正文的数字和用法自己讲得清，二创只配一张示意图"},
            flags=flags)
        self.assertFalse(blocked.ok)
        self.assertTrue(any("新进展" in error for error in blocked.errors))
        self.assertTrue(any("图" in error for error in blocked.errors))
        self.assertTrue(allowed.ok, allowed.errors)


if __name__ == "__main__":
    unittest.main()
