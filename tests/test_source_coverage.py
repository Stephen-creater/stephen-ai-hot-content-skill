from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from discovery_ledger import eligible_key, load_entries, record_attempt, stop_check, summarize
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
        entries = [{"recorded_at": now.isoformat(), "family": "twitter_builder_graph", "status": "blocked"}]
        report = audit_coverage(self.portfolio, self.sources, entries, {"exa_search", "github"}, now)
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
        report = audit_coverage(self.portfolio, self.sources, entries, now=now)
        self.assertEqual(report["access_coverage"], 10)
        self.assertEqual(report["rolling_attempt_coverage"], 0)
        entries.append({**base, "purpose": "discovery", "operation": "search"})
        report = audit_coverage(self.portfolio, self.sources, entries, now=now)
        self.assertEqual(report["rolling_attempt_coverage"], 10)
        empty = [{**base, "operation": "search", "result_count": 0}]
        self.assertEqual(audit_coverage(self.portfolio, self.sources, empty, now=now)["access_coverage"], 0)

    def test_stop_check_requires_coverage_and_two_rounds_without_new_material(self):
        required = sorted(row["id"] for row in self.portfolio["families"] if row["role"] == "candidate" and row["weight"] >= 8)

        def row(family, round_no, keys=(), channel="scrape_aihot", status="success", results=5, batch="b1", purpose="discovery", eligible=None):
            entry = {"batch": batch, "family": family, "round": round_no, "channel": channel, "status": status, "purpose": purpose,
                     "result_count": results, "eligible_count": len(keys) if eligible is None else eligible}
            if eligible is None:
                entry["eligible_keys"] = list(keys)
            return entry

        covered = [row(family, 1, keys=["a", "b"] if family == required[0] else []) for family in required]
        expansion = [row(required[0], 2, keys=["a"], channel="exa"), row(required[1], 3, channel="zhihu")]
        # Re-finding the same eligible items in later rounds is not new material.
        stopped = stop_check(covered + expansion + [row(required[0], 3, keys=["a", "b"])], "b1", self.portfolio)
        self.assertTrue(stopped["should_stop"], stopped["continue_reasons"])
        self.assertEqual(stopped["new_eligible_by_round"], {1: 2, 2: 0, 3: 0})
        self.assertEqual(stopped["recent_expansion_channels"], ["exa", "zhihu"])

        fresh = stop_check(covered + expansion + [row(required[0], 3, keys=["c"])], "b1", self.portfolio)
        self.assertFalse(fresh["should_stop"])
        self.assertEqual(fresh["recent_rounds_new_eligible"], 1)

        manual_without_keys = stop_check(covered + expansion + [row(required[0], 3, channel="v2ex", eligible=1)], "b1", self.portfolio)
        self.assertFalse(manual_without_keys["should_stop"])

        empty_expansion = covered + [row(required[0], 2, channel="exa", results=0), row(required[0], 3, channel="zhihu", results=0)]
        self.assertIn("至少需要 2 个", " ".join(stop_check(empty_expansion, "b1", self.portfolio)["continue_reasons"]))

        failed = [row(f, 1) for f in required[1:]] + [row(required[0], 1, status="failed"),
                                                    row(required[1], 2, channel="exa"), row(required[1], 3, channel="zhihu")]
        result = stop_check(failed, "b1", self.portfolio)
        self.assertFalse(result["should_stop"])
        self.assertEqual(result["missing_families"], [required[0]])

        all_blocked = [row(f, 1, status="blocked", results=0) for f in required] + [row("zhihu", 2, channel="exa"), row("zhihu", 3, channel="zhihu")]
        self.assertIn("全部受阻", " ".join(stop_check(all_blocked, "b1", self.portfolio)["continue_reasons"]))

        self.assertIn("至少需要两轮", " ".join(stop_check(covered, "b1", self.portfolio)["continue_reasons"]))
        unrounded = covered + [{**row(required[0], None), "round": None}]
        self.assertEqual(stop_check(unrounded, "b1", self.portfolio)["unrounded_records"], 1)
        noise = [row(f, 1, batch="b2") for f in required] + [row(f, 2, purpose="smoke") for f in required]
        self.assertEqual(stop_check(noise, "b1", self.portfolio)["rounds"], [])

    def test_stop_check_uses_shared_key_format_and_reports_blocked_families(self):
        required = sorted(row["id"] for row in self.portfolio["families"] if row["role"] == "candidate" and row["weight"] >= 8)
        link = "https://mp.weixin.qq.com/s/abc?from=rss"
        scrape_key = eligible_key("https://mp.weixin.qq.com/s/abc")
        self.assertEqual(eligible_key(link), scrape_key)
        self.assertEqual(eligible_key("already-a-hash"), "already-a-hash")

        def row(family, round_no, channel="scrape_aihot", keys=(), status="success", results=3):
            return {"batch": "b", "family": family, "round": round_no, "channel": channel, "status": status,
                    "purpose": "discovery", "result_count": results, "eligible_count": len(keys), "eligible_keys": list(keys)}

        base = [row(f, 1, keys=[scrape_key] if f == "wechat" else []) for f in required if f != "bilibili"]
        base.append(row("bilibili", 1, channel="bili-cli", status="blocked", results=0))
        rerun_only = base + [row("wechat", 2, keys=[scrape_key]), row("wechat", 3, keys=[scrape_key])]
        result = stop_check(rerun_only, "b", self.portfolio)
        self.assertFalse(result["should_stop"])
        self.assertEqual(result["blocked_families"], ["bilibili"])

        manual_same_article = rerun_only + [row("wechat", 3, channel="exa", keys=[eligible_key(link)]), row("wechat", 2, channel="zhihu")]
        stopped = stop_check(manual_same_article, "b", self.portfolio)
        self.assertTrue(stopped["should_stop"], stopped["continue_reasons"])
        self.assertEqual(stopped["recent_rounds_new_eligible"], 0)

    def test_ledger_rejects_invalid_round_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = {"batch": "b", "owner": "主力", "family": "wechat", "channel": "rss", "query": "q", "status": "success",
                    "result_count": 1, "fulltext_count": 1, "eligible_count": 0, "selected_count": 0,
                    "purpose": "discovery", "operation": "search", "evidence_url": ""}
            with self.assertRaises(ValueError):
                record_attempt(Path(tmp) / "l.jsonl", {**base, "round": -1})
            with self.assertRaises(ValueError):
                record_attempt(Path(tmp) / "l.jsonl", {**base, "eligible_keys": ["a"]})
            blocked = {**base, "status": "blocked", "result_count": 0, "fulltext_count": 0}
            with self.assertRaises(ValueError):
                record_attempt(Path(tmp) / "l.jsonl", blocked)
            with self.assertRaises(ValueError):
                record_attempt(Path(tmp) / "l.jsonl", {**blocked, "failure_type": "no_backend", "result_count": 2, "fulltext_count": 1})
            record_attempt(Path(tmp) / "l.jsonl", {**blocked, "failure_type": "no_backend"})
            record_attempt(Path(tmp) / "l.jsonl", {**base, "round": 2, "max_age_days": 45})
            self.assertEqual([row.get("round") for row in load_entries(Path(tmp) / "l.jsonl")], [None, 2])

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


