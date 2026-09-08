"""Locked, private ledger for measuring discovery-channel yield."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / ".local" / "discovery_attempts.jsonl"
PORTFOLIO = ROOT / "resources" / "source_portfolio.json"


def valid_families() -> set[str]:
    data = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    return {row["id"] for row in data["families"]}


def record_attempt(path: Path, entry: dict) -> None:
    if entry["family"] not in valid_families():
        raise ValueError(f"未知来源族：{entry['family']}")
    numeric = ("result_count", "fulltext_count", "eligible_count", "selected_count")
    if any(not isinstance(entry.get(key), int) or entry[key] < 0 for key in numeric):
        raise ValueError("结果、全文、合格与入选数量必须是非负整数")
    if not (entry["selected_count"] <= entry["eligible_count"] <= entry["fulltext_count"] <= entry["result_count"]):
        raise ValueError("数量必须满足 selected <= eligible <= fulltext <= result")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(), **entry}, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def load_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"检索账本第 {number} 行损坏：{exc}") from exc
        rows.append(row)
    return rows


def summarize(entries: list[dict], batch: str | None = None) -> dict:
    selected = [row for row in entries if batch is None or row.get("batch") == batch]
    groups: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "results": 0, "fulltexts": 0, "eligible": 0, "selected": 0, "failures": 0, "blocked": 0})
    for row in selected:
        group = groups[row["family"]]
        group["attempts"] += 1
        group["results"] += row.get("result_count", 0)
        group["fulltexts"] += row.get("fulltext_count", 0)
        group["eligible"] += row.get("eligible_count", 0)
        group["selected"] += row.get("selected_count", 0)
        group["failures"] += int(row.get("status") == "failed")
        group["blocked"] += int(row.get("status") == "blocked")
    for group in groups.values():
        group["fulltext_yield"] = round(group["fulltexts"] / group["results"], 3) if group["results"] else 0
        group["eligible_yield"] = round(group["eligible"] / group["fulltexts"], 3) if group["fulltexts"] else 0
        group["selection_yield"] = round(group["selected"] / group["eligible"], 3) if group["eligible"] else 0
    return {"batch": batch, "attempt_count": len(selected), "families_attempted": sorted(groups), "by_family": dict(sorted(groups.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description="记录与汇总热点选题检索渠道收益")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    sub = parser.add_subparsers(dest="action", required=True)
    record = sub.add_parser("record")
    record.add_argument("--batch", required=True)
    record.add_argument("--owner", choices=["主力", "主力2"], required=True)
    record.add_argument("--family", required=True)
    record.add_argument("--channel", required=True)
    record.add_argument("--query", required=True)
    record.add_argument("--status", choices=["success", "failed", "blocked"], required=True)
    for key in ("result-count", "fulltext-count", "eligible-count", "selected-count"):
        record.add_argument(f"--{key}", type=int, default=0)
    record.add_argument("--failure-type", default="")
    record.add_argument("--purpose", choices=["discovery", "smoke"], default="discovery")
    record.add_argument("--operation", choices=["search", "read", "author"], required=True)
    record.add_argument("--evidence-url", default="")
    report = sub.add_parser("report")
    report.add_argument("--batch")
    args = parser.parse_args()
    if args.action == "record":
        record_attempt(args.ledger, {
            "batch": args.batch, "owner": args.owner, "family": args.family, "channel": args.channel,
            "query": args.query, "status": args.status, "result_count": args.result_count,
            "fulltext_count": args.fulltext_count, "eligible_count": args.eligible_count,
            "selected_count": args.selected_count, "failure_type": args.failure_type,
            "purpose": args.purpose, "operation": args.operation, "evidence_url": args.evidence_url,
        })
        print(args.ledger)
    else:
        print(json.dumps(summarize(load_entries(args.ledger), args.batch), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
