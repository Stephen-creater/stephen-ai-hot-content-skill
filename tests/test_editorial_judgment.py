from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_answers import passing_answers  # noqa: E402
from editorial_judgment import (
    QUESTION_IDS,
    build_decision_contract,
    classify_penalties,
    final_decision_record,
    validate_manual_review,
    validate_source_anchors,
)


def evidence_review(**overrides):
    review = {
        "status": "passed",
        "answers": passing_answers(),
        "counterargument": "案例只有一位作者，结论可能存在样本偏差。",
        "decision_driver": "完整失败链和可回查原文的动作构成决定性证据。",
    }
    review.update(overrides)
    return review


class EditorialJudgmentTest(unittest.TestCase):
    def test_fabricated_quotes_and_changed_body_fail(self):
        body = '团队原先只检查结果，后来发现过程错误会累积。'
        answers = passing_answers(reader_takeaway={"quote": body}, has_substance={"quote": body})
        review = {'source_sha256': hashlib.sha256(body.encode()).hexdigest(), 'answers': answers}
        self.assertTrue(validate_source_anchors({'content': body, 'manual_editorial_review': review}).ok)
        self.assertFalse(validate_source_anchors({'content': body + '变化', 'manual_editorial_review': review}).ok)
        review['answers']['has_substance']['quote'] = '这段听起来很好的具体结果从未出现在正文里面。'
        self.assertFalse(validate_source_anchors({'content': body, 'manual_editorial_review': review}).ok)

    def test_profile_declares_generalizable_decision_contract(self):
        profile = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["schema_version"], 2)
        self.assertEqual(profile["decision_model"]["questions_file"], "resources/review_questions.json")
        self.assertTrue(profile["decision_model"]["manual_review_required"])
        self.assertFalse(profile["decision_model"]["keywords_affect_judgment"])
        self.assertFalse(profile["feedback_learning"]["blank_note_creates_rule"])
        self.assertNotIn("risk_signal_lexicon", profile)
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
            {}, penalties=["技术细节过深，目标读者难以理解或使用"]
        )
        self.assertEqual(contract["eligibility"]["status"], "passed")
        self.assertEqual(contract["machine_disposition"], "shortlist")
        self.assertTrue(contract["human_review_required"])
        self.assertTrue(all(row["answer"] == "unassessed" for row in contract["editorial_answers"].values()))


    def test_hard_failure_blocks_before_editorial_judgment(self):
        contract = build_decision_contract(
            {}, penalties=["主题已写过，不重复推荐"]
        )
        self.assertEqual(contract["eligibility"]["status"], "failed")
        self.assertEqual(contract["machine_disposition"], "blocked")
        self.assertEqual(contract["eligibility"]["failures"][0]["code"], "covered_topic")

    def test_insufficient_material_cannot_be_offset_by_score_or_review(self):
        for warning in ["文章正文偏短，不足以支撑高质量二创", "访谈摘要不足以支撑高质量二创"]:
            contract = build_decision_contract(
                {"manual_editorial_review": evidence_review()},
                penalties=[warning],
            )
            self.assertEqual(contract["machine_disposition"], "blocked")
            self.assertEqual(contract["eligibility"]["failures"][0]["code"], "insufficient_source_material")
        hard, risks = classify_penalties(["文章篇幅较短，但已完整展开失败、调整和结果"])
        self.assertEqual(hard, [])
        self.assertEqual(len(risks), 1)

    def test_manual_review_requires_every_question_and_objection(self):
        incomplete = validate_manual_review({"status": "passed", "answers": {"reader_meets_it": {"answer": "yes", "note": "读者每天都会遇到"}}})
        self.assertFalse(incomplete.ok)
        self.assertTrue(any("第 2 题没有回答" in error for error in incomplete.errors))
        self.assertTrue(any("最大疑点" in error for error in incomplete.errors))
        self.assertTrue(validate_manual_review(evidence_review()).ok)
        # 任何一题答到否决的那个答案就不推荐，没有总分可以拿来抵。
        vetoed = validate_manual_review(evidence_review(answers=passing_answers(overseas_only="yes")))
        self.assertFalse(vetoed.ok)
        self.assertTrue(any("第 2 题答了 yes" in error for error in vetoed.errors))
        self.assertFalse(validate_manual_review(evidence_review(answers=passing_answers(easy_rewrite="no"))).ok)
        # 说不清也不推。
        self.assertFalse(validate_manual_review(evidence_review(answers=passing_answers(text_stands_alone="unsure"))).ok)

    def test_final_record_is_auditable(self):
        item = {"manual_editorial_review": evidence_review()}
        record = final_decision_record(item)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(set(record["answers"]), set(QUESTION_IDS))
        self.assertIn("决定性证据", record["decision_driver"])

    def test_surface_feature_never_answers_a_question(self):
        contract = build_decision_contract(
            {"title": "某创始人的真实第一人称访谈"},
            penalties=[],
        )
        self.assertEqual(contract["machine_disposition"], "shortlist")
        self.assertEqual(contract["editorial_answers"]["author_bound"]["answer"], "unassessed")
        reviewed = build_decision_contract(
            {"manual_editorial_review": evidence_review()},
            penalties=[],
        )
        self.assertEqual(reviewed["editorial_answers"]["author_bound"]["answer"], "yes")


if __name__ == "__main__":
    unittest.main()
