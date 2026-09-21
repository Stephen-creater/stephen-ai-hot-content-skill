from __future__ import annotations

import hashlib
import functools
from collections import Counter
import html
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from editorial_judgment import build_decision_contract


TAG_RE = re.compile(r"<[^>]+>")
VERSION_ONLY_RE = re.compile(r"^(?:[a-z-]+-)?v?\d+\.\d+(?:\.\d+)?(?:[-.][a-z0-9.]+)?$", re.I)
PACKAGE_VERSION_RE = re.compile(r"^[a-z0-9_.-]+\s+v?\d+\.\d+(?:\.\d+)?(?:[-.][a-z0-9.]+)?$", re.I)
CORE_AI_TERMS = (
    "ai", "agent", "llm", "model", "codex", "claude", "openai", "anthropic",
    "gemini", "deepmind", "skill", "mcp", "prompt", "inference", "training",
    "reasoning", "kimi", "workbuddy", "qoder", "cursor", "copilot", "openclaw", "chatgpt", "chatbox",
    "人工智能", "模型", "智能体", "推理", "训练", "上下文", "缓存", "豆包",
)
SECRET_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9._-]{20,}"),
)


TRADITIONAL_MARKERS = set("體學這為與從讓個裡實過開關點臺檔寫讀據動應處別進還題會時發現種選擇轉換價務圖頁製後設產")
MIGRATION_CONTEXT_RE = re.compile(r"迁移|迁出|离开|告别|替代|取代|弃用|换掉|不再用|转向|迁到|换到")

def contains_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9 .+-]+", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None
    return term in text


# Generic words such as 模型/训练/缓存 also describe databases and ML-free systems,
# so the body check counts only terms that name AI itself or AI products.
STRONG_AI_TERMS = (
    "ai", "aigc", "llm", "agent", "gpt", "chatgpt", "codex", "claude", "openai", "anthropic", "gemini",
    "deepmind", "deepseek", "qwen", "kimi", "cursor", "copilot", "openclaw", "workbuddy", "qoder", "mcp",
    "prompt", "人工智能", "智能体", "大模型", "提示词", "豆包", "千问",
)


def minimum_article_chars(profile: dict) -> int:
    """Shortest article body that can still carry a rewrite; one value for scoring, pooling and publishing."""
    return int(profile.get("minimum_article_chars", 800))


def ai_subject_in_body(summary: str, content: str) -> bool:
    """Feeds without a real summary (most WeChat RSS) leave only the title to judge.

    Then the opening paragraphs stand in for the summary, and strong AI terms must
    keep recurring in the body so a passing mention cannot qualify an unrelated piece.
    """
    if len(summary) >= 80 or not content:
        return False
    lowered = content.lower()
    if not any(contains_term(lowered[:600], term) for term in STRONG_AI_TERMS):
        return False
    hits = sum(len(re.findall(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)) if re.fullmatch(r"[a-z0-9 .+-]+", term)
               else lowered.count(term) for term in STRONG_AI_TERMS)
    return hits >= 8


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def redact_untrusted_secrets(value: str | None) -> str:
    text = value or ""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_CREDENTIAL]", text)
    return text


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    tracking = {"fbclid", "gclid", "msclkid", "spm", "from", "main2", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        tracking |= {"si", "t", "start", "feature"}
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in tracking and not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), urlencode(sorted(query)), ""))


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


@functools.lru_cache(maxsize=16384)
def normalized_title(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalized_title(left), normalized_title(right)).ratio()


@functools.lru_cache(maxsize=16384)
def title_char_counts(text: str) -> Counter:
    return Counter(normalized_title(text))


