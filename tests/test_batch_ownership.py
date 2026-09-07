import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import import_feedback as feedback
from publish_batch import publish_batch, delivered_candidates
from curator import score_item


class BatchOwnershipTest(unittest.TestCase):
    def test_quantity_ready_draft_is_not_a_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_root(root)
            a,_=self.batch(root,'draft')
            (a/'run.json').write_text(json.dumps({'delivery_ready':True,'input_count':200}))
            self.assertEqual(delivered_candidates(root/'topics'),[])
            (a/'run.json').write_text(json.dumps({'delivery_ready':True,'manual_editorial_review':True}))
            self.assertEqual(len(delivered_candidates(root/'topics')),5)

    def test_concurrent_batches_cannot_both_publish_same_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_root(root)
            a,_=self.batch(root,'a'); b,_=self.batch(root,'b')
            def attempt(pair):
                try:
                    publish_batch(pair[0],pair[1],root)
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes=list(pool.map(attempt,[(a,'主力'),(b,'主力2')]))
            self.assertEqual(sorted(outcomes),[False,True])

    def setup_root(self, root):
        (root / 'resources').mkdir()
        (root / 'resources/editorial_profile.json').write_text(json.dumps({'minimum_delivery_count':5,'minimum_non_github_candidates':4,'maximum_github_candidates':1}))

    def batch(self, root, name, suffix=''):
        folder = root / 'topics' / name
        folder.mkdir(parents=True)
        rows = [{'id':str(i)+suffix, 'title':f'AI公开案例{i}{suffix}', 'link':f'https://example.org/{i}{suffix}',
                 'content':f'资料{i}{suffix}', 'score':100, 'recommended':True,
                 'manual_editorial_review':{'status':'passed'}} for i in range(5)]
        (folder / 'candidates.json').write_text(json.dumps(rows))
        (folder / 'run.json').write_text(json.dumps({'delivery_ready':False}))
        return folder, rows

    def test_publish_marks_owner_and_blocks_other_pending_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.setup_root(root)
            first, rows = self.batch(root,'first')
            publish_batch(first,'主力',root)
            html = (first/'index.html').read_text()
            self.assertIn('selection_feedback-主力-first.json',html)
            self.assertIn('batch_owner:"主力"',html)
            self.assertEqual(len(delivered_candidates(root/'topics')),5)
            other,_ = self.batch(root,'second')
            with self.assertRaisesRegex(ValueError,'已推送'):
                publish_batch(other,'主力2',root)
            self.assertFalse(json.loads((other/'run.json').read_text())['delivery_ready'])
            with self.assertRaisesRegex(ValueError,'另一个任务'):
                publish_batch(first,'主力2',root)

    def test_wrong_batch_owner_or_candidate_order_never_imports_or_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder,rows=self.batch(root,'batch1')
            (folder/'run.json').write_text(json.dumps({'batch_owner':'主力'}))
            payload={'generated_at':'batch1','batch_owner':'主力','exported_at':'2026-09-06T02:00:00Z','candidates':rows,'reviews':{}}
            source=root/'export.json'
            for wrong in ({'generated_at':'batch2'},{'batch_owner':'主力2'},{'candidates':rows[::-1]},{'reviews':{'alien':{'status':'selected'}}}):
                source.write_text(json.dumps({**payload,**wrong}))
                with patch.object(feedback,'ROOT',root), self.assertRaises(ValueError):
                    feedback.import_feedback(source,expected_batch='batch1',expected_owner='主力')
                self.assertTrue(source.exists())
                self.assertFalse((root/'.local/editorial_feedback.jsonl').exists())
            source.write_text(json.dumps(payload))
            with patch.object(feedback,'ROOT',root):
                target,_=feedback.import_feedback(source,expected_batch='batch1',expected_owner='主力')
            self.assertFalse(source.exists())
            self.assertTrue(feedback.already_imported(target,payload['exported_at'],payload))

    def test_editorial_exclusions_and_concrete_interview(self):
        profile=json.loads((ROOT/'resources/editorial_profile.json').read_text())
        base={'link':'https://example.org/new','language':'zh','maturity':'secondary','content_status':'fulltext','content_form':'article','summary':'AI公开方法与证据','content':'这份完整材料讨论真实任务的反馈与验证方法。'*160}
        for title in ('新的热点选题助手','AI视频剪辑实操','HyperFrames做动画','ContentOS工作流','18个模型统计108次财报，谁最快、最准、最便宜？'):
            result=score_item({**base,'title':title},profile)
            self.assertFalse(result['recommended'])
        result=score_item({**base,'title':'Anthropic产品负责人访谈：用真实失败案例改进工作结果'},profile)
        self.assertNotIn('Token 成本对比',result['penalty'])
        self.assertNotIn('主题已写过',result['penalty'])

    def test_skill_routes_to_complete_editorial_judgment_library(self):
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        judgments = (ROOT / 'references/editorial-judgment.md').read_text(encoding='utf-8')
        self.assertIn('完整读取 [编辑判断与历史校准库]', skill)
        self.assertIn('不能用本节摘要替代', skill)
        for preserved_rule in (
            '最新反馈明确肯定“良配”这类材料',
            '二创独立性优先于实测真实性',
            'GitHub 候选不仅要实时核验至少 100 Star',
            '历史去重必须比较正文',
        ):
            self.assertIn(preserved_rule, judgments)


if __name__=='__main__':
    unittest.main()
