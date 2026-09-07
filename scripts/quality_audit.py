"""Transparent structural quality audit for the Skill package."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    category: str
    name: str
    weight: int
    passed: bool
    evidence: str


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def audit() -> dict:
    skill = read("SKILL.md")
    judgment = read("references/editorial-judgment.md")
    calibration = read("references/editorial-calibration-cases.md")
    protocol = read("references/feedback-learning-protocol.md")
    profile = json.loads(read("resources/editorial_profile.json"))
    publisher = read("scripts/publish_batch.py")
    importer = read("scripts/import_feedback.py")
    ignore = read(".gitignore")

    checks = [
        Check("feedback_fidelity", "five independent dimensions", 8,
              all(term in judgment for term in ("选题吸引力", "读者改变", "材料增量", "二创独立性", "长期价值")),
              "stable judgment model"),
        Check("feedback_fidelity", "feedback learning types", 6,
              all(term in protocol for term in ("invariant", "conditional_preference", "case_only", "unexplained_decision", "hypothesis")),
              "feedback is classified before generalization"),
        Check("feedback_fidelity", "paired boundary cases", 6,
              calibration.count("### 可选") >= 5 and calibration.count("### 不选") >= 5,
              "positive and negative cases share surface traits"),

        Check("generalization", "keywords are not final verdicts", 7,
              profile["decision_model"].get("keyword_matches_are_risk_signals_not_verdicts") is True,
              "profile contract"),
        Check("generalization", "counterexample required", 5,
              profile["feedback_learning"].get("require_counterexample_before_generalizing") is True,
              "feedback contract"),
        Check("generalization", "blank notes never create rules", 4,
              profile["feedback_learning"].get("blank_note_creates_rule") is False,
              "unexplained decisions remain unexplained"),
        Check("generalization", "no dated patch section in core guidance", 4,
              not re.search(r"^#{1,4} .*20\d{2}-\d{2}-\d{2}", skill + "\n" + judgment, re.M),
              "core docs are organized by principle"),
        Check("generalization", "human evidence can override risk only", 5,
              "validate_manual_review" in publisher and "eligibility.get(\"status\") == \"failed\"" in publisher,
              "objective failures stay absolute; editorial risks are reviewable"),

        Check("reliability", "five-item article-first gate", 5,
              profile.get("minimum_delivery_count") == 5 and profile.get("minimum_non_github_candidates") >= 4 and profile.get("maximum_github_candidates") <= 1,
              "delivery composition"),
        Check("reliability", "v2 evidence required before publish", 6,
              "final_decision_record" in publisher and "人工终审证据不完整" in publisher,
              "publication gate"),
        Check("reliability", "feedback coverage audit exists", 4,
              (ROOT / "scripts/feedback_audit.py").exists() and "scripts/feedback_audit.py" in skill,
              "all feedback records are accounted for"),
        Check("reliability", "atomic feedback persistence", 3,
              all(term in importer for term in ("flock", "fsync", "read_bytes", "unlink")),
              "locked write, readback, guarded cleanup"),
        Check("reliability", "parallel ownership in execution contract", 2,
              all(term in skill for term in ("主力2", "批次 ID", "归属")),
              "parallel lanes cannot guess file ownership"),

        Check("maintainability", "compact core Skill", 5,
              len(skill.splitlines()) <= 160,
              f"{len(skill.splitlines())} lines"),
        Check("maintainability", "compact stable judgment model", 4,
              len(judgment.splitlines()) <= 160,
              f"{len(judgment.splitlines())} lines"),
        Check("maintainability", "progressive disclosure links", 3,
              all(name in skill for name in ("editorial-judgment.md", "editorial-calibration-cases.md", "feedback-learning-protocol.md")),
              "core, protocol and cases are separate"),
        Check("maintainability", "machine-readable profile schema", 3,
              profile.get("schema_version") == 2 and (ROOT / "resources/editorial_profile.schema.json").exists(),
              "versioned configuration"),

        Check("safety", "private paths ignored", 5,
              all(term in ignore for term in (".config/", ".local/", "topics/", ".env")),
              "secrets, feedback and artifacts stay local"),
        Check("safety", "browser boundary explicit", 2,
              "不调用 OpenCLI" in skill and "Ego Browser" in skill,
              "user Chrome is not commandeered"),
        Check("safety", "writing scope excluded", 3,
              "不撰写文章正文" in skill and "stephen-writing-skill" in skill,
              "selection and writing remain separate"),

        Check("tests", "decision contract tests", 5,
              (ROOT / "tests/test_editorial_judgment.py").exists(),
              "eligibility, risk and evidence boundaries"),
        Check("tests", "feedback audit tests", 2,
              (ROOT / "tests/test_feedback_audit.py").exists(),
              "coverage, conflicts and malformed input"),
        Check("tests", "paired-case test requirement documented", 1,
              all(term in protocol for term in ("应拦截案例", "反例", "换掉具体名词")),
              "new rules require counterfactual coverage"),
        Check("tests", "portable paired boundary fixture", 2,
              (ROOT / "tests/fixtures/editorial_boundary_cases.json").exists()
              and (ROOT / "tests/test_editorial_boundary_cases.py").exists(),
              "same surface feature has consider and reject cases"),
    ]
    categories: dict[str, dict] = {}
    for check in checks:
        bucket = categories.setdefault(check.category, {"earned": 0, "possible": 0})
        bucket["possible"] += check.weight
        bucket["earned"] += check.weight if check.passed else 0
    score = sum(check.weight for check in checks if check.passed)
    possible = sum(check.weight for check in checks)
    return {
        "score": score,
        "possible": possible,
        "passed": score >= 95,
        "categories": categories,
        "failed_checks": [
            {"category": check.category, "name": check.name, "weight": check.weight, "evidence": check.evidence}
            for check in checks if not check.passed
        ],
        "checks": [check.__dict__ for check in checks],
    }


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
