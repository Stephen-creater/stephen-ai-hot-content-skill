"""回放评测：用 Stephen 审核过的历史批次检查新规则有没有退步。

基准集来自 .local/editorial_feedback.jsonl，只在本机，不提交。

  build    冻结一版基准集（按批次切分出开发集和留出集）
  machine  用当前打分规则回放基准集：你选中的文章有没有被拦下或排到后面
  leak-check  检查规则文档有没有引用留出集的文章
  hints    每类关键词提示命中了多少入选、多少淘汰（关键词不参与排序和判断，只用来观察）
  export   导出不带结论的盲评材料，交给 Agent 按当前 SKILL 重新判断
  score    把 Agent 的判断和你的结论对比，记录到评测历史
  history  查看历次评测结果，发现退步
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from curator import parse_datetime, score_item  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK = ROOT / ".local" / "editorial_feedback.jsonl"
EVAL_DIR = ROOT / ".local" / "eval"
PROFILE = ROOT / "resources" / "editorial_profile.json"
MIN_JUDGEABLE_CHARS = 800
HOLDOUT_SHARE = 3  # of 10 batch buckets
# Notes that describe the whole batch, not this article. The label still counts; the reason does not.
BATCH_LEVEL_NOTES = ("整批", "全部拒绝", "无单条理由", "除最后一条外", "标题阶段即不符合需求")


def split_for(batch: str) -> str:
    bucket = int(hashlib.sha1(batch.encode("utf-8")).hexdigest(), 16) % 10
    return "holdout" if bucket < HOLDOUT_SHARE else "dev"


def label_strength(review: dict) -> str:
    note = str(review.get("note", "")).strip()
    if review.get("implicit"):
        return "weak"
    if review.get("reasons") or (note and not any(marker in note for marker in BATCH_LEVEL_NOTES)):
        return "strong"
    return "weak"


def collect(feedback: Path = FEEDBACK) -> list[dict]:
    """Last decision per candidate wins; pending is not a label."""
    candidates: dict[str, tuple[dict, str]] = {}
    decisions: dict[str, tuple[dict, str]] = {}
    for line in feedback.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        batch = str(record.get("generated_at", ""))
        for row in record.get("candidates", []):
            if isinstance(row, dict) and row.get("id"):
                candidates[str(row["id"])] = (row, batch)
        for item_id, review in record.get("reviews", {}).items():
            if isinstance(review, dict):
                decisions[str(item_id)] = (review, batch)
    items = []
    for item_id, (review, batch) in decisions.items():
        if review.get("status") not in {"selected", "rejected"} or item_id not in candidates:
            continue
        row, candidate_batch = candidates[item_id]
        content = row.get("content") or ""
        items.append({
            "id": item_id,
            "batch": candidate_batch or batch,
            "split": split_for(candidate_batch or batch),
            "label": review["status"],
            "label_strength": label_strength(review),
            "reasons": review.get("reasons", []),
            "note": str(review.get("note", "")).strip(),
            "judgeable": len(content) >= MIN_JUDGEABLE_CHARS,
            "candidate": row,
        })
    items.sort(key=lambda item: (item["batch"], item["id"]))
    return items


def latest_version() -> Path | None:
    versions = sorted(EVAL_DIR.glob("benchmark-v*.jsonl"))
    return versions[-1] if versions else None


def load_benchmark(path: Path | None = None) -> tuple[Path, list[dict]]:
    path = path or latest_version()
    if not path or not path.exists():
        raise SystemExit("还没有基准集，先运行：.venv/bin/python3 scripts/eval_replay.py build")
    return path, [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(feedback: Path = FEEDBACK) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    items = collect(feedback)
    previous = latest_version()
    number = int(previous.stem.split("-v")[-1]) + 1 if previous else 1
    path = EVAL_DIR / f"benchmark-v{number:03d}.jsonl"
    with path.open("w", encoding="utf-8") as out:
        for item in items:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary = Counter((item["split"], item["label"]) for item in items)
    manifest = {
        "version": path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feedback_sha256": hashlib.sha256(feedback.read_bytes()).hexdigest(),
        "items": len(items),
        "judgeable": sum(item["judgeable"] for item in items),
        "strong_labels": sum(item["label_strength"] == "strong" for item in items),
        "by_split_label": {f"{split}:{label}": count for (split, label), count in sorted(summary.items())},
    }
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def replay(item: dict, profile: dict) -> dict:
    row = dict(item["candidate"])
    for field in ("manual_editorial_review", "editorial_decision", "score", "recommended", "penalty"):
        row.pop(field, None)
    published = parse_datetime(row.get("published"))
    # Judge each article as of the day it was reviewed, so age rules do not drift with the calendar.
    now = published + timedelta(days=1) if published else datetime.now(timezone.utc)
    return score_item(row, profile, now=now)


def rank_auc(pairs: list[tuple[float, bool]]) -> float | None:
    positives = [score for score, positive in pairs if positive]
    negatives = [score for score, positive in pairs if not positive]
    if not positives or not negatives:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 3)


def machine(items: list[dict], profile: dict) -> dict:
    """Deterministic layer: selected articles must survive and should rank above rejected ones."""
    report: dict = {}
    for split in ("dev", "holdout", "all"):
        subset = [item for item in items if item["judgeable"] and (split == "all" or item["split"] == split)]
        blocked, pairs = [], []
        for item in subset:
            result = replay(item, profile)
            failures = [
                failure for failure in result["editorial_decision"]["eligibility"]["failures"]
                # Live GitHub stars and release dates are not stored with old feedback; they were checked at review time.
                if not (failure["evidence"].startswith("GitHub") and "github_stars" not in item["candidate"])
            ]
            selected = item["label"] == "selected"
            pairs.append((result["reading_order"], selected))
            if selected and failures:
                blocked.append({"id": item["id"], "title": result["title"], "why": [f["evidence"] for f in failures]})
        selected_total = sum(1 for _, positive in pairs if positive)
        report[split] = {
            "judgeable_items": len(subset),
            "selected": selected_total,
            "selected_kept_rate": round(1 - len(blocked) / selected_total, 3) if selected_total else None,
            "selected_blocked": blocked,
            "ranking_auc": rank_auc(pairs),
        }
    return report


def hints(items: list[dict], profile: dict) -> list[dict]:
    selected: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    batches: dict[str, set[str]] = {}
    for item in items:
        if not item["judgeable"]:
            continue
        result = replay(item, profile)
        for signal in result["editorial_decision"]["risk_signals"]:
            hint = signal["evidence"]
            (selected if item["label"] == "selected" else rejected)[hint] += 1
            batches.setdefault(hint, set()).add(item["batch"])
    rows = []
    for hint in sorted(set(selected) | set(rejected), key=lambda key: -(selected[key] + rejected[key])):
        rows.append({
            "hint": hint,
            "selected_hits": selected[hint],
            "rejected_hits": rejected[hint],
            "batches": len(batches[hint]),
        })
    return rows


def leak_check(items: list[dict], docs: list[Path]) -> list[dict]:
    """Holdout titles quoted in rules make the holdout useless for catching overfit."""
    import re as _re
    texts = {str(path.relative_to(ROOT)): path.read_text(encoding="utf-8") for path in docs}
    leaks = []
    for item in items:
        if item["split"] != "holdout":
            continue
        title = str(item["candidate"].get("source_title") or item["candidate"].get("title") or "")
        # Any 12-character run of the title counts as a quote.
        core = _re.sub(r"\s+", "", title)
        fragments = {core[i:i + 12] for i in range(0, max(1, len(core) - 11))} if len(core) >= 12 else set()
        for name, text in texts.items():
            flat = _re.sub(r"\s+", "", text)
            if any(fragment in flat for fragment in fragments):
                leaks.append({"doc": name, "title": title, "label": item["label"]})
    return leaks


def export_blind(items: list[dict], split: str, limit: int | None) -> list[dict]:
    rows = [item for item in items if item["judgeable"] and (split == "all" or item["split"] == split)]
    if limit:
        rows = rows[:limit]
    return [
        {
            "id": item["id"],
            "title": item["candidate"].get("source_title") or item["candidate"].get("title"),
            "link": item["candidate"].get("link"),
            "source_name": item["candidate"].get("source_name"),
            "published": item["candidate"].get("published"),
            "content": item["candidate"].get("content"),
        }
        for item in rows
    ]


def score_verdicts(items: list[dict], verdicts: list[dict]) -> dict:
    """Compare Agent verdicts (recommend / reject) with Stephen's labels."""
    by_id = {item["id"]: item for item in items}
    tp = fp = fn = tn = 0
    misses, false_alarms = [], []
    strong = Counter()
    for verdict in verdicts:
        item = by_id.get(str(verdict.get("id")))
        if not item:
            continue
        predicted = verdict.get("verdict") == "recommend"
        actual = item["label"] == "selected"
        title = item["candidate"].get("title")
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
            false_alarms.append({"id": item["id"], "title": title, "agent_reason": verdict.get("reason", ""), "your_reasons": item["reasons"] or item["note"]})
        elif actual:
            fn += 1
            misses.append({"id": item["id"], "title": title, "agent_reason": verdict.get("reason", ""), "your_reasons": item["reasons"] or item["note"]})
        else:
            tn += 1
        if item["label_strength"] == "strong":
            strong["agree" if predicted == actual else "disagree"] += 1
    total = tp + fp + fn + tn
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    specificity = tn / (tn + fp) if tn + fp else None
    return {
        "judged": total,
        "selected_recall": round(recall, 3) if recall is not None else None,
        "recommend_precision": round(precision, 3) if precision is not None else None,
        "balanced_accuracy": round((recall + specificity) / 2, 3) if recall is not None and specificity is not None else None,
        "accuracy": round((tp + tn) / total, 3) if total else None,
        "confusion": {"agree_selected": tp, "agent_only": fp, "missed_selected": fn, "agree_rejected": tn},
        "strong_label_agreement": dict(strong),
        "missed_selected": misses,
        "agent_only_recommendations": false_alarms,
    }


