from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from buzz import detect, record, render


NOW = datetime(2026, 9, 19, 6, tzinfo=timezone.utc)


def item(title: str, source: str, days_ago: float, link: str) -> dict:
    return {"title": title, "source_name": source, "link": link,
            "published": (NOW - timedelta(days=days_ago)).isoformat()}


class BuzzTest(unittest.TestCase):
    def test_new_name_across_many_sources_is_flagged(self):
        rows = [
            item("Jev 到底是什么？一个只做判断的模型", "公众号甲", 1, "https://a/1"),
            item("深入解析 Jev：只做选择题的大模型", "社区", 1, "https://a/2"),
            item("Browser Use 接上 Jev 之后快了十倍", "即刻", 2, "https://a/3"),
            item("Jev: a System One model", "Latent Space", 2, "https://a/4"),
            item("The model everyone is testing: Jev", "X 作者", 0.5, "https://a/5"),
        ]
        found = detect(record(rows, NOW, {}), NOW)
        self.assertEqual(found[0]["term"], "jev")
        self.assertEqual(found[0]["sources"], 5)
        self.assertIn("jev", render(found))

    def test_name_that_is_always_around_is_not_new(self):
        rows = [item(f"Claude 新用法 {i}", f"源{i}", 1, f"https://b/{i}") for i in range(6)]
        rows += [item(f"Claude 老用法 {i}", f"源{i}", 10, f"https://c/{i}") for i in range(6)]
        self.assertEqual([row["term"] for row in detect(record(rows, NOW, {}), NOW)], [])

    def test_english_only_chatter_and_function_words_are_ignored(self):
        rows = [item("The best tool for the job", f"blog{i}", 1, f"https://d/{i}") for i in range(8)]
        self.assertEqual(detect(record(rows, NOW, {}), NOW), [])

    def test_history_is_keyed_by_link_and_expires(self):
        history = record([item("旧文章 Jev", "甲", 40, "https://e/1"), item("新文章 Jev", "乙", 1, "https://e/2")], NOW, {})
        history = record([item("新文章 Jev", "乙", 1, "https://e/2")], NOW, history)
        self.assertEqual(list(history), ["https://e/2"])


if __name__ == "__main__":
    unittest.main()