class SourceGroupTest(unittest.TestCase):
    def test_rss_group_expands_with_defaults_and_joined_exclusions(self):
        from source_config import expand_sources

        config = {"sources": [
            {"name": "plain", "type": "web", "url": "https://a"},
            {"name": "组", "type": "rss_group", "family": "wechat",
             "defaults": {"priority": 4, "role": "candidate", "use_feed_content": True, "title_exclude_pattern": "早报"},
             "feeds": [{"name": "甲", "url": "https://f/1"},
                       {"name": "乙", "url": "https://f/2", "priority": 3, "title_exclude_pattern": "招聘"}]},
        ]}
        rows = expand_sources(config)
        self.assertEqual([r["name"] for r in rows], ["plain", "甲", "乙"])
        first, second = rows[1], rows[2]
        self.assertEqual((first["type"], first["family"], first["group"], first["priority"]), ("rss", "wechat", "组", 4))
        self.assertEqual(second["priority"], 3)
        self.assertRegex("AI 早报", second["title_exclude_pattern"])
        self.assertRegex("急招聘", second["title_exclude_pattern"])
        self.assertNotRegex("访谈", second["title_exclude_pattern"])

    def test_configured_sources_expand_to_unique_urls(self):
        from source_config import load_sources

        rows = load_sources()["sources"]
        urls = [r["url"] for r in rows]
        self.assertEqual(len(urls), len(set(urls)))
        names = [r["name"] for r in rows]
        self.assertEqual(len(names), len(set(names)), "来源名用于记账和失败记录，不能重名")
        for row in rows:
            self.assertIn("priority", row, row["name"])
            self.assertIn("category", row, row["name"])

    def test_tech_group_include_matches_ai_inside_chinese_titles(self):
        import re
        from source_config import load_sources

        tech = next(r for r in load_sources()["sources"] if r.get("group") == "大厂技术团队 Agent 实践")
        include = re.compile(tech["title_include_pattern"], re.I)
        for title in ("腾讯AI落地实践", "用AI写代码的一年", "Agent 评测方法"):
            self.assertRegex(title, include)
        for title in ("MAIL 系统迁移", "OpenAI 发布会", "分布式存储优化"):
            self.assertNotRegex(title, include)


if __name__ == "__main__":
    unittest.main()
