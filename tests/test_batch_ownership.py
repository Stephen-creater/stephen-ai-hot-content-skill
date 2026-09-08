import json
import hashlib
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


def complete_review():
    return {
        'status': 'passed',
        'topic_appeal': '目标读者每天都会遇到这个具体 AI 工作问题。',
        'reader_change': '读者会从直接相信结果改为先核对事实和来源。',
        'material_increment': '正文提供失败案例、调整过程和可核验结果。',
        're_authorability': '移除作者身份和截图后，公共事实与方法链仍成立。',
        'durability': '方法不依赖短期版本，热点消失后仍可以复用。',
        'counterargument': '材料来自单一作者，存在经验外推过度的风险。',
        'decision_driver': '决定放行的是完整失败链与可复用的核验动作。',
    }


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

    def test_complete_human_evidence_can_override_editorial_risk_but_not_eligibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_root(root)
            folder,rows=self.batch(root,'reviewed-risk')
            rows[0]['recommended']=False
            rows[0]['editorial_decision']={'eligibility':{'status':'passed','failures':[]},'risk_signals':[{'code':'editorial_risk','evidence':'技术门槛需人工核实'}]}
            (folder/'candidates.json').write_text(json.dumps(rows))
            publish_batch(folder,'主力',root)
            saved=json.loads((folder/'candidates.json').read_text())
            self.assertEqual(saved[0]['editorial_decision']['final']['status'],'passed')

        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_root(root)
            folder,rows=self.batch(root,'hard-failure','x')
            distinct=('阅读核验','办公交付','产品访谈','知识管理','模型解释')
            for index,row in enumerate(rows):
                row['title']=f'AI{distinct[index]}完整材料'
            rows[0]['editorial_decision']={'eligibility':{'status':'failed','failures':[{'code':'locked_content'}]}}
            (folder/'candidates.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'客观资格门槛'):
                publish_batch(folder,'主力',root)

    def setup_root(self, root):
        (root / 'resources').mkdir()
        (root / 'resources/editorial_profile.json').write_text(json.dumps({'minimum_delivery_count':5,'minimum_non_github_candidates':4,'maximum_github_candidates':1}))

    def test_publish_rechecks_stale_material_risks_and_actual_short_text(self):
        for metadata in (
            {'penalty': '文章正文偏短，不足以支撑高质量二创'},
            {'editorial_decision': {'eligibility': {'status': 'passed'}, 'risk_signals': [{'evidence': '摘要不足以支撑高质量二创'}]}},
            {'content_form': 'article', 'content_status': 'fulltext', 'content': '只有观点，没有展开。'},
        ):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); self.setup_root(root)
                folder, rows = self.batch(root, 'stale')
                rows[0].update(metadata)
                (folder / 'candidates.json').write_text(json.dumps(rows))
                with self.assertRaisesRegex(ValueError, '发布复核未通过'):
                    publish_batch(folder, '主力', root)
                self.assertFalse(json.loads((folder / 'run.json').read_text())['delivery_ready'])

    def batch(self, root, name, suffix=''):
        folder = root / 'topics' / name
        folder.mkdir(parents=True)
        rows = [{'id':str(i)+suffix, 'title':f'AI公开案例{i}{suffix}', 'link':f'https://example.org/{i}{suffix}',
                 'content':f'资料{i}{suffix}', 'score':100, 'recommended':True,
                 'manual_editorial_review':complete_review()} for i in range(5)]
        for row in rows:
            row['content'] = row['content'] + '作者核对了错误原文，修正后读者能独立验证结果。'
            row['manual_editorial_review']['source_sha256'] = hashlib.sha256(row['content'].encode()).hexdigest()
            row['manual_editorial_review']['source_anchors'] = [
                {'dimension': dimension, 'quote': '作者核对了错误原文，修正后读者能独立验证结果。'}
                for dimension in ('material_increment', 're_authorability')]
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
        calibration = (ROOT / 'references/editorial-calibration-cases.md').read_text(encoding='utf-8')
        protocol = (ROOT / 'references/feedback-learning-protocol.md').read_text(encoding='utf-8')
        self.assertIn('[编辑判断模型]', skill)
        self.assertIn('[反馈学习协议]', skill)
        for preserved_rule in (
            '选题吸引力',
            '读者改变',
            '材料增量',
            '二创独立性',
            '长期价值',
        ):
            self.assertIn(preserved_rule, judgments)
        self.assertIn('“良配”访谈', calibration)
        self.assertIn('换掉产品名、作者名和标题措辞', protocol)


if __name__=='__main__':
    unittest.main()
