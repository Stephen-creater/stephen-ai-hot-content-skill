from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 index.html 导出的人工审核结果")
    parser.add_argument("feedback", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.feedback.read_text(encoding="utf-8"))
    target = ROOT / ".local" / "editorial_feedback.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"imported_at": datetime.now().isoformat(), **payload}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    reviews = payload.get("reviews", {})
    selected = sum(1 for value in reviews.values() if value.get("status") == "selected")
    rejected = sum(1 for value in reviews.values() if value.get("status") == "rejected")
    print(f"已导入：入选 {selected}，不入选 {rejected}，遗漏 {len(payload.get('missed', []))}")
    print(target)


if __name__ == "__main__":
    main()
