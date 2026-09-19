"""仓库结构检查：文件齐不齐、规则有没有写矛盾。

只回答“结构是否完整”，给出通过或不通过，不打分。选题好不好看 Stephen 的
采纳率（feedback_audit.py）和历史回放评测（eval_replay.py）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from editorial_judgment import DIMENSIONS, HARD_FAILURE_MARKERS

ROOT = Path(__file__).resolve().parents[1]
# Words that make the Skill unreadable to Stephen; see AGENTS.md 写作规范.
# AGENTS.md lists these words on purpose, so it is not scanned.
BANNED_WORDS = ("契约", "求解空间", "口径", "闭环", "Agent Reach", "agent_reach", "OpenCLI 路由")
HUMAN_DOCS = ("SKILL.md", "README.md", *(str(p.relative_to(ROOT)) for p in sorted((ROOT / "references").glob("*.md"))))


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def broken_links(relative: str) -> list[str]:
    base = (ROOT / relative).parent
    missing = []
    for target in re.findall(r"\]\(([^)#\s]+\.md)\)", read(relative)):
        if not (base / target).exists():
            missing.append(f"{relative} -> {target}")
    return missing


def audit() -> dict:
    skill = read("SKILL.md")
    judgment = read("references/editorial-judgment.md")
    calibration = read("references/editorial-calibration-cases.md")
    protocol = read("references/feedback-learning-protocol.md")
    profile = json.loads(read("resources/editorial_profile.json"))
    publisher = read("scripts/publish_batch.py")
    importer = read("scripts/import_feedback.py")
    curator = read("scripts/curator.py")
    ignore = read(".gitignore")
    subjective_codes = {
        "implementation_dominates_article", "specialist_language_dominates", "complex_technical_case",
        "frontier_lab_safety_topic", "strategic_product_analysis", "visual_evidence_dependency",
    }
    banned_hits = [f"{doc}: {word}" for doc in HUMAN_DOCS for word in BANNED_WORDS if word in read(doc)]
    links = [missing for doc in HUMAN_DOCS for missing in broken_links(doc)]

    checks = [
        Check("判断标准写全六个维度", all(term in judgment for term in ("选题吸引力", "读者改变", "干货含量", "可重写性", "长期价值", "改写成本")), "references/editorial-judgment.md"),
        Check("打分规则和代码一致", profile["decision_model"].get("dimensions_in_order") == list(DIMENSIONS) and "至少 6 分" in skill and "至少 6 分" in judgment, "六维与总分门槛"),
        Check("反馈有七种归类", all(term in protocol for term in ("invariant", "conditional_preference", "case_only", "unexplained_decision", "hypothesis")), "feedback-learning-protocol.md"),
        Check("正反例成对", calibration.count("### 可选") >= 5 and calibration.count("### 不选") >= 5, "editorial-calibration-cases.md"),
        Check("关键词不参与判断", profile["decision_model"].get("keywords_affect_judgment") is False and "risk_signal_lexicon" not in profile, "口味档案"),
        Check("单批反馈不能造硬规则", profile["feedback_learning"].get("single_batch_can_create_subjective_hard_gate") is False and profile["feedback_learning"].get("blank_note_creates_rule") is False, "口味档案"),
        Check("一票否决只收客观条件", not (set(HARD_FAILURE_MARKERS.values()) & subjective_codes), "editorial_judgment.py"),
        Check("阅读顺序只用客观信号", 'item["reading_order"]' in curator, "curator.rank_candidates"),
        Check("核心文档不按日期打补丁", not re.search(r"^#{1,4} .*20\d{2}-\d{2}-\d{2}", skill + "\n" + judgment, re.M), "SKILL.md 与判断标准"),
        Check("发布前检查终审理由", "validate_manual_review" in publisher and 'eligibility.get("status") == "failed"' in publisher, "publish_batch.py"),
        Check("有历史回放评测", (ROOT / "scripts/eval_replay.py").exists() and (ROOT / "references/evaluation.md").exists() and "eval_replay.py machine" in skill, "eval_replay.py"),
        Check("有反馈审计", (ROOT / "scripts/feedback_audit.py").exists() and "feedback_audit.py" in skill, "feedback_audit.py"),
        Check("反馈写入加锁并回读", all(term in importer for term in ("flock", "fsync", "read_bytes", "unlink")), "import_feedback.py"),
        Check("并行认领写清楚", all(term in skill for term in ("主力2", "批次 ID", "认领")), "SKILL.md"),
        Check("SKILL.md 不过长", len(skill.splitlines()) <= 180, f"{len(skill.splitlines())} 行"),
        Check("文档链接都有效", not links, "；".join(links) or "全部有效"),
        Check("文档不用禁用词", not banned_hits, "；".join(banned_hits) or "没有命中"),
        Check("私有目录不提交", all(term in ignore for term in (".config/", ".local/", "topics/", ".env")), ".gitignore"),
        Check("清洗来源里的密钥", "redact_untrusted_secrets" in curator, "curator.py"),
        Check("浏览器边界写清楚", "不启动或接管" in skill and "channels.md" in skill, "SKILL.md"),
        Check("不写文章正文", "不写文章正文" in skill and "stephen-writing-skill" in skill, "SKILL.md"),
        Check("关键测试存在", all((ROOT / path).exists() for path in ("tests/test_editorial_judgment.py", "tests/test_feedback_audit.py", "tests/test_eval_replay.py")), "tests/"),
    ]
    failed = [check.__dict__ for check in checks if not check.passed]
    return {
        "scope": "只检查文件和结构，不代表选题质量",
        "passed": not failed,
        "failed": failed,
        "checks": [check.__dict__ for check in checks],
    }


if __name__ == "__main__":
    report = audit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
