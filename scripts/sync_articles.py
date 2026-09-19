"""把 Stephen 已发布的文章从飞书知识库只读同步到本机 .local/articles/。

这些文章是判断“他会写什么”的最强依据，也是“已经写过”的权威清单。
全文只存本机，不提交。知识库位置写在 .config/articles_source.json：

  {"space_id": "...", "root_node_token": "..."}

需要本机已登录的 lark-cli（只读取，不修改飞书里的任何内容）。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".config" / "articles_source.json"
OUT = ROOT / ".local" / "articles"

Runner = Callable[[list[str]], dict | None]


def lark(args: list[str]) -> dict | None:
    result = subprocess.run(["lark-cli", *args], capture_output=True, text=True, timeout=120)
    return json.loads(result.stdout) if result.stdout.strip().startswith("{") else None


def safe_name(parts: list[str]) -> str:
    return re.sub(r'[\\/:*?"<>|\n]', "_", "__".join(parts))[:150] + ".md"


def sync(space_id: str, root: str, out: Path = OUT, run: Runner = lark) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []

    def walk(token: str, path: list[str], depth: int) -> None:
        listing = run(["wiki", "+node-list", "--space-id", space_id, "--parent-node-token", token, "--page-all"]) or {}
        for node in listing.get("data", {}).get("nodes", []):
            title = node.get("title") or node["node_token"]
            record = {"path": path + [title], "node_token": node["node_token"], "obj_type": node.get("obj_type"), "depth": depth}
            if node.get("obj_type") == "docx":
                fetched = run(["docs", "+fetch", "--doc", node["obj_token"], "--doc-format", "markdown"]) or {}
                content = fetched.get("data", {}).get("document", {}).get("content", "")
                name = safe_name(path + [title])
                (out / name).write_text(content, encoding="utf-8")
                record.update(file=name, chars=len(content))
            index.append(record)
            if node.get("has_child"):
                walk(node["node_token"], path + [title], depth + 1)

    walk(root, [], 0)
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def main() -> None:
    if not CONFIG.exists():
        raise SystemExit(f"缺少 {CONFIG}，内容形如 {{\"space_id\": \"...\", \"root_node_token\": \"...\"}}")
    source = json.loads(CONFIG.read_text(encoding="utf-8"))
    index = sync(source["space_id"], source["root_node_token"])
    articles = [row for row in index if row.get("chars", 0) > 300]
    print(f"已同步 {len(articles)} 篇文章到 {OUT}；新文章请补进 published_topics.md 和 .local/eval/adoptions.json")


if __name__ == "__main__":
    main()
