import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_replay  # noqa: E402
from curator import review_hint_deduction  # noqa: E402

PROFILE = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
CURATOR_SOURCE = (ROOT / "scripts/curator.py").read_text(encoding="utf-8")


class ReviewHintPolicyTest(unittest.TestCase):
    def test_every_downrank_hint_exists_in_the_scorer(self) -> None:
        for hint in PROFILE["review_hint_policy"]["downrank"]:
            self.assertIn(f'"{hint}"', CURATOR_SOURCE, hint)

    def test_ordinary_hints_cost_nothing_and_downrank_is_capped(self) -> None:
        downrank = PROFILE["review_hint_policy"]["downrank"]
        self.assertEqual(review_hint_deduction([("只是一个需要核实的提示", 80)], PROFILE), 0)
        self.assertEqual(review_hint_deduction([(downrank[0], 45)], PROFILE), 10)
        self.assertEqual(review_hint_deduction([(hint, 80) for hint in downrank[:5]], PROFILE), 20)

    def test_objective_failures_keep_full_weight(self) -> None:
        self.assertEqual(review_hint_deduction([("超过时效范围", 60)], PROFILE), 60)


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
            items = {item["id"]: item for item in eval_replay.collect(self.feedback(Path(tmp)))}
        self.assertEqual(items["keep"]["label_strength"], "strong")
        self.assertEqual(items["drop"]["label_strength"], "weak")
        self.assertEqual(items["thin"]["label_strength"], "weak")
        self.assertFalse(items["thin"]["judgeable"])
        self.assertEqual({item["split"] for item in items.values()}, {eval_replay.split_for("batch-1")})

    def test_blind_export_hides_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = eval_replay.collect(self.feedback(Path(tmp)))
        rows = eval_replay.export_blind(items, "all", None)
        self.assertEqual({row["id"] for row in rows}, {"keep", "drop"})
        for row in rows:
            self.assertNotIn("label", row)
            self.assertNotIn("reasons", row)

    def test_score_reports_recall_precision_and_misses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items = eval_replay.collect(self.feedback(Path(tmp)))
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

    def test_ranking_auc(self) -> None:
        self.assertEqual(eval_replay.rank_auc([(90, True), (10, False)]), 1.0)
        self.assertEqual(eval_replay.rank_auc([(10, True), (90, False)]), 0.0)
        self.assertIsNone(eval_replay.rank_auc([(10, False)]))


if __name__ == "__main__":
    unittest.main()
