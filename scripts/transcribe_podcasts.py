"""挑本批最值得的播客，转成逐字稿并登记成候选。

播客只有逐字稿才能低成本二创。BestBlogs 只覆盖约三十档节目，其余节目以前就卡在这里。
整期转写一次几分钟，不适合每条都跑，所以每批只挑几期：按来源优先级和新鲜度排，
默认 2 期，转完写进 inbox，重跑抓取时按普通候选判定。

    .venv/bin/python3 scripts/transcribe_podcasts.py .local/work/<批次ID>/<时间戳> --limit 2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from add_source import append_source
from curator import canonical_url, clean_text, parse_datetime
from harvest_leads import known_urls
from transcribe_audio import DEFAULT_MODEL, save, transcribe

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / ".local" / "source_inbox.json"
DEFAULT_LIMIT = 2


def pick(items: list[dict], limit: int, skip: set[str]) -> list[dict]:
    """有音频、还没有逐字稿、没登记过的，按来源优先级和新鲜度排。"""
    rows = [
        item for item in items
        if item.get("audio_url") and item.get("content_status") != "transcript"
        and canonical_url(item.get("link", "")) not in skip
    ]
    rows.sort(key=lambda item: (
        -int(item.get("source_priority", 3)),
        -(parse_datetime(item.get("published")).timestamp() if parse_datetime(item.get("published")) else 0),
    ))
    return rows[:limit]


def run(items: list[dict], limit: int = DEFAULT_LIMIT, model: Path = DEFAULT_MODEL,
        inbox: Path = INBOX, max_minutes: int = 0) -> list[dict]:
    done = []
    for item in pick(items, limit, known_urls(inbox)):
        title = clean_text(item.get("title")) or item["link"]
        try:
            text = transcribe(item["audio_url"], model=model, max_minutes=max_minutes)
        except Exception as exc:
            done.append({"title": title, "ok": False, "note": str(exc)[:120]})
            continue
        path = save(text, title)
        append_source(inbox, {
            "url": item["link"], "platform": "xiaoyuzhou", "creator": clean_text(item.get("source_name")),
            "title": title, "source_title": title, "editorial_angle": "",
            "published": item.get("published", ""), "notes": "本机转写的机器稿，专名待校对",
            "maturity": "primary", "language": "zh", "official_release": False,
            "transcript_path": str(path), "content_file": "", "content_url": "",
            "content_json_key": "", "github_stars": None,
        })
        done.append({"title": title, "ok": True, "chars": len(text), "transcript": str(path)})
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="抓取输出目录，读它的 eligible.json / candidates.json")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--max-minutes", type=int, default=0, help="只转前 N 分钟，0 表示整期")
    args = parser.parse_args()
    items = []
    for name in ("eligible.json", "candidates.json"):
        path = args.run / name
        if path.exists():
            items += json.loads(path.read_text(encoding="utf-8"))
    if not items:
        raise SystemExit("抓取输出目录里没有 eligible.json 或 candidates.json")
    for row in run(items, args.limit, args.model, max_minutes=args.max_minutes):
        print(json.dumps(row, ensure_ascii=False))
    print(f"转写完成后重跑抓取：--inbox {INBOX}")


if __name__ == "__main__":
    main()
