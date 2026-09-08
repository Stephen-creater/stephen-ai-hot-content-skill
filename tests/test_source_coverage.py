from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery_ledger import load_entries, record_attempt, summarize
from source_coverage import audit_coverage


class SourceCoverageTest(unittest.TestCase):
    def setUp(self):
        self.portfolio = json.loads((ROOT / "resources/source_portfolio.json").read_text(encoding="utf-8"))
        self.sources = json.loads((ROOT / "resources/content_curator_sources.json").read_text(encoding="utf-8"))

    def test_portfolio_weights_sum_to_one_hundred(self):
        self.assertEqual(sum(row["weight"] for row in self.portfolio["families"]), 100)
        self.assertEqual(len({row["id"] for row in self.portfolio["families"]}), len(self.portfolio["families"]))

    def test_coverage_distinguishes_connection_configuration_and_attempt(self):
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        doctor = {
            "web": {"active_backend": "Jina"}, "rss": {"active_backend": "feedparser"},
            "exa_search": {"active_backend": None}, "twitter": {"active_backend": None},
            "bilibili": {"active_backend": "bili-cli"}, "youtube": {"active_backend": "yt-dlp"},
            "xiaoyuzhou": {"active_backend": None}, "reddit": {"active_backend": None},
            "v2ex": {"active_backend": "public"}, "github": {"active_backend": None},
            "xiaohongshu": {"active_backend": None},
        }
        entries = [{"recorded_at": now.isoformat(), "family": "twitter_builder_graph", "status": "blocked"}]
        report = audit_coverage(self.portfolio, doctor, self.sources, entries, {"exa_search", "github"}, now)
        self.assertLess(report["access_coverage"], report["access_target"])
        self.assertGreater(report["access_coverage"], report["configured_automation_coverage"])
        twitter = next(row for row in report["families"] if row["id"] == "twitter_builder_graph")
        self.assertEqual(twitter["access_fraction"], 0)
        self.assertTrue(twitter["attempted_in_window"])
        self.assertFalse(twitter["successful_in_window"])

    def test_ledger_is_locked_validated_and_reports_yield(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            entry = {
                "batch": "b1", "owner": "主力", "family": "chinese_longform_web", "channel": "exa",
                "query": "AI产品复盘", "status": "success", "result_count": 10,
                "fulltext_count": 4, "eligible_count": 2, "selected_count": 1, "failure_type": "",
            }
            record_attempt(path, entry)
            report = summarize(load_entries(path), "b1")
            self.assertEqual(report["attempt_count"], 1)
            self.assertEqual(report["by_family"]["chinese_longform_web"]["fulltext_yield"], 0.4)
            self.assertEqual(report["by_family"]["chinese_longform_web"]["selection_yield"], 0.5)
            with self.assertRaises(ValueError):
                record_attempt(path, {**entry, "selected_count": 5})


if __name__ == "__main__":
    unittest.main()
