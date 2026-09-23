"""Eligibility checks and the format check for Agent review cards.

Code decides objective eligibility only. It must not pretend
that keyword matches prove audience value, topic appeal, or reuse. Those need
an Agent that read the whole article and answered the yes/no questions in
resources/review_questions.json, quoting the article.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import hashlib
import json
import re


QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "resources" / "review_questions.json"


def load_questions(path: Path = QUESTIONS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


QUESTION_SET = load_questions()
QUESTIONS = tuple(QUESTION_SET["questions"])
QUESTION_IDS = tuple(q["id"] for q in QUESTIONS)
ANSWERS = ("yes", "no", "unsure")
# 这几道题的答案必须引一句能在正文里找到的原句，证明评审真的读了全文。
QUOTED_QUESTIONS = ("reader_takeaway", "has_substance")
REVIEW_FIELD_LABELS = {"counterargument": "最大疑点", "decision_driver": "放行理由"}


def question_number(question_id: str) -> int:
    return QUESTION_IDS.index(question_id) + 1


def vetoes(answers: dict) -> list[str]:
    """Question ids whose answer stops the recommendation. unsure counts too: 说不清就不推。

    2026-09-22 起用是/否题代替六维 0/1/2 分：65 条有终审分的审核里 57 条选题吸引力是 2 分，Stephen 只选了 1 条，
    分数分不出好坏；而且有了总分，评审就会写“虽然……但总分够，放行”。
    """
    hits = []
    for question in QUESTIONS:
        entry = answers.get(question["id"]) if isinstance(answers, dict) else None
        answer = entry.get("answer") if isinstance(entry, dict) else None
        if answer not in ANSWERS or answer == "unsure" or answer == question["veto_if"]:
            hits.append(question["id"])
    return hits


# 评审自己在疑点里写出来的放行说辞。2026-09-22 a 批五条全被拒，疑点里写着“三项只拿 1 分，属于勉强过线”，后面接一句“放行是因为……”照样发布了。
# 以前还拦“靠画面、靠截图”“大量代码”，改成是/否题后由第 8、9 题管；2026-09-23 全量重判时这两条单独拦下的只有两篇写成了文章的稿（Wan3.0、腾讯会议），就删了。
SELF_VETO_PATTERNS = (
    (r"勉强过线|勉强及格|放行是因为|虽然.{0,20}但.{0,20}放行", "疑点已经说了不够格，不能再找理由放行"),
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
    answered = manual.get("answers") if isinstance(manual.get("answers"), dict) else {}
    dimensions = {key: answered.get(key, {"answer": "unassessed"}) for key in QUESTION_IDS}
    machine_disposition = "blocked" if failures else "shortlist"
    return {
        "contract_version": 3,
        "eligibility": {
            "status": "failed" if failures else "passed",
            "failures": failures,
        },
        "editorial_answers": dimensions,
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
    answers = review.get("answers")
    if not isinstance(answers, dict):
        errors.append(f"要逐题回答 {len(QUESTIONS)} 道是/否题（answers）")
        return ReviewValidation(False, tuple(errors))
    notes = []
    for question in QUESTIONS:
        entry = answers.get(question["id"])
        number = question_number(question["id"])
        if not isinstance(entry, dict) or entry.get("answer") not in ANSWERS:
            errors.append(f"第 {number} 题没有回答 yes、no 或 unsure：{question['text']}")
            continue
        note = str(entry.get("note", "")).strip()
        notes.append(note)
        if len(note) < 8:
            errors.append(f"第 {number} 题要用一句话写明为什么这样答")
        if entry["answer"] == "unsure":
            errors.append(f"第 {number} 题答了说不清，说不清就不推荐：{question['text']}")
        elif entry["answer"] == question["veto_if"]:
            errors.append(f"第 {number} 题答了 {entry['answer']}，不能推荐：{question['text']}")
    evidence_text = " ".join([*notes, doubt])
    for pattern, label in SELF_VETO_PATTERNS:
        text = doubt if label.startswith("疑点") else evidence_text
        if re.search(pattern, text):
            errors.append(f"终审自己写了否决理由（{label}），不能推荐")
    return ReviewValidation(not errors, tuple(errors))


def validate_source_anchors(item: dict) -> ReviewValidation:
    """Verify quotes against the exact source reviewed; no quality score implied."""
    content = item.get("content", "")
    review = item.get("manual_editorial_review", {})
    errors = []
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if review.get("source_sha256") != digest:
        errors.append("终审正文指纹缺失或正文已变化")
    normalize = lambda value: re.sub(r"\s+", "", value)
    for question_id in QUOTED_QUESTIONS:
        entry = (review.get("answers") or {}).get(question_id) if isinstance(review.get("answers"), dict) else None
        quote = entry.get("quote", "") if isinstance(entry, dict) else ""
        if not isinstance(quote, str) or len(normalize(quote)) < 12 or normalize(quote) not in normalize(content):
            errors.append(f"第 {question_number(question_id)} 题的原句引用无法在当前正文中定位")
    return ReviewValidation(not errors, tuple(errors))


def final_decision_record(item: dict) -> dict:
    """Return the final publication-stage record after validated human review."""
    review = item.get("manual_editorial_review", {})
    validation = validate_manual_review(review)
    return {
        "contract_version": 3,
        "status": "passed" if validation.ok else "failed",
        "errors": list(validation.errors),
        "decision_driver": str(review.get("decision_driver", "")).strip(),
        "counterargument": str(review.get("counterargument", "")).strip(),
        "answers": review.get("answers", {}),
    }
