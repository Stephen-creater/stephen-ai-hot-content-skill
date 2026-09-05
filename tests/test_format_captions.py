import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from format_captions import restore_readability


class CaptionReadabilityTest(unittest.TestCase):
    def test_numeric_spoken_caption_is_not_dropped_as_cue_number(self):
        raw = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n2026\n\n2\n00:00:02.000 --> 00:00:04.000\n年需要核对数据\n"
        result = restore_readability(raw, "2026年需要核对数据。")
        self.assertEqual("".join(c for c in result if c.isalnum()), "2026年需要核对数据")

    def test_reference_cannot_change_model_names_or_wording(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n我们讨论的是模型Fable和Kimi\n\n00:00:03.000 --> 00:00:05.000\n下面这句话必须保留完整\n"
        reference = "我们讨论的是模型GPT和Kimi。\n\n下面这句话必须保留完整。"
        result = restore_readability(raw, reference)
        self.assertIn("Fable", result)
        self.assertNotIn("GPT", result)
        self.assertIn("下面这句话必须保留完整", result)
        self.assertNotIn("-->", result)
        self.assertIn("\n\n", result)

    def test_matching_reference_adds_readable_punctuation(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n这些公开材料足够完整\n\n00:00:03.000 --> 00:00:05.000\n我们还需要独立核验它们\n"
        result = restore_readability(raw, "这些公开材料足够完整。\n\n我们还需要独立核验它们。")
        self.assertIn("足够完整。\n\n我们", result)