def git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def append_history(entry: dict) -> Path:
    path = EVAL_DIR / "history.jsonl"
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def regression_warnings(entry: dict, history: list[dict]) -> list[str]:
    previous = [
        row for row in history
        if row.get("kind") == entry["kind"] and row.get("benchmark") == entry["benchmark"]
        and row.get("split") == entry.get("split") and row.get("judge") == entry.get("judge")
    ]
    if not previous:
        return []
    last = previous[-1]["metrics"]
    warnings = []
    for key in ("selected_recall", "recommend_precision", "balanced_accuracy", "selected_kept_rate", "ranking_auc"):
        old, new = last.get(key), entry["metrics"].get(key)
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new < old - 0.02:
            warnings.append(f"{key} 从 {old} 降到 {new}")
    return warnings


def read_history() -> list[dict]:
    path = EVAL_DIR / "history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    machine_parser = sub.add_parser("machine")
    machine_parser.add_argument("--no-record", action="store_true")
    sub.add_parser("hints")
    sub.add_parser("leak-check")
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    export_parser.add_argument("--limit", type=int)
    export_parser.add_argument("--output", type=Path, required=True)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("verdicts", type=Path)
    score_parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    score_parser.add_argument("--judge", default="agent", help="谁做的判断，例如 claude-opus-5")
    sub.add_parser("history")
    args = parser.parse_args()
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))

    if args.command == "build":
        path = build()
        print(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
        return
    if args.command == "history":
        for row in read_history():
            print(json.dumps({k: row[k] for k in ("at", "commit", "kind", "benchmark", "split", "metrics")}, ensure_ascii=False))
        return

    path, items = load_benchmark()
    if args.command == "machine":
        report = machine(items, profile)
        metrics = {k: report["dev"][k] for k in ("selected_kept_rate", "ranking_auc")}
        entry = {"at": datetime.now(timezone.utc).isoformat(), "commit": git_head(), "kind": "machine", "benchmark": path.name, "split": "dev", "metrics": metrics}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        warnings = regression_warnings(entry, read_history())
        for warning in warnings:
            print(f"退步：{warning}")
        if not args.no_record:
            append_history(entry)
        sys.exit(1 if warnings else 0)
    if args.command == "leak-check":
        docs = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
        leaks = leak_check(items, docs)
        print(json.dumps(leaks, ensure_ascii=False, indent=2))
        sys.exit(1 if leaks else 0)
    if args.command == "hints":
        print(json.dumps(hints(items, profile), ensure_ascii=False, indent=2))
    elif args.command == "export":
        rows = export_blind(items, args.split, args.limit)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出 {len(rows)} 条盲评材料（不含你的结论）：{args.output}")
    elif args.command == "score":
        verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))
        subset = [item for item in items if args.split == "all" or item["split"] == args.split]
        result = score_verdicts(subset, verdicts)
        entry = {
            "at": datetime.now(timezone.utc).isoformat(), "commit": git_head(), "kind": "judge", "judge": args.judge,
            "benchmark": path.name, "split": args.split,
            "metrics": {k: result[k] for k in ("judged", "selected_recall", "recommend_precision", "balanced_accuracy", "accuracy")},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        for warning in regression_warnings(entry, read_history()):
            print(f"退步：{warning}")
        append_history(entry)


if __name__ == "__main__":
    main()
