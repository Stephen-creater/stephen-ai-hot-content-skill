"""Eligibility checks and the format check for Agent review cards.

Code decides objective eligibility only. It must not pretend
that keyword matches prove audience value, topic appeal, or reuse. Those need
an Agent that read the whole article, scored six dimensions and quoted it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import hashlib
import re


DIMENSIONS = (
    "topic_appeal",
    "reader_change",
    "material_increment",
    "re_authorability",
    "durability",
    "rewrite_effort",
)

REVIEW_FIELD_LABELS = {
    "topic_appeal": "选题吸引力",
    "reader_change": "读者改变",
    "material_increment": "干货含量",
    "re_authorability": "可重写性",
    "durability": "长期价值",
    "rewrite_effort": "改写成本",
    "counterargument": "最大疑点",
    "decision_driver": "放行理由",
}

# Recommend when most requirements are met, not only when every one is.
# Rewrite effort is scored and shown to Stephen but does not decide the verdict.
CORE_DIMENSIONS = DIMENSIONS[:5]
PASS_TOTAL = 6  # of 10, over the five core dimensions
MUST_NOT_BE_ZERO = ("reader_change", "material_increment")
# 2026-09-22 回看 92 条有终审分的审核：选题吸引力或读者改变不满 2 分的 34 条全被拒，六维里三项及以上 1 分的 30 条全被拒。
# 以前写成“勉强过线要对上选过的类型才推荐”，评审每次都说“对上了”放行，所以改成机器拦。
MUST_BE_FULL = ("topic_appeal", "reader_change")
MAX_ONE_POINT_SCORES = 2
# 评审自己在疑点里写出来的否决理由。2026-09-22 a 批五条全被拒，疑点里写着“三项只拿 1 分，属于勉强过线”
# “效果有一部分靠画面”，后面接一句“放行是因为……”照样发布了。“国内用不上”不在这里：Stephen 写过国内用不了的 Ditto，
# 海外 App 靠打分下限和读稿判断拦（Muse 那条选题吸引力只有 1 分）。
SELF_VETO_PATTERNS = (
    (r"勉强过线|勉强及格|放行是因为|虽然.{0,20}但.{0,6}放行", "疑点已经说了不够格，不能再找理由放行"),
    (r"靠(?:画面|截图|视频|动图|效果图)", "效果靠图和视频展示"),
    (r"大量代码|代码(?:较多|很多|偏多)", "正文代码多"),
)

HARD_FAILURE_MARKERS = {
    "正文缺少中文内容": "body_language_mismatch",
    "原文为繁体中文": "simplified_chinese_required",
    "主题已写过": "covered_topic",
    "常规岗位基础应用暂缓": "deferred_topic",
    "用户当前不认可该产品": "disfavored_subject",
    "传统节点式 Workflow 平台已被用户明确淘汰": "retired_workflow_platform",
    "超过时效范围": "stale_material",
    "事件新闻已超过时效窗口": "stale_event",
    "核验来源，不进入默认选题": "verification_only_source",
    "缺少完整文字材料": "incomplete_text",
    "站点返回验证页": "blocked_by_site",
    "超过二创能承受的数量": "too_many_images",
    "行代码，读者看不懂也没法二创": "too_much_code",
    "正文是英文原文": "english_original",
    "材料过少": "incomplete_text",
    "不足以支撑高质量二创": "insufficient_source_material",
    "只有版本号": "invalid_material",
    "标题与摘要缺少明确 AI 对象": "out_of_scope",
    "命中排除词": "excluded_subject",
    "播客缺少逐字稿": "missing_transcript",
    "视频缺少逐字稿": "missing_transcript",
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


def is_hard_failure(evidence: str) -> bool:
    return any(marker in evidence for marker in HARD_FAILURE_MARKERS)


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
    machine_disposition = "blocked" if failures else "shortlist"
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


FLAG_FIELDS = {
    "written_topic_hint": ("new_progress", "与已写文章《{value}》同名，要在 new_progress 写明这次的新进展"),
    "many_images": ("image_plan", "配图 {value} 张，要在 image_plan 写明二创时图怎么办"),
    "has_video": ("image_plan", "正文嵌了 {value} 段视频，要在 image_plan 写明二创时视频演示怎么办"),
}


def flags_for(row: dict, *, maximum_images: int = 10) -> dict[str, object]:
    """What the machine noticed about a candidate and the Agent must answer before delivery."""
    flags: dict[str, object] = {}
    if row.get("written_topic_hint"):
        flags["written_topic_hint"] = row["written_topic_hint"]
    count = row.get("image_count")
    if isinstance(count, int) and count >= maximum_images:
        flags["many_images"] = count
    videos = row.get("video_count")
    if isinstance(videos, int) and videos >= 1:
        flags["has_video"] = videos
    return flags


def validate_manual_review(review: dict, *, require_v2: bool = True, flags: dict[str, object] | None = None) -> ReviewValidation:
    """Validate evidence required before a candidate may be published."""
    if not isinstance(review, dict):
        return ReviewValidation(False, ("缺少终审记录",))
    errors: list[str] = []
    if review.get("status") != "passed":
        errors.append("终审状态不是 passed")
    if not require_v2:
        return ReviewValidation(not errors, tuple(errors))
    for field, label in REVIEW_FIELD_LABELS.items():
        value = review.get(field)
        if not isinstance(value, str) or len(value.strip()) < 12:
            errors.append(f"{label}缺少具体正文证据")
    for flag, value in (flags or {}).items():
        field, message = FLAG_FIELDS[flag]
        if len(str(review.get(field, "")).strip()) < 12:
            errors.append(message.format(value=value))
    # 疑点里自己写了“Stephen 写过”，就按已写主题对待：2026-09-21 c 批四条这样放行的全被标“过时或已写过”“对读者没用”。
    doubt = str(review.get("counterargument", ""))
    if re.search(r"写过|已写|写了.{0,6}篇|已经写", doubt) and len(str(review.get("new_progress", "")).strip()) < 12:
        errors.append("疑点里说 Stephen 写过同题，要在 new_progress 写明这次的新事实（新功能、新数据、新结果），不能只是换个人再说一遍")
    evidence_text = " ".join(str(review.get(key, "")) for key in (*DIMENSIONS, "counterargument"))
    for pattern, label in SELF_VETO_PATTERNS:
        text = doubt if label.startswith("疑点") else evidence_text
        if re.search(pattern, text):
            errors.append(f"终审自己写了否决理由（{label}），不能推荐")
    access = str(review.get("reader_access", "")).strip()
    if len(access) < 6:
        errors.append("要在 reader_access 写明读者在国内能不能直接用上文章讲的产品或方法")
    scores = review.get("scores")
    if not isinstance(scores, dict) or any(scores.get(key) not in (0, 1, 2) for key in DIMENSIONS):
        errors.append("六个维度都要打 0、1 或 2 分")
    else:
        total = sum(scores[key] for key in CORE_DIMENSIONS)
        if total < PASS_TOTAL:
            errors.append(f"五个核心维度总分 {total} 低于 {PASS_TOTAL}")
        for key in MUST_NOT_BE_ZERO:
            if scores[key] == 0:
                errors.append(f"{REVIEW_FIELD_LABELS[key]}为 0 分")
        for key in MUST_BE_FULL:
            if scores[key] != 2:
                errors.append(f"{REVIEW_FIELD_LABELS[key]}不满 2 分")
        ones = sum(1 for key in DIMENSIONS if scores[key] == 1)
        if ones > MAX_ONE_POINT_SCORES:
            errors.append(f"六个维度里 {ones} 项只有 1 分")
    return ReviewValidation(not errors, tuple(errors))


def validate_source_anchors(item: dict) -> ReviewValidation:
    """Verify quotes against the exact source reviewed; no quality score implied."""
    content = item.get("content", "")
    review = item.get("manual_editorial_review", {})
    anchors = review.get("source_anchors", [])
    errors = []
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if review.get("source_sha256") != digest:
        errors.append("终审正文指纹缺失或正文已变化")
    normalize = lambda value: re.sub(r"\s+", "", value)
    matched = set()
    if not isinstance(anchors, list):
        return ReviewValidation(False, ("source_anchors 必须为数组",))
    for anchor in anchors:
        if not isinstance(anchor, dict):
            errors.append("无效原文依据")
            continue
        quote = anchor.get("quote", "")
        if not isinstance(quote, str) or len(normalize(quote)) < 12 or normalize(quote) not in normalize(content):
            errors.append("引用无法在当前正文中定位")
            continue
        dimension = anchor.get("dimension")
        if dimension not in DIMENSIONS:
            errors.append("引用维度无效")
        else:
            matched.add(dimension)
    if not {"material_increment", "re_authorability"}.issubset(matched):
        errors.append("干货含量和可重写性必须各有原文引用")
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
        "scores": review.get("scores", {}),
        "dimensions": {
            key: {"verdict": "supported", "evidence": str(review.get(key, "")).strip()}
            for key in DIMENSIONS
            if str(review.get(key, "")).strip()
        },
    }
