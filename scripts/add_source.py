from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INBOX = ROOT / ".local" / "source_inbox.json"


def append_source(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if any(existing.get("url") == row["url"] for existing in rows):
            raise SystemExit("该链接已经存在")
        rows.append(row)
        payload = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="向本地中文来源 inbox 添加内容")
    parser.add_argument("url")
    parser.add_argument(
        "--platform",
        choices=["wechat", "bilibili", "youtube", "xiaoyuzhou", "podcast", "web"],
        required=True,
    )
    parser.add_argument("--creator", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--published", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--maturity", choices=["secondary", "primary"], default="secondary")
    parser.add_argument("--transcript", dest="transcript_path", default="")
    parser.add_argument("--content-url", default="", help="用于抓取正文的公开原始文本链接；展示仍使用位置参数 URL")
    parser.add_argument("--content-json-key", default="", help="content-url 返回 JS/JSON 映射时选取指定正文键")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    args = parser.parse_args()

    append_source(
        args.inbox,
        {
            "url": args.url,
            "platform": args.platform,
            "creator": args.creator,
            "title": args.title,
            "published": args.published,
            "notes": args.notes,
            "maturity": args.maturity,
            "transcript_path": args.transcript_path,
            "content_url": args.content_url,
            "content_json_key": args.content_json_key,
        },
    )
    print(args.inbox)


if __name__ == "__main__":
    main()
