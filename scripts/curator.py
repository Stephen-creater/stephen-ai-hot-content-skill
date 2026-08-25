from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit


TAG_RE = re.compile(r"<[^>]+>")
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?|\$\d+", re.I)
VERSION_ONLY_RE = re.compile(r"^(?:[a-z-]+-)?v?\d+\.\d+(?:\.\d+)?(?:[-.][a-z0-9.]+)?$", re.I)
PACKAGE_VERSION_RE = re.compile(r"^[a-z0-9_.-]+\s+v?\d+\.\d+(?:\.\d+)?(?:[-.][a-z0-9.]+)?$", re.I)
CORE_AI_TERMS = (
    "ai", "agent", "llm", "model", "codex", "claude", "openai", "anthropic",
    "gemini", "deepmind", "skill", "mcp", "prompt", "inference", "training",
    "reasoning", "人工智能", "模型", "智能体", "推理", "训练", "上下文", "缓存",
)


def contains_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9 .+-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def title_similarity(left: str, right: str) -> float:
    normalize = lambda text: re.sub(r"\W+", "", text.lower())
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def deduplicate(items: list[dict]) -> list[dict]:
    kept: list[dict] = []
    seen_urls: set[str] = set()
    for item in items:
        url = canonical_url(item.get("link", ""))
        if url and url in seen_urls:
            continue
        if any(title_similarity(item.get("title", ""), old.get("title", "")) >= 0.86 for old in kept):
            continue
        if url:
            seen_urls.add(url)
        kept.append(item)
    return kept


