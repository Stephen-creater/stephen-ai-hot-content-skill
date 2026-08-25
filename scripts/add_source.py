from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = ROOT / ".local" / "source_inbox.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="向本地中文来源 inbox 添加内容")
    parser.add_argument("url")
    parser.add_argument("--platform", choices=["wechat", "bilibili", "xiaoyuzhou", "web"], required=True)
    parser.add_argument("--creator", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--published", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--transcript", dest="transcript_path", default="")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    args = parser.parse_args()

    args.inbox.parent.mkdir(parents=True, exist_ok=True)
    rows = json.loads(args.inbox.read_text(encoding="utf-8")) if args.inbox.exists() else []
    if any(row.get("url") == args.url for row in rows):
        raise SystemExit("该链接已经存在")
    rows.append(
        {
            "url": args.url,
            "platform": args.platform,
            "creator": args.creator,
            "title": args.title,
            "published": args.published,
            "notes": args.notes,
            "transcript_path": args.transcript_path,
        }
    )
    args.inbox.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.inbox)


if __name__ == "__main__":
    main()
