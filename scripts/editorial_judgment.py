"""Editorial decision contract for Stephen's hot-topic pipeline.

Deterministic code may establish eligibility and surface risks. It must not
pretend that keyword matches prove audience value, topic appeal, or reuse.
Those dimensions require evidence from a complete source and a human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DIMENSIONS = (
    "topic_appeal",
    "reader_change",
    "material_increment",
    "re_authorability",
    "durability",
)

REVIEW_FIELD_LABELS = {
    "topic_appeal": "选题吸引力",
    "reader_change": "读者改变",
    "material_increment": "材料增量",
    "re_authorability": "二创独立性",
    "durability": "长期价值",
    "counterargument": "最强反对理由",
    "decision_driver": "决定性证据",
}

HARD_FAILURE_MARKERS = {
    "原文为繁体中文": "simplified_chinese_required",
    "主题已写过": "covered_topic",
    "常规岗位基础应用暂缓": "deferred_topic",
    "用户当前不认可该产品": "disfavored_subject",
    "传统节点式 Workflow 平台已被用户明确淘汰": "retired_workflow_platform",
    "超过时效范围": "stale_material",
    "事件新闻已超过时效窗口": "stale_event",
    "英文一手信息": "verification_only_language",
    "核验来源，不进入默认选题": "verification_only_source",
    "缺少完整文字材料": "incomplete_text",
    "材料过少": "incomplete_text",
    "不足以支撑高质量二创": "insufficient_source_material",
    "只有版本号": "invalid_material",
    "标题与摘要缺少明确 AI 对象": "out_of_scope",
    "命中排除词": "excluded_subject",
    "播客缺少逐字稿": "missing_transcript",
    "视频缺少逐字稿": "missing_transcript",
    "关键证据依赖视频画面": "visual_evidence_dependency",
    "正文代码或实现片段占比过高": "implementation_dominates_article",
    "专业缩写、系统名与工程标识密度过高": "specialist_language_dominates",
    "GitHub Star 数未核验": "github_evidence_missing",
    "GitHub Star 低于": "github_below_threshold",
    "GitHub 最近有效发布或更新超过 7 天": "github_not_recent",
    "来源域名已被明确排除": "blocked_source",
    "作者或个人 IP 已被明确排除": "blocked_creator",
    "正文被登录、关注或付费墙截断": "locked_content",
    "文章主动披露由 AI 生成": "self_disclosed_ai_text",
}


@dataclass(frozen=True)
class ReviewValidation:
    ok: bool
    errors: tuple[str, ...]


def unique_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result


def classify_penalties(penalties: Iterable[str]) -> tuple[list[dict], list[dict]]:
    """Separate objective ineligibility from editorial investigation signals."""
    hard: list[dict] = []
    risks: list[dict] = []
    for evidence in unique_text(penalties):
        code = next((code for marker, code in HARD_FAILURE_MARKERS.items() if marker in evidence), None)
        record = {"code": code or "editorial_risk", "evidence": evidence}
        if code:
            hard.append(record)
        else:
            risks.append(record)
    return hard, risks


def build_decision_contract(
    item: dict,
    *,
    penalties: Iterable[str],
    score: float,
    minimum_score: float,
) -> dict:
    """Build an auditable machine-stage record without inventing human evidence."""
    failures, risks = classify_penalties(penalties)
    manual = item.get("manual_editorial_review") if isinstance(item.get("manual_editorial_review"), dict) else {}
    dimensions = {
        key: {
            "verdict": "supported" if str(manual.get(key, "")).strip() else "unassessed",
            "evidence": str(manual.get(key, "")).strip(),
        }
        for key in DIMENSIONS
    }
    machine_disposition = "blocked" if failures else ("shortlist" if score >= minimum_score else "review")
    return {
        "contract_version": 2,
        "eligibility": {
            "status": "failed" if failures else "passed",
            "failures": failures,
        },
        "editorial_dimensions": dimensions,
        "risk_signals": risks,
        "machine_disposition": machine_disposition,
        "human_review_required": manual.get("status") != "passed",
        "decision_driver": str(manual.get("decision_driver", "")).strip(),
        "counterargument": str(manual.get("counterargument", "")).strip(),
    }


def validate_manual_review(review: dict, *, require_v2: bool = True) -> ReviewValidation:
    """Validate evidence required before a candidate may be published."""
    if not isinstance(review, dict):
        return ReviewValidation(False, ("缺少人工终审",))
    errors: list[str] = []
    if review.get("status") != "passed":
        errors.append("人工终审状态不是 passed")
    if not require_v2:
        return ReviewValidation(not errors, tuple(errors))
    for field, label in REVIEW_FIELD_LABELS.items():
        value = review.get(field)
        if not isinstance(value, str) or len(value.strip()) < 12:
            errors.append(f"{label}缺少具体正文证据")
    return ReviewValidation(not errors, tuple(errors))


def final_decision_record(item: dict) -> dict:
    """Return the final publication-stage record after validated human review."""
    review = item.get("manual_editorial_review", {})
    validation = validate_manual_review(review)
    return {
        "contract_version": 2,
        "status": "passed" if validation.ok else "failed",
        "errors": list(validation.errors),
        "decision_driver": str(review.get("decision_driver", "")).strip(),
        "counterargument": str(review.get("counterargument", "")).strip(),
        "dimensions": {
            key: {"verdict": "supported", "evidence": str(review.get(key, "")).strip()}
            for key in DIMENSIONS
            if str(review.get(key, "")).strip()
        },
    }
