from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import transcribe_podcasts
from transcribe_audio import save


class PodcastTranscriptTest(unittest.TestCase):
    def test_only_episodes_without_a_transcript_are_picked_newest_first(self):
        items = [
            {"title": "已有逐字稿", "link": "https://x/1", "audio_url": "a", "content_status": "transcript", "source_priority": 5},
            {"title": "旧一期", "link": "https://x/2", "audio_url": "b", "published": "2026-09-01", "source_priority": 4},
            {"title": "新一期", "link": "https://x/3", "audio_url": "c", "published": "2026-09-19", "source_priority": 4},
            {"title": "没有音频", "link": "https://x/4", "source_priority": 5},
            {"title": "已登记过", "link": "https://x/5", "audio_url": "e", "published": "2026-09-20", "source_priority": 5},
        ]
        picked = transcribe_podcasts.pick(items, 2, {"https://x/5"})
        self.assertEqual([row["title"] for row in picked], ["新一期", "旧一期"])

    def test_a_transcribed_episode_is_registered_with_its_transcript(self):
        items = [{"title": "一期访谈", "link": "https://x/6", "audio_url": "https://audio/6",
                  "published": "2026-09-20", "source_priority": 5, "source_name": "某播客"}]
        with tempfile.TemporaryDirectory() as raw:
            inbox = Path(raw) / "inbox.json"
            with patch("transcribe_podcasts.transcribe", return_value="嘉宾讲了三个判断。" * 60), \
                 patch("transcribe_podcasts.save", side_effect=lambda text, title: Path(raw) / "t.md"):
                done = transcribe_podcasts.run(items, limit=1, inbox=inbox)
            rows = json.loads(inbox.read_text(encoding="utf-8"))
        self.assertTrue(done[0]["ok"])
        self.assertEqual(rows[0]["platform"], "xiaoyuzhou")
        self.assertTrue(rows[0]["transcript_path"].endswith("t.md"))

    def test_a_failed_episode_is_reported_not_registered(self):
        items = [{"title": "坏音频", "link": "https://x/7", "audio_url": "https://audio/7", "source_priority": 5}]
        with tempfile.TemporaryDirectory() as raw:
            inbox = Path(raw) / "inbox.json"
            with patch("transcribe_podcasts.transcribe", side_effect=RuntimeError("音频打不开")):
                done = transcribe_podcasts.run(items, limit=1, inbox=inbox)
            self.assertFalse(inbox.exists())
        self.assertFalse(done[0]["ok"])
        self.assertIn("音频打不开", done[0]["note"])

    def test_the_saved_transcript_says_it_is_a_machine_draft(self):
        with tempfile.TemporaryDirectory() as raw:
            path = save("一段转写。", "某期节目", Path(raw))
            self.assertIn("未校对", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
