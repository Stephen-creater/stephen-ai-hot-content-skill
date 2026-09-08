"""Reserve a verified review batch under a shared lock before showing it to a user."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path

from curator import canonical_url, deduplicate
from editorial_judgment import classify_penalties, final_decision_record, validate_manual_review
from import_feedback import final_reviewed_candidates
from report import generate_report
from scrape_aihot import delivery_mix_ready, is_historical_content_duplicate

ROOT = Path(__file__).resolve().parents[1]


def delivered_candidates(topics: Path, exclude: Path | None = None) -> list[dict]:
    rows = []
    for path in sorted(topics.glob("*/run.json")):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        # Older scrapers used delivery_ready for quantity alone, including drafts.
        # Only explicit reservations or legacy manually finalized reports count.
        if run.get("delivery_registered") is True or (run.get("delivery_ready") is True and run.get("manual_editorial_review") is True):
            rows.extend(json.loads(path.with_name("candidates.json").read_text(encoding="utf-8")))
    return rows


def publish_batch(folder: Path, owner: str, root: Path = ROOT) -> Path:
    folder = folder.resolve()
    if owner not in {"主力", "主力2"} or folder.parent != (root / "topics").resolve():
        raise ValueError("仅允许发布当前项目 topics 下的批次，且必须声明归属")
    lock = root / ".local" / "delivery.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        run_path = folder / "run.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("batch_owner") not in {None, "", owner}:
            raise ValueError("不得改写另一个任务的批次")
        rows = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
        profile = json.loads((root / "resources/editorial_profile.json").read_text(encoding="utf-8"))
        if not delivery_mix_ready(rows, profile["minimum_delivery_count"], profile["minimum_non_github_candidates"], profile["maximum_github_candidates"]):
            raise ValueError("数量或来源构成未达交付门槛")
        if len(deduplicate(rows)) != len(rows):
            raise ValueError("批内重复")
        for row in rows:
            # Recheck persisted warnings: older drafts may label a failure as risk.
            penalty = row.get("penalty", [])
            warnings = [penalty] if isinstance(penalty, str) else list(penalty)
            warnings.extend(signal.get("evidence", "") for signal in row.get("editorial_decision", {}).get("risk_signals", []))
            if row.get("content_form") == "article" and row.get("content_status") == "fulltext" and len(row.get("content", "")) < 2500:
                warnings.append("文章正文偏短，不足以支撑高质量二创")
            failures, _ = classify_penalties(warnings)
            if failures:
                raise ValueError(f"发布复核未通过：{row.get('title')}：{failures[0]['evidence']}")
            eligibility = row.get("editorial_decision", {}).get("eligibility", {})
            if eligibility.get("status") == "failed":
                raise ValueError(f"存在未通过客观资格门槛的候选：{row.get('title')}")
            if not eligibility and not row.get("recommended"):
                raise ValueError("旧版候选缺少机器资格记录且未通过筛选")
            validation = validate_manual_review(row.get("manual_editorial_review", {}))
            if not validation.ok:
                raise ValueError(f"人工终审证据不完整：{row.get('title')}：{'；'.join(validation.errors)}")
            row["editorial_decision"] = {
                **row.get("editorial_decision", {}),
                "final": final_decision_record(row),
                "human_review_required": False,
            }
        history = final_reviewed_candidates(root / ".local/editorial_feedback.jsonl") + delivered_candidates(root / "topics", folder)
        old_ids = {r.get("id") for r in history}
        old_urls = {canonical_url(r.get("link", "")) for r in history}
        for row in rows:
            if row.get("id") in old_ids or canonical_url(row.get("link", "")) in old_urls or is_historical_content_duplicate(row, history):
                raise ValueError(f"另一任务或历史批次已推送/审核：{row.get('title')}")
        candidates_path = folder / "candidates.json"
        candidates_temp = candidates_path.with_suffix(".json.tmp")
        with candidates_temp.open("w", encoding="utf-8") as out:
            json.dump(rows, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        html_path = folder / "index.html"
        html_temp = folder / "index.html.tmp"
        generate_report(rows, html_temp, folder.name, batch_owner=owner)
        run.update(batch_owner=owner, delivery_ready=True, delivery_registered=True, cross_task_dedup_verified=True)
        temp = run_path.with_suffix(".json.tmp")
        with temp.open("w", encoding="utf-8") as out:
            json.dump(run, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(candidates_temp, candidates_path)
        os.replace(html_temp, html_path)
        os.replace(temp, run_path)
    return html_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--owner", choices=["主力", "主力2"], required=True)
    args = parser.parse_args()
    print(publish_batch(args.folder, args.owner))
