import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_replay  # noqa: E402
from datetime import datetime, timezone

from curator import score_item  # noqa: E402

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)

PROFILE = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))


class ReadingOrderTest(unittest.TestCase):
    def test_reading_order_ignores_wording(self) -> None:
        body = "作者连续两个月用 AI 完成真实任务，记录了失败、调整和结果。" * 60
        base = {"link": "https://example.com/a", "language": "zh", "maturity": "secondary", "content_status": "fulltext",
                "content_form": "article", "source_priority": 4, "summary": "AI 实践复盘", "content": body}
        plain = score_item({**base, "title": "用 AI 做两个月真实任务的复盘"}, PROFILE, now=NOW)
        hyped = score_item({**base, "title": "炸裂！用 AI 做两个月真实任务的复盘", "link": "https://example.com/b"}, PROFILE, now=NOW)
        self.assertEqual(plain["penalty"], "")
        self.assertEqual(hyped["penalty"], "")
        self.assertEqual(plain["reading_order"], hyped["reading_order"])


class EvalReplayTest(unittest.TestCase):
    def feedback(self, directory: Path) -> Path:
        body = "这是一篇讨论真实 AI 工作流的完整中文材料，包含失败、调整和结果。" * 40
        rows = [
            {"id": "keep", "title": "AI 客户拜访实测", "link": "https://example.com/a", "content": body, "language": "zh", "content_status": "fulltext"},
            {"id": "drop", "title": "某模型跑分登顶", "link": "https://example.com/b", "content": body, "language": "zh", "content_status": "fulltext"},
            {"id": "thin", "title": "只有摘要", "link": "https://example.com/c", "content": "短", "language": "zh"},
        ]
        record = {
            "generated_at": "batch-1",
            "candidates": rows,
            "reviews": {
                "keep": {"status": "selected", "reasons": ["干货足"]},
                "drop": {"status": "rejected", "note": "整批质量不达标"},
                "thin": {"status": "rejected", "reasons": [], "implicit": True},
            },
        }
        path = directory / "feedback.jsonl"
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def test_collect_marks_label_strength_and_judgeability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = {item["id"]: item for item in eval_replay.collect(self.feedback(Path(tmp)), adoptions={})}
        self.assertEqual(items["keep"]["label_strength"], "strong")
        self.assertEqual(items["drop"]["label_strength"], "weak")
        self.assertEqual(items["thin"]["label_strength"], "weak")
        self.assertFalse(items["thin"]["judgeable"])
        self.assertEqual({item["split"] for item in items.values()}, {eval_replay.split_for("batch-1")})

    def test_blind_export_hides_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = eval_replay.collect(self.feedback(Path(tmp)), adoptions={})
        rows = eval_replay.export_blind(items, "all", None)
        self.assertEqual({row["id"] for row in rows}, {"keep", "drop"})
        for row in rows:
            self.assertNotIn("label", row)
            self.assertNotIn("reasons", row)

    def test_score_reports_recall_precision_and_misses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = eval_replay.collect(self.feedback(Path(tmp)), adoptions={})
        result = eval_replay.score_verdicts(items, [
            {"id": "keep", "verdict": "reject", "reason": "太技术"},
            {"id": "drop", "verdict": "reject"},
        ])
        self.assertEqual(result["selected_recall"], 0.0)
        self.assertEqual(result["confusion"]["missed_selected"], 1)
        self.assertEqual(result["missed_selected"][0]["id"], "keep")

    def test_regression_warning_compares_same_benchmark_and_split(self) -> None:
        history = [{"kind": "judge", "benchmark": "v1", "split": "dev", "metrics": {"selected_recall": 0.95}}]
        entry = {"kind": "judge", "benchmark": "v1", "split": "dev", "metrics": {"selected_recall": 0.8}}
        self.assertTrue(eval_replay.regression_warnings(entry, history))
        self.assertFalse(eval_replay.regression_warnings({**entry, "split": "holdout"}, history))
        # A baseline run with a different judge label is not a regression of this one.
        self.assertFalse(eval_replay.regression_warnings({**entry, "judge": "旧标准"}, history))

    def test_machine_regression_ignores_reading_order(self) -> None:
        history = [{"kind": "machine", "benchmark": "v1", "split": "dev", "metrics": {"selected_kept_rate": 1.0, "ranking_auc": 0.66}}]
        entry = {"kind": "machine", "benchmark": "v1", "split": "dev", "metrics": {"selected_kept_rate": 1.0, "ranking_auc": 0.58}}
        self.assertFalse(eval_replay.regression_warnings(entry, history))
        self.assertTrue(eval_replay.regression_warnings({**entry, "metrics": {"selected_kept_rate": 0.9}}, history))

    def test_written_articles_override_review_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.feedback(Path(tmp))
            topics = Path(tmp) / "topics"
            (topics / "batch-2").mkdir(parents=True)
            body = "一篇后来被写成文章的完整中文材料，讲清了新功能怎么用。" * 40
            (topics / "batch-2" / "candidates.json").write_text(json.dumps([{"id": "later", "title": "腾讯会议新功能实测", "content": body}], ensure_ascii=False), encoding="utf-8")
            adoptions = {"drop": {"article": "9.x"}, "later": {"article": "9.16"}}
            items = {item["id"]: item for item in eval_replay.collect(path, adoptions=adoptions, topics=topics)}
        self.assertEqual(items["drop"]["label"], "selected")
        self.assertEqual(items["drop"]["label_strength"], "adopted")
        self.assertEqual(items["later"]["label"], "selected")
        self.assertTrue(items["later"]["judgeable"])

    def test_sync_articles_walks_tree_read_only(self) -> None:
        import sync_articles
        calls = []

        def fake(args):
            calls.append(args[:2])
            if args[1] == "+node-list":
                parent = args[args.index("--parent-node-token") + 1]
                nodes = {"root": [{"title": "第一周", "node_token": "w1", "obj_type": "docx", "obj_token": "d1", "has_child": True}],
                         "w1": [{"title": "9.1 文章", "node_token": "a1", "obj_type": "docx", "obj_token": "d2", "has_child": False}]}
                return {"data": {"nodes": nodes.get(parent, [])}}
            return {"data": {"document": {"content": "正文" * 200}}}

        with tempfile.TemporaryDirectory() as tmp:
            index = sync_articles.sync("space", "root", Path(tmp), fake)
            self.assertTrue((Path(tmp) / "第一周__9.1 文章.md").exists())
        self.assertEqual([row["path"] for row in index], [["第一周"], ["第一周", "9.1 文章"]])
        self.assertTrue(all(call[1] in {"+node-list", "+fetch"} for call in calls))

    def test_ranking_auc(self) -> None:
        self.assertEqual(eval_replay.rank_auc([(90, True), (10, False)]), 1.0)
        self.assertEqual(eval_replay.rank_auc([(10, True), (90, False)]), 0.0)
        self.assertIsNone(eval_replay.rank_auc([(10, False)]))


if __name__ == "__main__":
    unittest.main()
