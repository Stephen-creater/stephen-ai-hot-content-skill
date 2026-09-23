import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_trace  # noqa: E402
import eval_suite  # noqa: E402
from review_answers import passing_answers  # noqa: E402

PROFILE = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
BODY = "作者连续三周记录自己用 AI 整理会议纪要的做法，写清了失败的两次和改进后的结果。" * 30


def case(item_id, label, reasons=(), note="", strength="strong"):
    return {"id": item_id, "batch": "2026-09-01-main-a", "split": "train", "label": label, "label_strength": strength,
            "reasons": list(reasons), "note": note, "judgeable": True, "reviewed_at": "2026-09-02",
            "candidate": {"title": f"候选{item_id}", "content": BODY, "language": "zh", "published": "2026-09-01",
                          "source_name": "测试源", "link": f"https://example.org/{item_id}", "content_status": "fulltext"}}


class VerdictTest(unittest.TestCase):
    def test_verdict_is_computed_from_answers_not_taken_from_the_judge(self):
        item = case("a", "rejected", ["海外 App"])
        good = eval_suite.verdict_for(item, {"answers": passing_answers(), "counterargument": "样本只有一个人"}, PROFILE)
        self.assertEqual(good["verdict"], "recommend")
        vetoed = eval_suite.verdict_for(item, {"answers": passing_answers(overseas_only="yes"), "counterargument": "样本只有一个人"}, PROFILE)
        self.assertEqual(vetoed["verdict"], "reject")
        self.assertIn("overseas_only", vetoed["by"])
        talked_into = eval_suite.verdict_for(item, {"answers": passing_answers(), "counterargument": "三项偏弱，勉强过线，放行是因为对上了一类"}, PROFILE)
        self.assertEqual(talked_into["verdict"], "reject")

    def test_per_question_agreement_uses_stephens_reason_button(self):
        items = [case("a", "rejected", ["海外 App"]), case("b", "selected")]
        judge = [{"id": "a", "answers": passing_answers(overseas_only="yes")}, {"id": "b", "answers": passing_answers()}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "judge.json"
            path.write_text(json.dumps(judge, ensure_ascii=False), encoding="utf-8")
            run = eval_suite.record_run(items, {"a", "b"}, "all", [path], "test-model", PROFILE, "v1")
        score = eval_suite.score_run(run, items, {})
        self.assertEqual(score["pass_all_trials"], 1.0)
        self.assertEqual(score["per_question"]["overseas_only"]["agree_rate"], 1.0)


class SuiteTest(unittest.TestCase):
    def test_regression_only_grows_and_takes_what_the_rules_get_right(self):
        items = [case("a", "rejected", ["海外 App"]), case("b", "rejected", ["太垂直小众"]), case("c", "rejected", strength="weak")]
        results = {"a": {"verdict": "reject", "by": ["overseas_only"], "answers": {}},
                   "b": {"verdict": "recommend", "by": [], "answers": {}},
                   "c": {"verdict": "reject", "by": [], "answers": {}}}
        run = {"run_id": "r1", "case_ids": ["a", "b", "c"], "trials": [{"judge": "j", "results": results}]}
        suites = eval_suite.build_suites(run, items, {}, {"regression": ["old"], "capability": [], "retired": {}})
        self.assertEqual(suites["regression"], ["a", "old"])
        self.assertEqual(suites["capability"], ["b"])

    def test_gate_demands_a_fresh_regression_run(self):
        items = [case("a", "rejected", ["海外 App"])]
        suites = {"regression": ["a"], "capability": [], "retired": {}}
        stale = {"run_id": "r0", "fingerprint": "old", "suite": "regression", "case_ids": ["a"], "trials": []}
        problems = eval_suite.gate(items, suites, [stale], {}, PROFILE)
        self.assertTrue(any("还没有用现在的规则重跑回归测试集" in p for p in problems))
        fresh = {"run_id": "r1", "fingerprint": eval_suite.rules_fingerprint(), "suite": "regression", "case_ids": ["a"],
                 "trials": [{"judge": "j", "results": {"a": {"verdict": "recommend", "by": [], "answers": passing_answers()}}}]}
        problems = eval_suite.gate(items, suites, [stale, fresh], {}, PROFILE)
        self.assertTrue(any("通过率" in p for p in problems))
        self.assertTrue(any("负向用例" in p for p in problems))


class TraceTest(unittest.TestCase):
    def test_card_rewritten_after_being_blocked_is_flagged(self):
        checks = [{"id": "x", "title": "Muse 被拉闸", "ok": False, "errors": ["终审自己写了否决理由"], "card": "aaa"},
                  {"id": "x", "title": "Muse 被拉闸", "ok": True, "errors": [], "card": "bbb"},
                  {"id": "y", "title": "正常一条", "ok": True, "errors": [], "card": "ccc"}]
        flagged = batch_trace.rewritten_after_block(checks)
        self.assertEqual([row["id"] for row in flagged], ["x"])


if __name__ == "__main__":
    unittest.main()


class NegativeBatchTest(unittest.TestCase):
    def test_only_pressure_induced_pushes_block(self):
        items = [case("a", "rejected", ["海外 App"]), case("b", "rejected", ["太浅太泛"])]
        suites = {"regression": ["a", "b"], "capability": [], "retired": {}}
        fp = eval_suite.rules_fingerprint()
        calm = {"run_id": "r1", "fingerprint": fp, "suite": "all", "case_ids": ["a", "b"],
                "trials": [{"judge": "j", "results": {"a": {"verdict": "reject", "by": ["overseas_only"], "answers": passing_answers(overseas_only="yes")},
                                                     "b": {"verdict": "recommend", "by": [], "answers": passing_answers()}}}]}
        pressed = {"run_id": "r2", "fingerprint": fp, "suite": "negative_batch", "case_ids": ["a", "b"],
                   "trials": [{"judge": "j", "results": {"a": {"verdict": "recommend", "by": [], "answers": passing_answers()},
                                                        "b": {"verdict": "recommend", "by": [], "answers": passing_answers()}}}]}
        problems = eval_suite.gate(items, suites, [calm, pressed], {}, PROFILE)
        self.assertTrue(any("凑数" in p and "候选a" in p for p in problems))
        self.assertFalse(any("凑数" in p and "候选b" in p for p in problems))


class ScriptOnlyChangeTest(unittest.TestCase):
    def test_script_change_needs_no_rejudging_but_released_cases_do(self):
        items = [case("a", "rejected", ["海外 App"])]
        blocked_then = {"run_id": "r1", "fingerprint": eval_suite.rules_fingerprint(), "suite": "all", "case_ids": ["a"],
                        "trials": [{"judge": "j", "results": {"a": {"verdict": "reject", "by": ["script"], "answers": {}}}}]}
        rescored = eval_suite.rescore(blocked_then, items, PROFILE)
        self.assertEqual(rescored["trials"][0]["results"]["a"]["verdict"], "missing")
        answered = {"run_id": "r2", "fingerprint": eval_suite.rules_fingerprint(), "suite": "needs_judging", "case_ids": ["a"],
                    "trials": [{"judge": "j", "results": {"a": {"verdict": "reject", "by": ["overseas_only"], "answers": passing_answers(overseas_only="yes")}}}]}
        filled = eval_suite.fill_missing(rescored, [answered])
        self.assertEqual(filled["trials"][0]["results"]["a"]["verdict"], "reject")
