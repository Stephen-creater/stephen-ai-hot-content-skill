from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from feedback_audit import audit_feedback


class FeedbackAuditTest(unittest.TestCase):
    def test_audit_accepts_single_exported_feedback_object(self):
        payload = {
            "generated_at": "batch-export",
            "batch_owner": "主力2",
            "reviews": {"a": {"status": "selected", "note": "还不错"}},
            "candidates": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection_feedback.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            report = audit_feedback(path)
        self.assertEqual(report["batch_count"], 1)
        self.assertEqual(report["review_count"], 1)
        self.assertEqual(report["status_counts"], {"selected": 1})
        self.assertEqual(report["invalid_records"], [])

    def test_non_object_export_is_reported_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "selection_feedback.json"
            path.write_text(json.dumps("not a feedback object"), encoding="utf-8")
            report = audit_feedback(path)
        self.assertEqual(report["batch_count"], 0)
        self.assertIn("must be an object", report["invalid_records"][0]["error"])

    def test_audit_counts_every_decision_without_exporting_notes(self):
        rows = [
            {
                "generated_at": "batch-a",
                "batch_owner": "主力",
                "reviews": {
                    "a": {"status": "selected", "note": "这个题已经写过了"},
                    "b": {"status": "rejected", "note": ""},
                },
                "candidates": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            },
            {
                "generated_at": "batch-b",
                "batch_owner": "主力2",
                "reviews": {"b": {"status": "pending", "note": "稍后再看"}},
                "candidates": [{"id": "b", "title": "B"}],
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.jsonl"
            path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
            report = audit_feedback(path)
        self.assertEqual(report["batch_count"], 2)
        self.assertEqual(report["review_count"], 3)
        self.assertEqual(report["status_counts"], {"selected": 1, "rejected": 1, "pending": 1})
        self.assertEqual(report["unexplained_decisions"][0]["id"], "b")
        self.assertEqual(report["interpretation_queue"][0]["type"], "topic_state")
        self.assertEqual(report["repeated_candidate_decisions"][0]["occurrences"], 2)
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("这个题已经写过了", rendered)
        self.assertNotIn("稍后再看", rendered)
        self.assertTrue(report["safe_summary_only"])

    def test_invalid_json_is_reported_without_stopping_valid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.jsonl"
            path.write_text('{bad json}\n{"generated_at":"ok","reviews":{}}', encoding="utf-8")
            report = audit_feedback(path)
        self.assertEqual(report["batch_count"], 1)
        self.assertEqual(len(report["invalid_records"]), 1)


class SourceYieldTest(unittest.TestCase):
    def test_latest_decision_wins_and_wechat_groups_by_account(self):
        from source_yield import source_yield

        first = {
            "generated_at": "b1",
            "reviews": {"a": {"status": "rejected"}, "b": {"status": "selected"}, "c": {"status": "pending"}},
            "candidates": [
                {"id": "a", "title": "A", "link": "https://mp.weixin.qq.com/s/1", "source_name": "Z Finance / 某编译"},
                {"id": "b", "title": "B", "link": "https://www.zhihu.com/p/1", "source_name": "知乎"},
                {"id": "c", "title": "C", "link": "https://www.zhihu.com/p/2", "source_name": "知乎"},
            ],
        }
        second = {"generated_at": "b2", "reviews": {"a": {"status": "selected"}}, "candidates": []}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in (first, second)), encoding="utf-8")
            rows = {row["source"]: row for row in source_yield(path)}
        self.assertEqual(rows["Z Finance"]["selected"], 1)
        self.assertEqual(rows["Z Finance"]["rejected"], 0)
        self.assertEqual(rows["zhihu.com"]["decided"], 1)
        self.assertEqual(rows["zhihu.com"]["smoothed_rate"], 0.4)


if __name__ == "__main__":
    unittest.main()


class BatchLevelTest(unittest.TestCase):
    def test_batch_level_counts_passes_and_positions(self):
        records = [
            {"generated_at": "b1", "candidates": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "reviews": {"a": {"status": "rejected"}, "b": {"status": "rejected"}, "c": {"status": "selected", "reasons": ["干货足"]}}},
            {"generated_at": "b2", "candidates": [{"id": "d"}, {"id": "e"}], "reviews": {"d": {"status": "rejected"}, "e": {"status": "rejected"}}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feedback.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
            report = audit_feedback(path)
        level = report["batch_level"]
        self.assertEqual((level["batches"], level["batches_with_a_pass"], level["effective_batch_rate"]), (2, 1, 0.5))
        self.assertEqual(level["selected_per_batch"], 0.5)
        self.assertEqual((level["selected_in_top_5"], level["selected_positions_known"]), (1, 1))
        self.assertEqual(report["batches"][0]["selected_positions"], [3])
