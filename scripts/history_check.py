"""Check draft materials against reviewed and delivered history before spending review time."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from curator import canonical_url
from discovery_history import delivered_candidates
from import_feedback import final_reviewed_candidates
from scrape_aihot import is_historical_content_duplicate

ROOT = Path(__file__).resolve().parents[1]


def duplicate_reason(row: dict, history: list[dict]) -> str:
    if row.get("id") and row.get("id") in {item.get("id") for item in history}:
        return "候选 ID 已出现"
    if canonical_url(row.get("link", "")) in {canonical_url(item.get("link", "")) for item in history if item.get("link")}:
        return "原文链接已出现"
    if is_historical_content_duplicate(row, history):
        return "正文与历史材料高度重合（常见于换标题转载）"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path, help="JSON 数组，每项至少含 link，最好含 title 与 content")
    parser.add_argument("--exclude-batch", type=Path, help="排除自身批次目录，避免与自己比较")
    args = parser.parse_args()
    rows = json.loads(args.draft.read_text(encoding="utf-8"))
    history = final_reviewed_candidates(ROOT / ".local/editorial_feedback.jsonl") + delivered_candidates(ROOT / "topics", args.exclude_batch)
    duplicates = 0
    for row in rows:
        reason = duplicate_reason(row, history)
        duplicates += bool(reason)
        print(json.dumps({"title": row.get("title", ""), "link": row.get("link", ""), "duplicate": bool(reason), "reason": reason}, ensure_ascii=False))
    sys.exit(1 if duplicates else 0)


if __name__ == "__main__":
    main()
