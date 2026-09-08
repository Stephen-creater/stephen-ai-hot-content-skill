from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editorial_judgment import (
    DIMENSIONS,
    build_decision_contract,
    classify_penalties,
    final_decision_record,
    validate_manual_review,
    validate_source_anchors,
)


def evidence_review(**overrides):
    review = {
        "status": "passed",
        "topic_appeal": "普通知识工作者每天都会遇到资料核对困难。",
        "reader_change": "读者会从直接采用回答改为返回原文核对事实。",
        "material_increment": "正文记录一次失败、两次调整和最终可核验结果。",
        "re_authorability": "移除作者身份与截图后，公共方法和因果链仍成立。",
        "durability": "方法不依赖某个短期版本，半年后仍能复用。",
        "counterargument": "案例只有一位作者，结论可能存在样本偏差。",
        "decision_driver": "完整失败链和可回查原文的动作构成决定性证据。",
    }
    review.update(overrides)
    return review


class EditorialJudgmentTest(unittest.TestCase):
    def test_fabricated_quotes_and_changed_body_fail(self):
        body = '团队原先只检查结果，后来发现过程错误会累积。'
        review = {'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
                  'source_anchors': [{'dimension': d, 'quote': body}
                                     for d in ('material_increment', 're_authorability')]}
        self.assertTrue(validate_source_anchors({'content': body, 'manual_editorial_review': review}).ok)
        self.assertFalse(validate_source_anchors({'content': body + '变化', 'manual_editorial_review': review}).ok)
        review['source_anchors'][0]['quote'] = '这段听起来很好的具体结果从未出现在正文里面。'
        self.assertFalse(validate_source_anchors({'content': body, 'manual_editorial_review': review}).ok)
    def test_profile_declares_generalizable_decision_contract(self):
        profile = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["schema_version"], 2)
        self.assertEqual(tuple(profile["decision_model"]["dimensions_in_order"]), DIMENSIONS)
        self.assertTrue(profile["decision_model"]["manual_review_required"])
        self.assertTrue(profile["decision_model"]["keyword_matches_are_risk_signals_not_verdicts"])
        self.assertFalse(profile["feedback_learning"]["blank_note_creates_rule"])
        self.assertIn("risk_signal_lexicon", profile)
        self.assertNotIn("editorial_fit", profile)

    def test_objective_failures_are_separate_from_editorial_risks(self):
        hard, risks = classify_penalties([
            "正文被登录、关注或付费墙截断，材料不完整",
            "技术细节过深，目标读者难以理解或使用",
        ])
        self.assertEqual(hard[0]["code"], "locked_content")
        self.assertEqual(risks[0]["code"], "editorial_risk")

    def test_risk_signal_does_not_claim_a_human_verdict(self):
        contract = build_decision_contract(
            {}, penalties=["技术细节过深，目标读者难以理解或使用"], score=80, minimum_score=48
        )
        self.assertEqual(contract["eligibility"]["status"], "passed")
        self.assertEqual(contract["machine_disposition"], "shortlist")
        self.assertTrue(contract["human_review_required"])
        self.assertTrue(all(row["verdict"] == "unassessed" for row in contract["editorial_dimensions"].values()))

        low_score = build_decision_contract(
            {}, penalties=["文章包含较多个人经历"], score=-20, minimum_score=48
        )
        self.assertEqual(low_score["machine_disposition"], "review")
        self.assertEqual(low_score["eligibility"]["status"], "passed")

    def test_hard_failure_blocks_before_editorial_judgment(self):
        contract = build_decision_contract(
            {}, penalties=["主题已写过，不重复推荐"], score=120, minimum_score=48
        )
        self.assertEqual(contract["eligibility"]["status"], "failed")
        self.assertEqual(contract["machine_disposition"], "blocked")
        self.assertEqual(contract["eligibility"]["failures"][0]["code"], "covered_topic")

    def test_insufficient_material_cannot_be_offset_by_score_or_review(self):
        for warning in ["文章正文偏短，不足以支撑高质量二创", "访谈摘要不足以支撑高质量二创"]:
            contract = build_decision_contract(
                {"manual_editorial_review": evidence_review()},
                penalties=[warning], score=120, minimum_score=48,
            )
            self.assertEqual(contract["machine_disposition"], "blocked")
            self.assertEqual(contract["eligibility"]["failures"][0]["code"], "insufficient_source_material")
        hard, risks = classify_penalties(["文章篇幅较短，但已完整展开失败、调整和结果"])
        self.assertEqual(hard, [])
        self.assertEqual(len(risks), 1)

    def test_manual_review_requires_all_five_dimensions_and_objection(self):
        incomplete = validate_manual_review({"status": "passed", "topic_appeal": "很有意思"})
        self.assertFalse(incomplete.ok)
        self.assertTrue(any("读者改变" in error for error in incomplete.errors))
        self.assertTrue(any("最强反对理由" in error for error in incomplete.errors))
        self.assertTrue(validate_manual_review(evidence_review()).ok)

    def test_final_record_is_auditable(self):
        item = {"manual_editorial_review": evidence_review()}
        record = final_decision_record(item)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(set(record["dimensions"]), set(DIMENSIONS))
        self.assertIn("决定性证据", record["decision_driver"])

    def test_surface_feature_never_satisfies_dimension_evidence(self):
        contract = build_decision_contract(
            {"title": "某创始人的真实第一人称访谈"},
            penalties=[],
            score=100,
            minimum_score=48,
        )
        self.assertEqual(contract["machine_disposition"], "shortlist")
        self.assertEqual(contract["editorial_dimensions"]["re_authorability"]["verdict"], "unassessed")
        reviewed = build_decision_contract(
            {"manual_editorial_review": evidence_review()},
            penalties=[],
            score=100,
            minimum_score=48,
        )
        self.assertEqual(reviewed["editorial_dimensions"]["re_authorability"]["verdict"], "supported")


if __name__ == "__main__":
    unittest.main()
