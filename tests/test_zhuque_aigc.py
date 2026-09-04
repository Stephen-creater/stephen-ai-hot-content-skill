from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from zhuque_aigc import ZhuqueClient, ZhuqueConfig, apply_policy, estimate_text_cost_yuan, load_config, normalize_result
from report import generate_report


DOCUMENTED_RESPONSE = {
    "status": "success",
    "softmax_confidence": 0.9274,
    "ratio_confidence": 1.0,
    "labels_ratio": {"0": 0.0001, "1": 0.0001, "2": 0.9999},
    "segment_labels": [
        {"text": "hello world", "label": 2, "conf": 0.9274, "order": 1, "position": [0, 11]}
    ],
    "msg": "",
}


class ZhuqueAigcTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ZhuqueConfig(gateway="https://example.test", api_key="secret")

    def test_documented_three_class_response_is_normalized(self) -> None:
        result = normalize_result(DOCUMENTED_RESPONSE)
        self.assertEqual(result["ratios"], {"human": 0.0001, "ai": 0.0001, "suspected_ai": 0.9999})
        self.assertEqual(result["segments"][0]["label"], 2)
        self.assertEqual(result["segments"][0]["position"], [0, 11])

    def test_cost_estimate_rounds_each_thousand_characters_up(self) -> None:
        self.assertEqual(estimate_text_cost_yuan("a"), 0.04)
        self.assertEqual(estimate_text_cost_yuan("a" * 22000), 0.88)

    def test_almost_all_ai_is_hard_rejected(self) -> None:
        detection = normalize_result({**DOCUMENTED_RESPONSE, "labels_ratio": {"0": 0.01, "1": 0.99, "2": 0.0}})
        result = apply_policy({"score": 120, "recommended": True, "penalty": ""}, detection, self.config)
        self.assertFalse(result["recommended"])
        self.assertEqual(result["aigc_policy"], "rejected")

    def test_majority_suspected_ai_is_downranked(self) -> None:
        detection = normalize_result({**DOCUMENTED_RESPONSE, "labels_ratio": {"0": 0.2, "1": 0.1, "2": 0.7}})
        result = apply_policy({"score": 120, "recommended": True, "penalty": ""}, detection, self.config)
        self.assertTrue(result["recommended"])
        self.assertEqual(result["score"], 85)
        self.assertEqual(result["aigc_policy"], "downranked")

    def test_report_exposes_ratios_and_segment_labels(self) -> None:
        detection = normalize_result(DOCUMENTED_RESPONSE)
        item = {
            "id": "aigc-example",
            "title": "朱雀返回结构示例",
            "score": 80,
            "recommended": True,
            "selected_by_default": False,
            "aigc_policy": "downranked",
            "aigc_detection": detection,
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.html"
            generate_report([item], output, "2026-09-04-200000")
            rendered = output.read_text(encoding="utf-8")
        self.assertIn("人工 0.0%", rendered)
        self.assertIn("疑似 AI 100.0%", rendered)
        self.assertIn("hello world", rendered)
        self.assertIn("朱雀 AIGC 检测 · 已降权", rendered)

    def test_client_requests_unmerged_segments_and_caches_by_text(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = DOCUMENTED_RESPONSE
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            client = ZhuqueClient(self.config, cache_path=cache)
            with patch("zhuque_aigc.requests.post", return_value=response) as post:
                first = client.classify_text("hello world")
                second = client.classify_text("hello world")
            self.assertFalse(first["cached"])
            self.assertTrue(second["cached"])
            self.assertTrue(client.has_cached_text("hello world"))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs["json"], {"text": "hello world", "is_merge": False})

    def test_partial_config_fails_without_revealing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zhuque.json"
            path.write_text(json.dumps({"api_key": "do-not-print"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "配置不完整"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
