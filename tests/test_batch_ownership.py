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
import publish_batch as publish_batch_module
from publish_batch import publish_batch, delivered_candidates


def setUpModule():
    # 这些测试用的是假链接，发布前回读链接的网络检查单独在 test_media_and_links 里测。
    global _link_patch
    _link_patch = patch.object(publish_batch_module, "unreachable_links", return_value=[])
    _link_patch.start()


def tearDownModule():
    _link_patch.stop()

from curator import score_item
from review_answers import passing_answers

QUOTE = '作者核对了错误原文，修正后读者能独立验证结果。'


def complete_review():
    return {
        'status': 'passed',
        'answers': passing_answers(reader_takeaway={'quote': QUOTE}, has_substance={'quote': QUOTE}),
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

    def test_check_only_validates_without_registering_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_root(root)
            folder,_=self.batch(root,'dry-run')
            before={path.name:path.read_bytes() for path in folder.iterdir()}
            self.assertEqual(publish_batch(folder,'主力',root,check_only=True),folder.resolve())
            self.assertEqual({path.name:path.read_bytes() for path in folder.iterdir()},before)
            self.assertEqual(delivered_candidates(root/'topics'),[])
            publish_batch(folder,'主力',root)
            unscored,rows=self.batch(root,'dry-run-unscored')
            for row in rows: row.pop('score',None)
            (unscored/'candidates.json').write_text(json.dumps(rows))
            with self.assertRaises(ValueError):
                publish_batch(unscored,'主力2',root,check_only=True)  # duplicates the delivered batch
            other,_=self.batch(root,'dry-run-duplicate')
            with self.assertRaises(ValueError):
                publish_batch(other,'主力2',root,check_only=True)

    def test_history_check_catches_retitled_reposts_before_review(self):
        from history_check import duplicate_reason
        body='作者复盘了真实产品决策、失败原因和取舍条件，并给出可以复用的方法。'*120
        history=[{'id':'old','title':'原标题','link':'https://mp.weixin.qq.com/s/abc','content':body}]
        self.assertEqual(duplicate_reason({'link':'https://mp.weixin.qq.com/s/abc?from=rss','title':'x'},history),'原文链接已出现')
        self.assertIn('换标题转载',duplicate_reason({'link':'https://www.woshipm.com/ai/1.html','title':'新标题','content':'导语。'+body},history))
        self.assertEqual(duplicate_reason({'link':'https://example.org/new','title':'无关','content':'完全不同的内容，讲另一件事。'*120},history),'')

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
        (root / 'resources/editorial_profile.json').write_text(json.dumps({'default_topic_count':10}))

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

    def test_github_skill_focus_requires_chinese_article_and_localization_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_root(root)
            folder, rows = self.batch(root, 'github-life')
            for row in rows:
                row['github_skill_focus'] = True
                row['source_url'] = f"https://github.com/example/skill-{row['id']}"
                row['human_article_verified'] = True
            (folder / 'candidates.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, '中文文章解读'):
                publish_batch(folder, '主力', root)

            for row in rows:
                row['article_zh'] = '真人文章的中文转述，说明具体使用过程、可见结果、限制条件和国内用户需要调整的数据源。' * 4
                row['localization_review'] = {
                    'status': 'passed',
                    'evidence': '依赖本地文件或国内可用平台，中文用户不需要替换关键数据源即可完成主要流程。',
                }
            (folder / 'candidates.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, '配置与付费审查'):
                publish_batch(folder, '主力', root)

            for row in rows:
                row['setup_cost_review'] = {
                    'status': 'passed',
                    'evidence': '基础能力开源免费，只需本地 Node.js，首次安装一条命令，没有额外 API Key 或持续订阅。',
                }
                row['security_review'] = {
                    'status': 'passed',
                    'risk': 'high',
                    'evidence': '已审查 SKILL.md、脚本和测试，核心路径只读取公开来源并写入用户指定目录。',
                }
            (folder / 'candidates.json').write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, '安全审查未通过'):
                publish_batch(folder, '主力', root)

            for row in rows:
                row['security_review']['risk'] = 'low'
            (folder / 'candidates.json').write_text(json.dumps(rows))
            publish_batch(folder, '主力', root)
            self.assertTrue(json.loads((folder / 'run.json').read_text())['delivery_ready'])

    def batch(self, root, name, suffix=''):
        folder = root / 'topics' / name
        folder.mkdir(parents=True)
        rows = [{'id':str(i)+suffix, 'title':f'AI公开案例{i}{suffix}', 'link':f'https://example.org/{i}{suffix}',
                 'content':f'资料{i}{suffix}', 'score':100, 'recommended':True,
                 'manual_editorial_review':complete_review()} for i in range(5)]
        for row in rows:
            row['content'] = row['content'] + '作者核对了错误原文，修正后读者能独立验证结果。'
            row['manual_editorial_review']['source_sha256'] = hashlib.sha256(row['content'].encode()).hexdigest()
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
        for title in ('新的热点选题助手','AI视频剪辑实操','HyperFrames做动画','ContentOS工作流'):
            result=score_item({**base,'title':title},profile)
            self.assertTrue(result['penalty'])
        result=score_item({**base,'title':'Anthropic产品负责人访谈：用真实失败案例改进工作结果'},profile)
        self.assertNotIn('Token 成本对比',result['penalty'])
        self.assertNotIn('主题已写过',result['penalty'])

    def test_skill_routes_to_complete_editorial_judgment_library(self):
        skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        judgments = (ROOT / 'references/editorial-judgment.md').read_text(encoding='utf-8')
        calibration = (ROOT / 'references/editorial-calibration-cases.md').read_text(encoding='utf-8')
        protocol = (ROOT / 'references/feedback-learning-protocol.md').read_text(encoding='utf-8')
        self.assertIn('[编辑判断标准]', skill)
        self.assertIn('[反馈学习规则]', skill)
        self.assertIn('[评测方法]', skill)
        questions = json.loads((ROOT / 'resources/review_questions.json').read_text(encoding='utf-8'))['questions']
        for question in questions:
            self.assertIn(question['id'], judgments)
        self.assertIn('“良配”访谈', calibration)
        self.assertIn('换掉产品名、作者名和标题措辞', protocol)


if __name__=='__main__':
    unittest.main()


class SkillVersionGateTest(unittest.TestCase):
    def test_a_batch_run_on_an_old_skill_cannot_be_published(self):
        with patch("publish_batch.behind_remote", return_value="abc1234 收紧配图规则"):
            with self.assertRaises(ValueError) as caught:
                publish_batch(ROOT / "topics" / "2026-09-20-main-a", "主力", check_only=True)
        self.assertIn("旧版 Skill", str(caught.exception))