def score_item(item: dict, profile: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    title = clean_text(item.get("title"))
    summary = clean_text(item.get("summary") or item.get("description"))
    content = clean_text(item.get("content"))
    haystack = f"{title} {summary} {content}".lower()
    title_summary = f"{title} {summary}".lower()
    reasons: list[str] = []
    penalties: list[str] = []
    language = item.get("language", "unknown")
    maturity = item.get("maturity", "unknown")
    content_status = item.get("content_status", "fulltext" if len(content) >= 500 else "summary")
    source_role = item.get("source_role", "candidate")

    published = parse_datetime(item.get("published") or item.get("article_date"))
    age_days = None
    if published:
        age_days = max(0, (now - published).days)
        if age_days > profile["max_age_days"]:
            penalties.append("超过时效范围")
        elif age_days <= profile["priority_days"]:
            reasons.append("最近一周发布")

    matched_pillars = []
    pillar_points = 0.0
    for pillar in profile["topic_pillars"]:
        matches = [keyword for keyword in pillar["keywords"] if keyword.lower() in haystack]
        if matches:
            matched_pillars.append(pillar["name"])
            pillar_points = max(pillar_points, 22 * float(pillar["weight"]))
    if matched_pillars:
        reasons.append("符合" + "、".join(matched_pillars[:2]))

    excluded = [word for word in profile["exclude_keywords"] if word.lower() in haystack]
    if excluded:
        penalties.append("命中排除词" + "、".join(excluded[:2]))

    score = pillar_points
    priority = int(item.get("source_priority", 3))
    score += priority * 2
    if age_days is not None:
        score += max(0, 18 - age_days)
    elif item.get("source_type") == "web":
        score -= 6

    if language == profile.get("preferred_language"):
        score += 18
        reasons.append("中文内容")
    elif language == "en":
        score -= 22
        penalties.append("英文一手信息，优先用于核验")
    if maturity == profile.get("preferred_maturity"):
        score += 16
        reasons.append("作者已完成二手整合")
    elif maturity == "primary":
        score -= 15
    if source_role == "verification":
        score -= 80
        penalties.append("核验来源，不进入默认选题")

    if content_status == "transcript":
        score += 20
        reasons.append("已有逐字稿")
    elif content_status == "fulltext":
        score += 15
        reasons.append("已有完整正文")
    elif content_status == "shownotes":
        score += 8
        reasons.append("已有详细 Show Notes")
    else:
        score -= 14
        penalties.append("缺少完整文字材料")

    if NUMBER_RE.search(haystack):
        score += 6
        reasons.append("包含明确数字")
    if any(word in haystack for word in ("github", "api", "open source", "开源", "case study", "案例")):
        score += 7
        reasons.append("具备产品或案例抓手")
    if any(word in haystack for word in ("how", "guide", "workflow", "skill", "方法", "实践", "为什么")):
        score += 5
        reasons.append("可形成机制解释")
    if len(content) >= 500:
        score += 8
        reasons.append("正文材料充足")
    elif len(summary) < 80:
        score -= 8
        penalties.append("材料过少")
    if excluded:
        score -= 60
    if VERSION_ONLY_RE.fullmatch(title.strip()) or PACKAGE_VERSION_RE.fullmatch(title.strip()):
        score -= 90
        penalties.append("只有版本号")
    if not any(contains_term(title_summary, term) for term in CORE_AI_TERMS):
        score -= 40
        penalties.append("标题与摘要缺少明确 AI 对象")
    if any(word.lower() in haystack for word in ("weekly roundup", "week in review", "本周汇总", "一周回顾")):
        score -= 30
        penalties.append("多事件合集")
    if title.count("；") >= 2:
        score -= 40
        penalties.append("标题包含多个事件")
    finance_terms = ("funding", "raises $", "valuation", "融资", "估值")
    substance_terms = ("open source", "开源", "api", "workflow", "agent", "product", "产品", "机制", "case study")
    if any(word in haystack for word in finance_terms) and not any(word in haystack for word in substance_terms):
        score -= 35
        penalties.append("只有融资或估值")
    title_finance = ("融资", "估值", "收购", "卖了", "亿美元")
    title_substance = ("开源", "模型发布", "模型上线", "产品发布", "产品上线", "技术", "案例", "工作流", "agent")
    if any(word.lower() in title.lower() for word in title_finance) and not any(word.lower() in title.lower() for word in title_substance):
        score -= 35
        penalties.append("标题只有资本事件")
    if any(word in title for word in ("重磅发布", "深度参与", "主论坛", "峰会")):
        score -= 30
        penalties.append("疑似会议或商业通稿")
    if any(word in title for word in ("比赛", "决赛", "奖金")):
        score -= 25
        penalties.append("比赛新闻偏离既有文章谱系")

    editorial_fit = profile.get("editorial_fit", {})
    evergreen_terms = [word for word in editorial_fit.get("evergreen_angle_terms", []) if word.lower() in haystack]
    hype_terms = [word for word in editorial_fit.get("hype_or_gossip_terms", []) if word.lower() in title_summary]
    broad_terms = [word for word in editorial_fit.get("broad_or_pr_terms", []) if word.lower() in title_summary]
    niche_terms = [word for word in editorial_fit.get("niche_professional_terms", []) if word.lower() in title_summary]
    major_entities = [word for word in editorial_fit.get("major_ai_entities", []) if word.lower() in title_summary]
    major_entities_in_content = [word for word in editorial_fit.get("major_ai_entities", []) if word.lower() in haystack]
    release_terms = [word for word in editorial_fit.get("release_terms", []) if word.lower() in title_summary]
    interview_terms = [word for word in editorial_fit.get("authoritative_interview_terms", []) if word.lower() in haystack]
    event_terms = [word for word in editorial_fit.get("event_or_ad_terms", []) if word.lower() in title_summary]
    people_terms = [word for word in editorial_fit.get("people_profile_terms", []) if word.lower() in title_summary]
    concept_terms = ("harness", "skill", "mcp", "机制", "原理", "架构", "工作流", "缓存", "训练", "推理")
    authoritative_interview = bool(interview_terms and major_entities_in_content)
    if evergreen_terms:
        score += 12
        reasons.append("具备可长期回看的机制切口")
    if hype_terms:
        score -= 45
        penalties.append("炒作或猎奇成分过高")
    if broad_terms:
        score -= 30
        penalties.append("宏大或通稿式表述，缺少具体切口")
    if niche_terms:
        score -= 30
        penalties.append("科研或医疗垂直题，大众切口偏弱")
    if authoritative_interview:
        score += 24
        reasons.insert(0, "核心 AI 团队权威人物访谈，材料完整")
    if release_terms and not major_entities and not any(term in title_summary for term in concept_terms):
        score -= 35
        penalties.append("主体知名度或事件级别不足")
    if event_terms:
        score -= 55
        penalties.append("活动、采购或合作宣传稿")
    if people_terms and not authoritative_interview:
        score -= 30
        penalties.append("纯人物群像，缺少可复用的核心机制")

    score = round(score, 1)
    if content_status in {"transcript", "fulltext"} and language == "zh" and len(content) >= 1000:
        adaptation_readiness = "高"
        research_cost = "低"
    elif content_status in {"shownotes", "fulltext", "transcript"} and len(content) >= 400:
        adaptation_readiness = "中"
        research_cost = "中"
    else:
        adaptation_readiness = "低"
        research_cost = "高"
    return {
        **item,
        "id": item.get("id") or hashlib.sha1(f"{title}|{item.get('link', '')}".encode()).hexdigest()[:10],
        "title": title,
        "summary": summary,
        "content": content,
        "age_days": age_days,
        "pillars": matched_pillars,
        "score": score,
        "recommended": score >= profile["minimum_score"] and not excluded and not penalties and source_role == "candidate",
        "reason": "；".join(reasons[:6]) or "信息不足，等待人工判断",
        "penalty": "；".join(penalties),
        "language": language,
        "maturity": maturity,
        "content_status": content_status,
        "adaptation_readiness": adaptation_readiness,
        "research_cost": research_cost,
        "source_role": source_role,
    }


def rank_candidates(items: list[dict], profile: dict, now: datetime | None = None) -> list[dict]:
    scored = [score_item(item, profile, now=now) for item in deduplicate(items)]
    scored.sort(key=lambda item: (item["recommended"], item["score"]), reverse=True)
    return scored
