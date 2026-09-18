"""Load content_curator_sources.json and expand grouped feeds into plain sources."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "resources" / "content_curator_sources.json"


def expand_sources(config: dict) -> list[dict]:
    """Turn every ``rss_group`` entry into one ``rss`` source per feed.

    Group ``defaults`` apply to each feed; a feed's own fields win, except
    ``title_exclude_pattern``, which is joined so a feed can only add noise
    filters on top of the shared ones.
    """
    expanded = []
    for source in config.get("sources", []):
        if source.get("type") != "rss_group":
            expanded.append(source)
            continue
        defaults = source.get("defaults", {})
        for feed in source.get("feeds", []):
            row = {**defaults, **feed, "type": "rss", "group": source["name"]}
            row.setdefault("family", source.get("family"))
            row.setdefault("category", source.get("category", source["name"]))
            patterns = [p for p in (defaults.get("title_exclude_pattern"), feed.get("title_exclude_pattern")) if p]
            if patterns:
                row["title_exclude_pattern"] = "|".join(f"(?:{p})" for p in patterns)
            expanded.append(row)
    return expanded


def load_sources(path: Path = SOURCES) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    return {**config, "sources": expand_sources(config)}
