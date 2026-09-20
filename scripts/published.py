"""把候选和 Stephen 已经写成文章的主题对上号。

Agent 对照 `.local/articles/published_topics.md` 自己查重不可靠：2026-09-20 一批 20 条里有 9 条
是写过的主题（Jev 前一天刚写，DeepSeek Harness 四条）。所以抓取时就机械地标出来。

宁可标多，不可放过：标中不等于淘汰，只是要求交付前说清这次有什么新进展，
`publish_batch.py` 会检查这句话在不在。真正是不是重复，由读完全文的 Agent 判断。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTICLES = ROOT / ".local" / "articles"

WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.\-][A-Za-z0-9]+)*")
CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
COMMON_WORDS = {"the", "and", "for", "with", "you", "your", "how", "what", "why", "ai", "app", "api", "llm", "agent", "agents"}
COMMON_AT_LEAST = 4  # a name in this many article titles names the field, not one article's topic
MINIMUM_ARTICLE_CHARS = 300


def article_titles(directory: Path = ARTICLES) -> list[str]:
    try:
        index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    titles = []
    for row in index:
        if row.get("chars", 0) < MINIMUM_ARTICLE_CHARS or not row.get("path"):
            continue
        title = re.sub(r"^[\d.]+\s*|【[^】]*】", "", row["path"][-1]).strip()
        if title:
            titles.append(title)
    return titles


def names(text: str) -> set[str]:
    """Latin words, plus four-character Chinese runs — long enough not to collide by accident."""
    found = {word.lower() for word in WORD.findall(text) if len(word) >= 3} - COMMON_WORDS
    for run in CJK_RUN.findall(text):
        found |= {run[index:index + 4] for index in range(max(0, len(run) - 3))}
    return found


def build_index(titles: list[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for title in titles:
        for name in names(title):
            index.setdefault(name, []).append(title)
    return {name: rows for name, rows in index.items() if len(rows) < COMMON_AT_LEAST}


def written_about(title: str, index: dict[str, list[str]]) -> str:
    """The published article this candidate may repeat, or an empty string."""
    hits: dict[str, int] = {}
    for name in names(title):
        for article in index.get(name, []):
            hits[article] = hits.get(article, 0) + 1
    return max(hits, key=hits.get) if hits else ""


def annotate(items: list[dict], directory: Path = ARTICLES) -> list[dict]:
    index = build_index(article_titles(directory))
    if not index:
        return items
    for item in items:
        match = written_about(str(item.get("title") or ""), index)
        if match:
            item["written_topic_hint"] = match
    return items