def titles_at_least(left: str, right: str, threshold: float) -> bool:
    """Same verdict as title_similarity >= threshold, rejecting most pairs by difflib's own upper bounds first."""
    a, b = normalized_title(left), normalized_title(right)
    total = len(a) + len(b)
    if not total:
        return True
    # real_quick_ratio and quick_ratio bounds, computed without building a matcher for every pair.
    if 2.0 * min(len(a), len(b)) / total < threshold:
        return False
    if 2.0 * sum((title_char_counts(left) & title_char_counts(right)).values()) / total < threshold:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def deduplicate(items: list[dict]) -> list[dict]:
    kept: list[dict] = []

    def same_title_content(left: dict, right: dict) -> bool:
        if not titles_at_least(left.get("title", ""), right.get("title", ""), 0.86):
            return False
        texts = [re.sub(r"\W+", "", clean_text(row.get("content", "")).lower()) for row in (left, right)]
        if not all(row.get("content_status") in {"fulltext", "transcript"} for row in (left, right)) or min(map(len, texts)) < 400:
            return True
        shingles = [{text[i:i + 16] for i in range(len(text) - 15)} for text in texts]
        return len(shingles[0] & shingles[1]) / min(map(len, shingles)) >= 0.68

    def richness(item: dict) -> tuple[int, int, int]:
        status_rank = {"transcript": 3, "fulltext": 2, "shownotes": 1, "summary": 0}
        return (
            status_rank.get(item.get("content_status", "summary"), 0),
            len(clean_text(item.get("content"))),
            int(item.get("source_priority", 0)),
        )

    urls: list[str] = []
    for item in items:
        url = canonical_url(item.get("link", ""))
        duplicate_index = next(
            (
                index
                for index, old in enumerate(kept)
                if (url and url == urls[index]) or same_title_content(item, old)
            ),
            None,
        )
        if duplicate_index is not None:
            if richness(item) > richness(kept[duplicate_index]):
                kept[duplicate_index] = item
                urls[duplicate_index] = url
            continue
        kept.append(item)
        urls.append(url)
    return kept


