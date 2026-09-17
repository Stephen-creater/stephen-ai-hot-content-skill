"""Locked, private ledger for measuring discovery-channel yield."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / ".local" / "discovery_attempts.jsonl"
PORTFOLIO = ROOT / "resources" / "source_portfolio.json"


def eligible_key(value: str) -> str:
    """One key format for scraper and manual records, so the same article is never counted twice."""
    value = value.strip()
    if value.startswith(("http://", "https://")):
        from curator import canonical_url

        return hashlib.sha1(canonical_url(value).encode("utf-8")).hexdigest()[:16]
    return value


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
    for key in ("round", "max_age_days"):
        if entry.get(key) is not None and (not isinstance(entry[key], int) or entry[key] < 0):
            raise ValueError(f"{key} 必须是非负整数")
    keys = entry.get("eligible_keys")
    if keys is not None and (not isinstance(keys, list) or len(keys) > entry["eligible_count"] or not all(isinstance(key, str) and key for key in keys)):
        raise ValueError("eligible_keys 必须是不超过合格数的非空字符串列表")
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


def stop_check(entries: list[dict], batch: str, portfolio: dict, min_weight: int = 8) -> dict:
    """Decide the completion contract's stop condition from recorded evidence only."""
    rows = [row for row in entries if row.get("batch") == batch and row.get("purpose", "discovery") == "discovery"]
    required = sorted(row["id"] for row in portfolio["families"] if row.get("role") == "candidate" and row.get("weight", 0) >= min_weight)
    # Failed attempts do not count; a blocked family (no authorization or no backend) is covered but reported.
    covered = {row["family"] for row in rows if row.get("status") in {"success", "blocked"}}
    blocked = sorted({row["family"] for row in rows if row.get("status") == "blocked"} - {row["family"] for row in rows if row.get("status") == "success"})
    missing = [family for family in required if family not in covered]
    unrounded = sum(1 for row in rows if not isinstance(row.get("round"), int) or row["round"] < 1)
    rounds = sorted({row["round"] for row in rows if isinstance(row.get("round"), int) and row["round"] >= 1})
    seen: set[str] = set()
    new_by_round: dict[int, int] = {}
    for number in rounds:
        fresh = 0
        for row in (row for row in rows if row.get("round") == number):
            keys = row.get("eligible_keys")
            if keys is None:
                fresh += row.get("eligible_count", 0)  # manual records without keys cannot be deduplicated
            else:
                fresh += len(set(keys) - seen)
                seen.update(keys)
        new_by_round[number] = fresh
    recent = rounds[-2:]
    recent_new = sum(new_by_round[number] for number in recent)
    expanded = any(row.get("round") in recent and row.get("status") == "success" and row.get("channel") != "scrape_aihot" for row in rows)
    reasons = []
    if missing:
        reasons.append(f"高权重来源族尚未成功检索：{', '.join(missing)}")
    if len(rounds) < 2:
        reasons.append(f"只记录了 {len(rounds)} 轮检索，至少需要两轮")
    elif recent_new:
        reasons.append(f"最近两轮（{recent[0]}、{recent[1]}）仍有 {recent_new} 条此前未出现的合格材料")
    elif not expanded:
        reasons.append("最近两轮只有常规抓取，没有换渠道或换查询的扩源记录")
    return {
        "batch": batch, "should_stop": not reasons, "required_families": required, "missing_families": missing,
        "blocked_families": blocked, "rounds": rounds, "new_eligible_by_round": new_by_round,
        "recent_rounds_new_eligible": recent_new, "recent_rounds_expanded": expanded,
        "unrounded_records": unrounded, "continue_reasons": reasons,
    }


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
    for key in ("result-count", "fulltext-count", "selected-count"):
        record.add_argument(f"--{key}", type=int, default=0)
    record.add_argument("--eligible-count", type=int, help="不填时取 --eligible-key 的数量")
    record.add_argument("--failure-type", default="")
    record.add_argument("--purpose", choices=["discovery", "smoke"], default="discovery")
    record.add_argument("--operation", choices=["search", "read", "author"], required=True)
    record.add_argument("--evidence-url", default="")
    record.add_argument("--round", type=int, help="本批第几轮检索，从 1 开始；不填的记录不参与停止判断")
    record.add_argument("--eligible-key", action="append", default=None, help="合格材料的原文链接（自动换算成与抓取记账相同的哈希），可重复；用于跨轮去重")
    record.add_argument("--max-age-days", type=int, default=0, help="本次检索使用的时间窗（天）")
    report = sub.add_parser("report")
    report.add_argument("--batch")
    check = sub.add_parser("stop-check", help="按完成契约判断是否应停止扩源并交付缺口报告")
    check.add_argument("--batch", required=True)
    check.add_argument("--min-weight", type=int, default=8)
    args = parser.parse_args()
    if args.action == "record":
        keys = sorted({eligible_key(value) for value in args.eligible_key}) if args.eligible_key else None
        eligible_count = args.eligible_count if args.eligible_count is not None else len(keys or [])
        fulltext_count = max(args.fulltext_count, eligible_count)
        result_count = max(args.result_count, fulltext_count)
        record_attempt(args.ledger, {
            "batch": args.batch, "owner": args.owner, "family": args.family, "channel": args.channel,
            "query": args.query, "status": args.status, "result_count": result_count,
            "fulltext_count": fulltext_count, "eligible_count": eligible_count,
            "selected_count": args.selected_count, "failure_type": args.failure_type,
            "purpose": args.purpose, "operation": args.operation, "evidence_url": args.evidence_url,
            "round": args.round, "max_age_days": args.max_age_days, "eligible_keys": keys,
        })
        print(args.ledger)
    elif args.action == "stop-check":
        portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        print(json.dumps(stop_check(load_entries(args.ledger), args.batch, portfolio, args.min_weight), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summarize(load_entries(args.ledger), args.batch), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
