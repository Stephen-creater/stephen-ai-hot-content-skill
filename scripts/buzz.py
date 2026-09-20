"""找出最近几天在很多来源同时刷屏的新名字（新模型、新产品、新概念）。

单篇文章看不出热度：一个创业公司的新模型，读一篇报道会觉得是小众产品，
但它三天内出现在十几个来源里，就是 Stephen 会写的“火爆全网的 X 到底是什么”。

不用选题关键词表。每个词只和它自己的历史比：最近 3 天出现在多少个不同来源，
前几周又出现在多少个来源。平时就常见的词（the、Claude、OpenAI）历史基数高，不会上榜。
历史存在本机 .local/buzz_history.json，按文章链接去重，保留 30 天。
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from curator import parse_datetime

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / ".local" / "buzz_history.json"

TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*)(?![A-Za-z0-9])")
NOISE = re.compile(r"https?://\S+|@\w+")
# English function words: a language filter, not an editorial one.
FUNCTION_WORDS = set("""
the and for with are this that your can you not its our their from have has was were will just how what why when who
new one all more most than into out about over after before use used using get got now here there they them his her
been being also only some any each very make made like via per but yet off too may might should would could
""".split())
KEEP_DAYS = 30
RECENT_DAYS = 3
BASELINE_DAYS = 18  # the weeks before the recent window


def terms(item: dict) -> set[str]:
    text = NOISE.sub(" ", f"{item.get('title', '')} {str(item.get('summary') or '')[:280]}")
    return {token.lower() for token in TOKEN.findall(text) if len(token) >= 3} - FUNCTION_WORDS


def title_terms(item: dict) -> set[str]:
    """English names inside a Chinese title; Chinese titles rarely carry English words that are not names."""
    title = str(item.get("title") or "")
    if len(re.findall(r"[一-鿿]", title)) < 4:
        return set()
    return {token.lower() for token in TOKEN.findall(NOISE.sub(" ", title)) if len(token) >= 3} - FUNCTION_WORDS


def load_history(path: Path = HISTORY) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(items: list[dict], now: datetime, history: dict) -> dict:
    """Add each dated item once (keyed by link) and drop entries older than KEEP_DAYS."""
    for item in items:
        published = parse_datetime(item.get("published"))
        if not published or not item.get("link"):
            continue
        history[item["link"]] = {
            "date": published.date().isoformat(),
            "source": (item.get("source_name") or "").strip().lower(),
            "zh_title_terms": sorted(title_terms(item)),
            "terms": sorted(terms(item)),
            "title": str(item.get("title") or "")[:120],
        }
    cutoff = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    return {link: row for link, row in history.items() if row["date"] >= cutoff}


def detect(history: dict, now: datetime, *, min_sources: int = 4, min_chinese: int = 2, ratio: float = 3.0) -> list[dict]:
    recent_from = (now - timedelta(days=RECENT_DAYS)).date().isoformat()
    baseline_from = (now - timedelta(days=RECENT_DAYS + BASELINE_DAYS)).date().isoformat()
    recent: dict[str, dict[str, dict]] = defaultdict(dict)
    chinese: dict[str, set[str]] = defaultdict(set)
    baseline: dict[str, set[str]] = defaultdict(set)
    for link, row in history.items():
        for term in row["terms"]:
            if row["date"] >= recent_from:
                recent[term].setdefault(row["source"], {"title": row["title"], "link": link})
                if term in row.get("zh_title_terms", []):
                    chinese[term].add(row["source"])
            elif row["date"] >= baseline_from:
                baseline[term].add(row["source"])
    found = []
    for term, sources in recent.items():
        # Distinct sources saturate over time, so compare counts directly rather than per day.
        if len(sources) >= min_sources and len(chinese[term]) >= min_chinese and len(sources) >= ratio * (len(baseline[term]) + 1):
            found.append({
                "term": term, "sources": len(sources), "chinese_sources": len(chinese[term]),
                "baseline_sources": len(baseline[term]), "examples": list(sources.values())[:6],
            })
    found.sort(key=lambda row: -row["sources"])
    # A name and its company often rise together (jev, typesafe); keep the one with more sources.
    kept: list[dict] = []
    for row in found:
        links = {example["link"] for example in row["examples"]}
        if not any(len(links & {example["link"] for example in other["examples"]}) >= 2 for other in kept):
            kept.append(row)
    return kept


def render(rows: list[dict]) -> str:
    """英文圈先热、中文还没跟进的名字不在这里：只按英文来源统计时，噪声全是 think、need 这类常用词。
    那段时间差由 Agent 每批用 ego-browser 直接看 X 覆盖，见 SKILL.md 第 2 步。"""
    if not rows:
        return ""
    lines = [
        "## 最近 3 天多源刷屏",
        "",
        "这些名字最近 3 天在很多不同来源里同时出现，前几周却很少见。刷屏的新模型、新产品、新概念，",
        "即使来自创业公司、只开放候补名单，也是 Stephen 会写的“火爆全网的 X 到底是什么”。先看这里，再看下面的清单。",
        "",
    ]
    for row in rows:
        lines.append(f"- **{row['term']}**：{row['sources']} 个来源（其中 {row['chinese_sources']} 个中文标题），前 {BASELINE_DAYS} 天 {row['baseline_sources']} 个")
        for example in row["examples"][:4]:
            lines.append(f"  - [{example['title']}]({example['link']})")
    return "\n".join(lines) + "\n\n"


def update(items: list[dict], now: datetime, path: Path = HISTORY) -> list[dict]:
    history = record(items, now, load_history(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    return detect(history, now)
