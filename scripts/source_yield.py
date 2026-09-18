"""Report reviewer outcomes per source so reading order follows observed yield.

Only button states count. The report ranks sources; it never changes source
config or editorial rules by itself.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_HOSTS = {"mp.weixin.qq.com", "wechat2rss.bestblogs.dev", "wechat2rss.xlab.app", "www.bestblogs.dev", "bestblogs.dev"}


def source_key(candidate: dict) -> str:
    """Account name for WeChat-like platforms, otherwise the site host."""
    host = urlsplit(str(candidate.get("link", ""))).netloc.lower().removeprefix("www.")
    name = str(candidate.get("source_name", "")).strip()
    if name and (not host or host in PLATFORM_HOSTS or f"www.{host}" in PLATFORM_HOSTS):
        return re.split(r"\s*[/·｜|（(]\s*", name)[0] or name
    return host or name or "<unknown>"


def source_yield(path: Path) -> list[dict]:
    """Latest decision per candidate id, grouped by source key."""
    candidates: dict[str, dict] = {}
    decisions: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for row in record.get("candidates", []):
            if isinstance(row, dict) and row.get("id"):
                candidates[str(row["id"])] = row
        for item_id, review in (record.get("reviews") or {}).items():
            status = (review or {}).get("status")
            if status in {"selected", "rejected"}:
                decisions[str(item_id)] = status
    stats: dict[str, dict] = defaultdict(lambda: {"selected": 0, "rejected": 0, "selected_titles": []})
    for item_id, status in decisions.items():
        candidate = candidates.get(item_id, {})
        row = stats[source_key(candidate)]
        row[status] += 1
        if status == "selected":
            row["selected_titles"].append(str(candidate.get("title", ""))[:60])
    rows = []
    for key, row in stats.items():
        decided = row["selected"] + row["rejected"]
        rows.append({
            "source": key,
            "decided": decided,
            **row,
            # Beta(1, 3) prior: one lucky pick from a new source does not outrank a proven one.
            "smoothed_rate": round((row["selected"] + 1) / (decided + 4), 3),
        })
    rows.sort(key=lambda r: (-r["smoothed_rate"], -r["decided"], r["source"]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="按来源统计审核按钮结果，用于决定阅读顺序")
    parser.add_argument("feedback", type=Path, nargs="?", default=ROOT / ".local" / "editorial_feedback.jsonl")
    parser.add_argument("--min-decided", type=int, default=2, help="只显示至少有这么多次决定的来源")
    args = parser.parse_args()
    rows = [row for row in source_yield(args.feedback) if row["decided"] >= args.min_decided]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
