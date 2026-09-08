import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from scrape_aihot import hydrate, inbox_item, load_inbox, fetch_youtube_transcript
from curator import score_item
from report import generate_report
from discovery_history import delivered_candidates


class MaterialCompletenessTest(unittest.TestCase):
    def test_delivered_unreviewed_items_are_not_fetched_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = root / 'topics' / 'one'
            batch.mkdir(parents=True)
            (batch / 'run.json').write_text(json.dumps({'delivery_registered': True}))
            (batch / 'candidates.json').write_text(json.dumps([{'id': 'x', 'link': 'https://example.org/pending'}]))
            inbox = root / 'inbox.json'
            inbox.write_text(json.dumps([{'url': 'https://example.org/pending'}]))
            known = {r['link'] for r in delivered_candidates(root / 'topics')}
            with patch('scrape_aihot.inbox_item') as read:
                self.assertEqual(load_inbox(inbox, {}, known), [])
                read.assert_not_called()
    def test_original_title_survives_editorial_reframing(self):
        row = {'id': 'x', 'title': '编辑重写', 'source_title': '原文其实谈某公司的融资',
               'title_zh': '普通人立刻能用的方法', 'link': 'https://example.org/x', 'score': 10}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'index.html'
            generate_report([row], path, 'test')
            page = path.read_text()
            links = path.with_name('links.md').read_text()
        self.assertIn('1. 原文其实谈某公司的融资</a>', page)
        self.assertIn('拟议切口（非原文标题）：普通人立刻能用的方法', page)
        self.assertIn('[原文其实谈某公司的融资]', links)
    def test_chinese_metadata_cannot_hide_an_english_body(self):
        profile = json.loads((ROOT / 'resources/editorial_profile.json').read_text())
        item = score_item({'title': 'AI 实用方法', 'language': 'zh', 'content_status': 'fulltext',
                           'content': 'This is an English transcript of a long discussion. ' * 100}, profile)
        self.assertIn('body_language_mismatch', [f['code'] for f in item['editorial_decision']['eligibility']['failures']])
    def test_chinese_subtitles_win_over_alphabetically_first_english(self):
        def download(command, **kwargs):
            folder = Path(command[command.index('-o') + 1]).parent
            (folder / 'clip.en.vtt').write_text('English words only. ' * 50)
            (folder / 'clip.zh-Hans.vtt').write_text('完整中文字幕保留了原始结论。' * 50)
            return ''
        with patch('scrape_aihot.shutil.which', return_value='/bin/yt-dlp'), patch('scrape_aihot.subprocess.check_output', side_effect=download):
            text = fetch_youtube_transcript('https://www.youtube.com/watch?v=sample')
        self.assertIn('完整中文字幕', text)
        self.assertNotIn('English words', text)
    def test_reviewed_urls_are_skipped_before_expensive_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'inbox.json'
            path.write_text(json.dumps([{'url': 'https://example.org/old?utm_source=x'}, {'url': 'https://example.org/new'}]))
            with patch('scrape_aihot.inbox_item', side_effect=lambda row, settings: row) as read:
                rows = load_inbox(path, {}, {'https://example.org/old'})
            self.assertEqual(len(rows), 1)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(rows[0]['url'], 'https://example.org/new')
    def test_web_keeps_end_and_paragraphs_beyond_old_limit(self):
        body = ('真实经历及限制条件。\n\n' * 800) + '文末决定性反例：这次试验没有成功。'
        with patch('scrape_aihot.requests.get') as get, patch('scrape_aihot.trafilatura.extract', return_value=body), patch('scrape_aihot.trafilatura.bare_extraction', return_value={}):
            response = get.return_value.__enter__.return_value
            response.iter_content.return_value = [b'<html>body</html>']
            response.encoding = 'utf-8'
            item = hydrate({'link': 'https://example.org/article'}, {'request_timeout_seconds': 1, 'max_article_bytes': 1000})
        self.assertEqual(item['content'], body)
        self.assertEqual(item['content_status'], 'fulltext')

    def test_byte_limit_is_partial_not_fulltext(self):
        with patch('scrape_aihot.requests.get') as get, patch('scrape_aihot.trafilatura.extract', return_value='可解析前半段'), patch('scrape_aihot.trafilatura.bare_extraction', return_value={}):
            response = get.return_value.__enter__.return_value
            response.iter_content.return_value = [b'x' * 30]
            response.encoding = 'utf-8'
            item = hydrate({'link': 'https://example.org/article'}, {'request_timeout_seconds': 1, 'max_article_bytes': 20})
        self.assertTrue(item['content_truncated'])
        self.assertEqual(item['content_status'], 'partial')

    def test_explicit_body_keeps_more_than_twenty_thousand_chars(self):
        body = ('完整正文和限制条件。\n' * 2500) + '尾部独有结论'
        with patch('scrape_aihot.requests.get') as get:
            get.return_value.content = body.encode()
            get.return_value.encoding = 'utf-8'
            item = inbox_item({'url': 'https://example.org/article', 'content_url': 'https://example.org/text'}, {'request_timeout_seconds': 1, 'max_article_bytes': 1500000})
        self.assertEqual(item['content'], body)

    def test_local_transcript_keeps_late_conclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'transcript.txt'
            path.write_text('\n'.join(f'第{i}句：这里讨论真实失败以及后续修改。' for i in range(1600)) + '\n最后的结论是实验尚未成立。', encoding='utf-8')
            item = inbox_item({'url': 'https://example.org/video', 'platform': 'youtube', 'transcript_path': str(path)}, {})
        self.assertGreater(len(item['content']), 20000)
        self.assertIn('最后的结论是实验尚未成立', item['content'])


if __name__ == '__main__':
    unittest.main()
