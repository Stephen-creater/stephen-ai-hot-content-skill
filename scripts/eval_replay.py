"""回放评测：用 Stephen 审核过的历史批次检查新规则有没有退步。

基准集来自 .local/editorial_feedback.jsonl，只在本机，不提交。

  build    冻结一版基准集（按批次切分出开发集和留出集）
  machine  用当前打分规则回放基准集：你选中的文章有没有被拦下或排到后面
  leak-check  检查规则文档有没有引用留出集的文章
  export   导出不带结论的盲评材料，交给 Agent 按当前 SKILL 重新判断
  score    把 Agent 的判断和你的结论对比，记录到评测历史
  history  查看历次评测结果，发现退步
  forward  前瞻检验：新一批反馈到达、改规则之前，先用主干最新规则盲判这批，记下判决和 Stephen 的结果
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
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


ADOPTIONS = EVAL_DIR / "adoptions.json"
FORWARD = EVAL_DIR / "forward.jsonl"
PUBLISHED_TOPICS = ROOT / ".local" / "articles" / "published_topics.md"
TOPICS = ROOT / "topics"
WORK = ROOT / ".local" / "work"


def load_adoptions(path: Path = ADOPTIONS) -> dict[str, dict]:
    """Candidates Stephen turned into published articles. Writing it is the strongest label there is."""
    if not path.exists():
        return {}
    return {str(row["candidate_id"]): row for row in json.loads(path.read_text(encoding="utf-8"))}


def delivered_rows(topics: Path = TOPICS) -> dict[str, tuple[dict, str]]:
    rows: dict[str, tuple[dict, str]] = {}
    for path in sorted(topics.glob("*/candidates.json")):
        try:
            for row in json.loads(path.read_text(encoding="utf-8")):
                if isinstance(row, dict) and row.get("id"):
                    rows.setdefault(str(row["id"]), (row, path.parent.name))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def read_rows(ids: set[str], work: Path = WORK) -> dict[str, tuple[dict, str]]:
    """Material the Agent read but never delivered lives only in the scrape output."""
    rows: dict[str, tuple[dict, str]] = {}
    for path in sorted(work.glob("*/*/eligible.json")):
        if not ids - set(rows):
            break
        try:
            for row in json.loads(path.read_text(encoding="utf-8")):
                if isinstance(row, dict) and str(row.get("id")) in ids:
                    rows.setdefault(str(row["id"]), (row, path.parent.parent.name))
        except (OSError, json.JSONDecodeError):
            continue
    return rows


def collect(feedback: Path = FEEDBACK, adoptions: dict[str, dict] | None = None, topics: Path = TOPICS, work: Path = WORK) -> list[dict]:
    """Last decision per candidate wins; pending is not a label.

    A candidate Stephen later wrote up counts as selected with the strongest
    label, even when the review page said otherwise or was never filled in.
    """
    candidates: dict[str, tuple[dict, str]] = {}
    decisions: dict[str, tuple[dict, str]] = {}
    reviewed_at: dict[str, str] = {}
    positions: dict[str, int] = {}
    for line in feedback.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        batch = str(record.get("generated_at", ""))
        reviewed_at[batch] = str(record.get("exported_at") or record.get("imported_at") or "")[:10]
        for position, row in enumerate(record.get("candidates", []), 1):
            if isinstance(row, dict) and row.get("id"):
                candidates[str(row["id"])] = (row, batch)
                positions[str(row["id"])] = position  # 审核页上的顺序
        for item_id, review in record.get("reviews", {}).items():
            if isinstance(review, dict):
                decisions[str(item_id)] = (review, batch)
    adoptions = load_adoptions() if adoptions is None else adoptions
    delivered = delivered_rows(topics) if adoptions else {}
    missing = {item_id for item_id in adoptions if item_id not in candidates and item_id not in delivered}
    delivered.update(read_rows(missing, work) if missing else {})
    for item_id in adoptions:
        if item_id not in candidates and item_id in delivered:
            candidates[item_id] = delivered[item_id]
        if item_id in candidates:
            decisions[item_id] = ({"status": "selected", "note": "写成了文章：" + adoptions[item_id].get("article", ""), "adopted": True},
                                  decisions.get(item_id, ({}, candidates[item_id][1]))[1])
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
            "label_strength": "adopted" if review.get("adopted") else label_strength(review),
            "reasons": review.get("reasons", []),
            "note": str(review.get("note", "")).strip(),
            "judgeable": len(content) >= MIN_JUDGEABLE_CHARS,
            "reviewed_at": reviewed_at.get(candidate_batch or batch, ""),
            "position": positions.get(item_id),
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
        "adopted_labels": sum(item["label_strength"] == "adopted" for item in items),
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
        # In a Chinese title, a run that is mostly a product name ("ClaudeCode团队") is not a quote.
        if _re.search(r"[\u4e00-\u9fff]", core):
            fragments = {f for f in fragments if len(_re.findall(r"[\u4e00-\u9fff]", f)) >= 6}
        for name, text in texts.items():
            flat = _re.sub(r"\s+", "", text)
            if any(fragment in flat for fragment in fragments):
                leaks.append({"doc": name, "title": title, "label": item["label"]})
    return leaks


def published_articles(path: Path = PUBLISHED_TOPICS) -> list[tuple[str, str]]:
    """(发布日期, 标题) from the private published-topics table. 行首是 8.17 这种月.日；写“第九周”这类没具体日期的按 2026-09-21 算。"""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"日期", ""} or cells[0].startswith("-"):
            continue
        match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", cells[0])
        day = f"2026-{int(match.group(1)):02d}-{int(match.group(2)):02d}" if match else ("2026-09-21" if cells[0].startswith("第") else "")
        if day:
            rows.append((day, cells[1]))
    return rows


def written_before(review_date: str, exclude: set[str], articles: list[tuple[str, str]]) -> list[str]:
    """Articles Stephen had published by the day he reviewed this batch. 后来才写的不能让评审看到，
    不然评审会把当时的正样本判成“已写过”。"""
    return [title for day, title in articles if day <= review_date and not any(marker and marker in title for marker in exclude)]


def stratified_sample(rows: list[dict], limit: int | None, seed: str) -> list[dict]:
    """Same seed, same sample: 选中和淘汰按比例抽，不再取文件前 N 条。"""
    if not limit or limit >= len(rows):
        return rows
    rng = random.Random(seed)
    groups = {"selected": [row for row in rows if row["label"] == "selected"], "rejected": [row for row in rows if row["label"] != "selected"]}
    share = limit / len(rows)
    picked = []
    for label in ("selected", "rejected"):
        take = round(len(groups[label]) * share)
        picked.extend(rng.sample(groups[label], min(take, len(groups[label]))))
    picked.sort(key=lambda row: (row["batch"], row["id"]))
    return picked[:limit]


def export_blind(items: list[dict], split: str, limit: int | None, seed: str = "benchmark", adoptions: dict[str, dict] | None = None) -> list[dict]:
    rows = [item for item in items if item["judgeable"] and (split == "all" or item["split"] == split)]
    rows = stratified_sample(rows, limit, seed)
    adoptions = load_adoptions() if adoptions is None else adoptions
    articles = published_articles()
    exported = []
    for item in rows:
        exclude = {str(adoptions.get(item["id"], {}).get("article", ""))[-12:]} if item["id"] in adoptions else set()
        exported.append({
            "id": item["id"],
            "title": item["candidate"].get("source_title") or item["candidate"].get("title"),
            "link": item["candidate"].get("link"),
            "source_name": item["candidate"].get("source_name"),
            "published": item["candidate"].get("published"),
            "image_count": item["candidate"].get("image_count"),
            "video_count": item["candidate"].get("video_count"),
            "review_date": item.get("reviewed_at", ""),
            "written_before_review": written_before(item.get("reviewed_at") or "9999", exclude, articles) if articles else None,
            "content": item["candidate"].get("content"),
        })
    return exported


def gate_blocked(item: dict, profile: dict) -> bool:
    """Would the one-vote rules stop this before an Agent reads it? Live GitHub data is not stored, so skip it."""
    failures = replay(item, profile)["editorial_decision"]["eligibility"]["failures"]
    return any(not (failure["evidence"].startswith("GitHub") and "github_stars" not in item["candidate"]) for failure in failures)


def score_verdicts(items: list[dict], verdicts: list[dict], profile: dict | None = None, base_rate: float = 0.12) -> dict:
    """Compare Agent verdicts (recommend / reject) with Stephen's labels.

    With a profile, items the one-vote rules would block count as rejected, so the
    numbers describe the real pipeline rather than the Agent alone.
    """
    by_id = {item["id"]: item for item in items}
    tp = fp = fn = tn = 0
    misses, false_alarms = [], []
    strong = Counter()
    weak_negatives = Counter()
    per_item: dict[str, str] = {}
    for verdict in verdicts:
        item = by_id.get(str(verdict.get("id")))
        if not item:
            continue
        predicted = verdict.get("verdict") == "recommend" and not (profile and gate_blocked(item, profile))
        actual = item["label"] == "selected"
        title = item["candidate"].get("title")
        per_item[item["id"]] = "recommend" if predicted else "reject"
        # 没给理由的淘汰不一定是“不好”，可能只是那天没轮到：只单独记，不进主指标。
        if not actual and item["label_strength"] == "weak":
            weak_negatives["recommended" if predicted else "rejected"] += 1
            continue
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
    false_rate = fp / (fp + tn) if fp + tn else None
    # Samples are enriched with selected items; rescale to Stephen's real selection rate.
    estimated = (
        recall * base_rate / (recall * base_rate + false_rate * (1 - base_rate))
        if recall is not None and false_rate is not None and (recall or false_rate) else None
    )
    return {
        "judged": total,
        "selected_recall": round(recall, 3) if recall is not None else None,
        "recommend_precision": round(precision, 3) if precision is not None else None,
        "balanced_accuracy": round((recall + specificity) / 2, 3) if recall is not None and specificity is not None else None,
        "estimated_real_precision": round(estimated, 3) if estimated is not None else None,
        "base_rate": base_rate,
        "accuracy": round((tp + tn) / total, 3) if total else None,
        "confusion": {"agree_selected": tp, "agent_only": fp, "missed_selected": fn, "agree_rejected": tn},
        "strong_label_agreement": dict(strong),
        "weak_negatives": dict(weak_negatives),
        "per_item": per_item,
        "missed_selected": misses,
        "agent_only_recommendations": false_alarms,
    }


def verdict_flips(current: dict[str, str], previous: dict[str, str], items: list[dict]) -> dict:
    """Which articles changed verdict since the last run of the same judge. 一篇翻转是噪声，两篇选中的翻成淘汰要解释。"""
    labels = {item["id"]: item["label"] for item in items}
    flipped = {"selected_to_reject": [], "rejected_to_recommend": [], "other": []}
    for item_id, now in current.items():
        before = previous.get(item_id)
        if before is None or before == now:
            continue
        if labels.get(item_id) == "selected" and now == "reject":
            flipped["selected_to_reject"].append(item_id)
        elif labels.get(item_id) != "selected" and now == "recommend":
            flipped["rejected_to_recommend"].append(item_id)
        else:
            flipped["other"].append(item_id)
    return {"compared": sum(1 for item_id in current if item_id in previous), **{k: len(v) for k, v in flipped.items()}, "ids": flipped}


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
    if entry["kind"] == "machine":
        # Reading order is informational only; the machine layer is judged on keeping selected items.
        old, new = last.get("selected_kept_rate"), entry["metrics"].get("selected_kept_rate")
        if isinstance(old, (int, float)) and isinstance(new, (int, float)) and new < old - 0.02:
            warnings.append(f"selected_kept_rate 从 {old} 降到 {new}")
        return warnings
    # 判断层看逐篇翻转，不看百分比：24 个正样本里一篇就是 4%，比原来的 0.02 门槛还大。
    flips = entry.get("flips") or {}
    if flips.get("selected_to_reject", 0) >= 2:
        warnings.append(f"上次推荐、这次淘汰的选中文章有 {flips['selected_to_reject']} 篇：{flips['ids']['selected_to_reject']}")
    if flips.get("rejected_to_recommend", 0) >= 4:
        warnings.append(f"上次淘汰、这次推荐的淘汰稿有 {flips['rejected_to_recommend']} 篇，放宽过头了")
    return warnings


def forward_record(items: list[dict], batch: str, verdict_files: list[Path], profile: dict, model: str) -> dict:
    """新一批反馈到达、改规则之前，用主干最新规则盲判这批，逐批累计成前瞻成绩。两个评审时顺手算一致率。"""
    subset = [item for item in items if item["batch"] == batch]
    if not subset:
        raise SystemExit(f"基准里没有批次 {batch}，先导入反馈并 build")
    judges = []
    per_judge: list[dict[str, str]] = []
    for path in verdict_files:
        verdicts = json.loads(path.read_text(encoding="utf-8"))
        result = score_verdicts(subset, verdicts, profile)
        per_judge.append(result["per_item"])
        recommended = sum(1 for v in result["per_item"].values() if v == "recommend")
        hits = result["confusion"]["agree_selected"]
        judges.append({"file": path.name, "recommended": recommended, "hits": hits, "missed_selected": result["confusion"]["missed_selected"]})
    agreement = None
    if len(per_judge) >= 2:
        shared = [item_id for item_id in per_judge[0] if item_id in per_judge[1]]
        agreement = {"items": len(shared), "agree": sum(per_judge[0][i] == per_judge[1][i] for i in shared)}
    return {
        "at": datetime.now(timezone.utc).isoformat(), "commit": git_head(), "model": model, "batch": batch,
        "reviewed": len(subset), "stephen_selected": sum(item["label"] == "selected" for item in subset),
        "judges": judges, "agreement": agreement,
    }


def forward_report(rows: list[dict], window: int = 50) -> dict:
    """累计前瞻命中率和最近 window 条的双评审一致率。"""
    recommended = sum(j["recommended"] for row in rows for j in row["judges"][:1])
    hits = sum(j["hits"] for row in rows for j in row["judges"][:1])
    selected = sum(row["stephen_selected"] for row in rows)
    agree = items = 0
    for row in reversed(rows):
        if row.get("agreement"):
            take = min(row["agreement"]["items"], window - items)
            if take <= 0:
                break
            agree += round(row["agreement"]["agree"] * take / row["agreement"]["items"])
            items += take
    return {
        "batches": len(rows),
        "stephen_selected": selected,
        "judge_recommended": recommended,
        "judge_hits": hits,
        "forward_precision": round(hits / recommended, 3) if recommended else None,
        "forward_recall": round(hits / selected, 3) if selected else None,
        "agreement_last": {"items": items, "rate": round(agree / items, 3) if items else None},
        "per_batch": [{"batch": r["batch"], "commit": r["commit"], "selected": r["stephen_selected"],
                       "judges": [(j["recommended"], j["hits"]) for j in r["judges"]],
                       "agreement": r.get("agreement")} for r in rows],
    }


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
    sub.add_parser("leak-check")
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    export_parser.add_argument("--limit", type=int)
    export_parser.add_argument("--output", type=Path, required=True)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("verdicts", type=Path)
    score_parser.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
    score_parser.add_argument("--judge", required=True, help="这次评测的名字，同名的才互相比较，例如 dev-v11")
    score_parser.add_argument("--model", required=True, help="评审用的模型版本，例如 claude-fable-5-1；模型换了数字就不能比")
    score_parser.add_argument("--no-gate", action="store_true", help="只看 Agent 本身，不叠加一票否决")
    sub.add_parser("history")
    forward_parser = sub.add_parser("forward")
    forward_sub = forward_parser.add_subparsers(dest="forward_command", required=True)
    record_parser = forward_sub.add_parser("record", help="记下改规则前主干最新规则对这批的判决")
    record_parser.add_argument("--batch", required=True)
    record_parser.add_argument("--model", required=True)
    record_parser.add_argument("--verdicts", type=Path, nargs="+", required=True, help="一个或两个评审的 verdicts.json")
    forward_sub.add_parser("report", help="累计前瞻命中率和双评审一致率")
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
    if args.command == "export":
        rows = export_blind(items, args.split, args.limit, seed=path.name)
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出 {len(rows)} 条盲评材料（不含你的结论，已写清单按审核日截断）：{args.output}")
    elif args.command == "score":
        verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))
        subset = [item for item in items if args.split == "all" or item["split"] == args.split]
        result = score_verdicts(subset, verdicts, None if args.no_gate else profile)
        history = read_history()
        previous = [row for row in history if row.get("kind") == "judge" and row.get("benchmark") == path.name
                    and row.get("split") == args.split and row.get("judge") == args.judge and row.get("per_item")]
        flips = verdict_flips(result["per_item"], previous[-1]["per_item"], subset) if previous else None
        entry = {
            "at": datetime.now(timezone.utc).isoformat(), "commit": git_head(), "kind": "judge", "judge": args.judge, "model": args.model,
            "benchmark": path.name, "split": args.split,
            "metrics": {k: result[k] for k in ("judged", "selected_recall", "recommend_precision", "estimated_real_precision", "balanced_accuracy", "accuracy")},
            "weak_negatives": result["weak_negatives"], "flips": flips, "per_item": result["per_item"],
        }
        shown = {k: v for k, v in result.items() if k != "per_item"}
        shown["flips_since_last_run"] = flips
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        for warning in regression_warnings(entry, history):
            print(f"退步：{warning}")
        append_history(entry)
    elif args.command == "forward":
        if args.forward_command == "record":
            entry = forward_record(items, args.batch, args.verdicts, profile, args.model)
            with FORWARD.open("a", encoding="utf-8") as out:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(json.dumps(entry, ensure_ascii=False, indent=2))
        else:
            rows = [json.loads(line) for line in FORWARD.read_text(encoding="utf-8").splitlines() if line.strip()] if FORWARD.exists() else []
            print(json.dumps(forward_report(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
