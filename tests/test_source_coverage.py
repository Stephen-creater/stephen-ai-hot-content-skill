from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery_ledger import load_entries, record_attempt, stop_check, summarize
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
        self.assertEqual(report["access_coverage"], 0)
        self.assertEqual(report["rolling_attempt_coverage"], 0)
        twitter = next(row for row in report["families"] if row["id"] == "twitter_builder_graph")
        self.assertEqual(twitter["access_fraction"], 0)
        self.assertTrue(twitter["attempted_in_window"])
        self.assertFalse(twitter["successful_in_window"])

    def test_only_fresh_nonempty_operation_evidence_counts(self):
        now = datetime(2026, 9, 8, tzinfo=timezone.utc)
        base = {"recorded_at": now.isoformat(), "family": "twitter_builder_graph",
                "status": "success", "result_count": 2, "channel": "ego-browser",
                "purpose": "smoke", "evidence_url": "https://x.com/search?q=AI"}
        entries = [{**base, "operation": op} for op in ("search", "read", "author")]
        report = audit_coverage(self.portfolio, {}, self.sources, entries, now=now)
        self.assertEqual(report["access_coverage"], 10)
        self.assertEqual(report["rolling_attempt_coverage"], 0)
        entries.append({**base, "purpose": "discovery", "operation": "search"})
        report = audit_coverage(self.portfolio, {}, self.sources, entries, now=now)
        self.assertEqual(report["rolling_attempt_coverage"], 10)
        empty = [{**base, "operation": "search", "result_count": 0}]
        self.assertEqual(audit_coverage(self.portfolio, {}, self.sources, empty, now=now)["access_coverage"], 0)

    def test_stop_check_requires_coverage_window_and_two_stagnant_rounds(self):
        required = sorted(row["id"] for row in self.portfolio["families"] if row["role"] == "candidate" and row["weight"] >= 8)

        def row(family, round_no, eligible=0, status="success", window=45, batch="b1", purpose="discovery"):
            return {"batch": batch, "family": family, "round": round_no, "eligible_count": eligible,
                    "status": status, "max_age_days": window, "purpose": purpose}

        covered = [row(family, 1) for family in required]
        stopped = stop_check(covered + [row(required[0], 2)], "b1", self.portfolio, 45)
        self.assertTrue(stopped["should_stop"])
        self.assertEqual(stopped["missing_families"], [])

        failed_family = [row(f, 1) for f in required[1:]] + [row(required[0], 1, status="failed"), row(required[1], 2)]
        result = stop_check(failed_family, "b1", self.portfolio, 45)
        self.assertFalse(result["should_stop"])
        self.assertEqual(result["missing_families"], [required[0]])

        narrow = [row(f, 1, window=14) for f in required] + [row(required[0], 2, window=14)]
        self.assertIn("时间窗", " ".join(stop_check(narrow, "b1", self.portfolio, 45)["continue_reasons"]))

        still_finding = covered + [row(required[0], 2, eligible=1)]
        self.assertFalse(stop_check(still_finding, "b1", self.portfolio, 45)["should_stop"])

        one_round = stop_check(covered, "b1", self.portfolio, 45)
        self.assertFalse(one_round["should_stop"])
        other_batch_and_smoke = [row(f, 1, batch="b2") for f in required] + [row(f, 2, purpose="smoke") for f in required]
        self.assertEqual(stop_check(other_batch_and_smoke, "b1", self.portfolio, 45)["rounds"], [])

    def test_ledger_rejects_invalid_round_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = {"batch": "b", "owner": "主力", "family": "wechat", "channel": "rss", "query": "q", "status": "success",
                    "result_count": 1, "fulltext_count": 1, "eligible_count": 0, "selected_count": 0,
                    "purpose": "discovery", "operation": "search", "evidence_url": ""}
            with self.assertRaises(ValueError):
                record_attempt(Path(tmp) / "l.jsonl", {**base, "round": -1})
            record_attempt(Path(tmp) / "l.jsonl", {**base, "round": 2, "max_age_days": 45})
            self.assertEqual(load_entries(Path(tmp) / "l.jsonl")[0]["round"], 2)

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