def score_item(item: dict, profile: dict, now: datetime | None = None) -> dict:
    """Apply the one-vote rules and compute reading order. No keyword-based judgment.

    Whether a piece is worth writing is decided by an Agent reading the full text.
    """
    now = now or datetime.now(timezone.utc)
    title = clean_text(item.get("source_title") or item.get("title"))
    summary = clean_text(item.get("summary") or item.get("description"))
    raw_content = redact_untrusted_secrets(item.get("content"))
    content = clean_text(raw_content)
    haystack = f"{title} {summary} {content}".lower()
    title_summary = f"{title} {summary}".lower()
    failures: list[str] = []
    reasons: list[str] = []
    gates = profile.get("gate_terms", {})

    language = item.get("language", "unknown")
    maturity = item.get("maturity", "unknown")
    content_status = item.get("content_status", "fulltext" if len(content) >= 500 else "summary")
    content_form = item.get("content_form", "article")
    source_role = item.get("source_role", "candidate")
    source_domain = urlsplit(item.get("link", "")).netloc.lower()
    source_name = clean_text(item.get("source_name")).lower()
    github_stars = item.get("github_stars")

    # Language
    if language == "zh" and len(content) >= 400 and len(re.findall(r"[\u4e00-\u9fff]", content)) < 20:
        failures.append("正文缺少中文内容，不能按中文标签放行")
    if profile.get("required_chinese_script") == "simplified":
        chinese = re.findall(r"[\u4e00-\u9fff]", content or title)
        traditional_count = sum(char in TRADITIONAL_MARKERS for char in chinese)
        if traditional_count >= 12 and traditional_count / max(len(chinese), 1) >= 0.02:
            failures.append("原文为繁体中文，要求简体中文材料")
    if source_role == "verification":
        failures.append("核验来源，不进入默认选题")

    # Stephen 二创要重做配图：阈值见口味档案。2026-09-20 三篇 13 到 23 张的写了 image_plan 仍被拒；
    # 2026-09-21 b 批三篇正好 10 张的也全被拒，其中一篇的备注是“图片、视频太多了”。
    image_count = item.get("image_count")
    if isinstance(image_count, int) and image_count >= int(profile.get("maximum_images_hard", 10)):
        failures.append(f"配图 {image_count} 张，超过二创能承受的数量")
    video_count = item.get("video_count")
    if isinstance(video_count, int) and video_count >= int(profile.get("maximum_videos_hard", 2)):
        failures.append(f"嵌入视频 {video_count} 段，超过二创能承受的数量")

    # Exact topic state: written, deferred, disfavored, retired, excluded, blocked
    covered_pattern = any(re.search(pattern, title_summary, re.I) for pattern in profile.get("covered_topic_patterns", []))
    karpathy_wiki = any(term in title_summary for term in ("karpathy", "卡帕西", "卡帕斯")) and "知识库" in title_summary
    if covered_pattern or karpathy_wiki or any(term.lower() in title_summary for term in profile.get("covered_topic_terms", [])):
        failures.append("主题已写过，不重复推荐")
    if "workbuddy" in title_summary and any(term in title_summary for term in profile.get("deferred_basic_workbuddy_terms", [])):
        failures.append("WorkBuddy 常规岗位基础应用暂缓推荐")
    # Leaving or replacing a retired tool is a different subject from promoting it.
    migration_context = bool(MIGRATION_CONTEXT_RE.search(title_summary))
    # 只看标题：顺带提到（三款产品对比里的一款）不等于文章在讲它。
    if not migration_context and any(term.lower() in title.lower() for term in profile.get("disfavored_product_subject_terms", [])):
        failures.append("用户当前不认可该产品，不推荐其主体实测或介绍")
    if not migration_context and any(term.lower() in title_summary for term in profile.get("retired_workflow_platform_subject_terms", [])):
        failures.append("传统节点式 Workflow 平台已被用户明确淘汰，不再作为选题主体")
    personal_activity_recall = (
        any(term in haystack for term in ("computer history", "个人电脑活动回忆", "个人工作记忆"))
        and any(term in haystack for term in ("找回工作", "恢复工作", "工作上下文", "工作状态"))
        and any(term in haystack for term in ("默认关闭", "默认是关闭", "主动开启"))
        and "暂停" in haystack
        and not any(term in title_summary for term in ("员工", "监视", "偷窥", "伴侣", "孩子", "他人", "考勤"))
    )
    excluded = [word for word in profile.get("exclude_keywords", []) if word.lower() in title_summary
                and not (word == "监控" and personal_activity_recall)]
    if excluded:
        failures.append("命中排除词" + "、".join(excluded[:2]))
    if any(source_domain == domain or source_domain.endswith(f".{domain}") for domain in profile.get("blocked_domains", [])):
        failures.append("来源域名已被明确排除")
    if any(term.lower() in f"{source_name} {title.lower()}" for term in profile.get("blocked_creators", [])):
        failures.append("作者或个人 IP 已被明确排除")

    # Age
    published = parse_datetime(item.get("published") or item.get("article_date"))
    age_days = max(0, (now - published).days) if published else None
    if age_days is not None:
        if age_days > profile["max_age_days"]:
            failures.append("超过时效范围")
        elif age_days <= profile["priority_days"]:
            reasons.append("最近一周发布" if age_days <= 7 else "最近两周发布")
    product_update = bool(re.search(r"(?:版本|模型|产品|功能|软件|系统).{0,8}更新|更新.{0,8}(?:版本|模型|产品|功能|软件|系统)", title_summary))
    product_withdrawal = bool(re.search(
        r"(?:版本|模型|产品|功能|软件|系统|服务|发布|上线|公告).{0,8}撤回|撤回.{0,8}(?:版本|模型|产品|功能|软件|系统|服务|发布|上线|公告)",
        title_summary,
    ))
    event_words = [
        word for word in gates.get("time_sensitive_event_terms", [])
        if word.lower() in title_summary and (word != "更新" or product_update) and (word != "撤回" or product_withdrawal)
    ]
    # An interview is not event news just because a launch is mentioned in passing.
    interview_words = gates.get("interview_terms", [])
    core_team_interview = any(word.lower() in title_summary for word in interview_words) and any(
        entity.lower() in haystack for entity in gates.get("major_ai_entities", []))
    long_interview = (
        any(word.lower() in title.lower() for word in interview_words)
        and not any(word.lower() in title.lower() for word in event_words)
        and len(content) >= minimum_article_chars(profile)
    )
    # Stephen writes major launches the same day straight from the official English post;
    # other English material, and official posts past the launch window, stay leads.
    official_release = bool(item.get("official_release")) and age_days is not None and age_days <= int(profile.get("time_sensitive_max_age_days", 5))
    if official_release:
        reasons.append("官方发布原文，仍在事件时效窗口内")
    if age_days is not None and event_words and not (core_team_interview or long_interview) and age_days > int(profile.get("time_sensitive_max_age_days", 5)):
        failures.append("事件新闻已超过时效窗口")

    # Complete, public text
    if content_status == "transcript":
        reasons.append("已有逐字稿")
    elif content_status == "fulltext":
        reasons.append("已有完整正文")
    elif content_status == "shownotes":
        reasons.append("已有详细 Show Notes")
    else:
        failures.append("缺少完整文字材料")
    if content_form == "podcast" and content_status != "transcript":
        failures.append("播客缺少逐字稿，无法低成本二创")
    if content_form == "video" and content_status != "transcript":
        failures.append("视频缺少逐字稿，无法核验完整论证")
    if len(content) < 500 and len(summary) < 80:
        failures.append("材料过少")
    if content_status == "blocked":
        failures.append("站点返回验证页，没有取到正文")
    # X 和即刻的帖子是平台原生写法，写满五百字已经是完整的一篇，不按公众号长文的尺子量。
    minimum_chars = int(profile.get("social_minimum_article_chars", 500)) if item.get("social_post") else minimum_article_chars(profile)
    if content_form == "article" and content_status == "fulltext" and len(content) < minimum_chars:
        failures.append("文章正文偏短，不足以支撑高质量二创")
    if any(word.lower() in haystack for word in gates.get("locked_content_terms", [])):
        failures.append("正文被登录、关注或付费墙截断，材料不完整")
    if VERSION_ONLY_RE.fullmatch(title.strip()) or PACKAGE_VERSION_RE.fullmatch(title.strip()):
        failures.append("只有版本号")
    if not any(contains_term(title_summary, term) for term in CORE_AI_TERMS) and not ai_subject_in_body(summary, content):
        failures.append("标题与摘要缺少明确 AI 对象")
    if re.search(r"(?:本文|本篇内容).{0,24}(?:由|使用).{0,40}(?:ai|codex|豆包|claude|gpt).{0,24}(?:生成|完成|创作)", haystack[:1200], flags=re.I):
        failures.append("文章主动披露由 AI 生成，不作为 Stephen 二创底稿")

    # GitHub
    if source_domain == "github.com":
        if github_stars is None:
            failures.append("GitHub Star 数未核验，不能进入候选")
        elif int(github_stars) < int(profile.get("minimum_github_stars", 100)):
            failures.append("GitHub Star 低于 100，不进入候选")
        else:
            reasons.insert(0, f"GitHub {int(github_stars)} Star，达到入场门槛")
        if age_days is None or age_days > 7:
            failures.append("GitHub 最近有效发布或更新超过 7 天，不再算当前热点")

    if language == profile.get("preferred_language"):
        reasons.append("中文内容")
    if maturity == profile.get("preferred_maturity"):
        reasons.append("作者已完成二手整合")

    # Reading order: source priority, freshness, Chinese, edited secondary source, full text.
    reading_order = int(item.get("source_priority", 3)) * 2
    reading_order += max(0, 18 - age_days) if age_days is not None else 0
    reading_order += 18 if language == profile.get("preferred_language") else 0
    reading_order += 16 if maturity == profile.get("preferred_maturity") else (-15 if maturity == "primary" and not official_release else 0)
    reading_order += 34 if official_release else 0
    reading_order += {"transcript": 20, "fulltext": 15, "shownotes": 8}.get(content_status, 0)

    if content_status in {"transcript", "fulltext"} and (language == "zh" or official_release) and len(content) >= 1000:
        adaptation_readiness, research_cost = "高", "低"
    elif content_status in {"shownotes", "fulltext", "transcript"} and len(content) >= 400:
        adaptation_readiness, research_cost = "中", "中"
    else:
        adaptation_readiness, research_cost = "低", "高"
    decision_contract = build_decision_contract(item, penalties=failures)
    eligible = decision_contract["eligibility"]["status"] == "passed"
    return {
        **item,
        "id": item.get("id") or hashlib.sha1(f"{title}|{item.get('link', '')}".encode()).hexdigest()[:10],
        "title": title,
        "summary": summary,
        "content": raw_content,
        "age_days": age_days,
        "score": reading_order,
        "reading_order": reading_order,
        "recommended": eligible and source_role == "candidate",
        "machine_shortlisted": eligible and source_role == "candidate",
        "reason": "；".join(reasons[:6]) or "信息不足，等待人工判断",
        "penalty": "；".join(failures),
        "language": language,
        "maturity": maturity,
        "content_status": content_status,
        "adaptation_readiness": adaptation_readiness,
        "research_cost": research_cost,
        "source_role": source_role,
        "editorial_decision": decision_contract,
    }


def rank_candidates(items: list[dict], profile: dict, now: datetime | None = None) -> list[dict]:
    scored = [score_item(item, profile, now=now) for item in deduplicate(items)]
    scored.sort(key=lambda item: (item["editorial_decision"]["eligibility"]["status"] == "passed", item["reading_order"]), reverse=True)
    return scored
