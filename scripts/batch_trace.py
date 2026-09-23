"""一批选题的执行轨迹：搜了哪些渠道、抓了几轮、每个源漏了多少、发布检查拦了几次、最后交了几条、Stephen 通过几条。

数据都在本机：抓取输出 .local/work/<批次ID>/*/run.json，搜索记录 .local/discovery_attempts.jsonl，
发布检查记录 .local/trace/<批次ID>.jsonl（publish_batch.py 每次检查都写一笔），交付 topics/<批次ID>/candidates.json，
审核结果 .local/editorial_feedback.jsonl。

最要紧的一项是“被拦下后改卡放行”：同一条候选先被发布检查拦下，终审卡改了内容后又通过。
这可能是真的改对了，也可能是换个说法绕过检查（2026-09-22 a 批就是凑数时这样放行的），要人看一眼。

用法：.venv/bin/python3 scripts/batch_trace.py <批次ID> [--markdown]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def rewritten_after_block(checks: list[dict]) -> list[dict]:
    """先被拦、改了终审卡后又通过的候选。"""
    found = []
    by_id: dict[str, list[dict]] = {}
    for row in checks:
        by_id.setdefault(str(row.get("id")), []).append(row)
    for item_id, rows in by_id.items():
        blocked = [row for row in rows if not row.get("ok")]
        passed = [row for row in rows if row.get("ok")]
        if blocked and passed and passed[-1].get("card") not in {row.get("card") for row in blocked}:
            found.append({"id": item_id, "title": passed[-1].get("title"), "blocked_for": blocked[-1].get("errors", [])[:3]})
    return found


def trace(batch: str, root: Path = ROOT) -> dict:
    rounds = []
    funnel: dict[str, Counter] = {}
    for run_path in sorted((root / ".local" / "work" / batch).glob("*/run.json")):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rounds.append({"at": run.get("generated_at"), "input": run.get("input_count"), "rejected_by_gate": run.get("rejected_by_gate_count"),
                       "blocked_by_site": run.get("blocked_by_site_count"), "pool": run.get("candidate_count")})
        for row in run.get("source_funnel", []):
            counter = funnel.setdefault(row["source"], Counter())
            counter["listed"] += row["listed"]
            counter["fulltext"] += row["fulltext"]
            counter["eligible"] += row["eligible"]
    searches = [row for row in read_jsonl(root / ".local" / "discovery_attempts.jsonl") if row.get("batch") == batch]
    checks = read_jsonl(root / ".local" / "trace" / f"{batch}.jsonl")
    delivered_path = root / "topics" / batch / "candidates.json"
    delivered = json.loads(delivered_path.read_text(encoding="utf-8")) if delivered_path.exists() else []
    profile = json.loads((root / "resources" / "editorial_profile.json").read_text(encoding="utf-8"))
    selected = rejected = 0
    for record in read_jsonl(root / ".local" / "editorial_feedback.jsonl"):
        if str(record.get("generated_at", "")) != batch:
            continue
        for review in (record.get("reviews") or {}).values():
            selected += review.get("status") == "selected"
            rejected += review.get("status") == "rejected"
    leaky = sorted(
        ({"source": name, "listed": c["listed"], "missing": c["listed"] - c["fulltext"], "eligible": c["eligible"]} for name, c in funnel.items()),
        key=lambda row: -row["missing"],
    )
    target = int(profile.get("default_topic_count", 10))
    return {
        "batch": batch,
        "rounds": rounds,
        "searches": {"total": len(searches), "channels": dict(Counter(row.get("channel") for row in searches)),
                     "failed": sum(row.get("status") not in {"success", None} for row in searches)},
        "source_leaks": [row for row in leaky if row["missing"]][:15],
        "publish_checks": {"total": len(checks), "blocked": sum(not row.get("ok") for row in checks)},
        "rewritten_after_block": rewritten_after_block(checks),
        "delivered": len(delivered), "target": target,
        "stephen": {"selected": selected, "rejected": rejected},
    }


def render_markdown(result: dict) -> str:
    lines = [f"## 执行轨迹：{result['batch']}", ""]
    lines.append(f"- 抓取 {len(result['rounds'])} 轮，搜索 {result['searches']['total']} 次（失败 {result['searches']['failed']} 次），渠道：" +
                 ("、".join(f"{k} {v}" for k, v in result["searches"]["channels"].items()) or "没有记录"))
    lines.append(f"- 交付 {result['delivered']} 条（目标 {result['target']}），Stephen 选中 {result['stephen']['selected']}、拒绝 {result['stephen']['rejected']}")
    lines.append(f"- 发布检查 {result['publish_checks']['total']} 次，拦下 {result['publish_checks']['blocked']} 次")
    if result["rewritten_after_block"]:
        lines.append("- **被拦下后改卡放行的**（要人看一眼是不是换说法绕过检查）：")
        lines += [f"  - {row['title']}：先因 {'；'.join(row['blocked_for'])} 被拦" for row in result["rewritten_after_block"]]
    if result["source_leaks"]:
        lines.append("- 列出来却没拿到全文最多的源：" + "、".join(f"{row['source']} 漏 {row['missing']}/{row['listed']}" for row in result["source_leaks"][:8]))
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    result = trace(args.batch)
    print(render_markdown(result) if args.markdown else json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
