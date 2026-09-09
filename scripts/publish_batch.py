"""Reserve a verified review batch under a shared lock before showing it to a user."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path

from curator import canonical_url, deduplicate
from discovery_history import delivered_candidates
from editorial_judgment import classify_penalties, final_decision_record, validate_manual_review, validate_source_anchors
from import_feedback import final_reviewed_candidates
from report import generate_report
from scrape_aihot import delivery_mix_ready, is_historical_content_duplicate

ROOT = Path(__file__).resolve().parents[1]


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
            if row.get("github_skill_focus"):
                localization = row.get("localization_review", {})
                setup_cost = row.get("setup_cost_review", {})
                security = row.get("security_review", {})
                if not row.get("human_article_verified"):
                    raise ValueError(f"GitHub Skill 缺少真人文章核验：{row.get('title')}")
                if not str(row.get("source_url", "")).startswith("https://github.com/"):
                    raise ValueError(f"GitHub Skill 缺少原始仓库链接：{row.get('title')}")
                if len(str(row.get("article_zh", "")).strip()) < 120:
                    raise ValueError(f"GitHub Skill 缺少可直接阅读的中文文章解读：{row.get('title')}")
                if localization.get("status") != "passed" or len(str(localization.get("evidence", "")).strip()) < 20:
                    raise ValueError(f"GitHub Skill 未通过中文用户适配：{row.get('title')}")
                if setup_cost.get("status") != "passed" or len(str(setup_cost.get("evidence", "")).strip()) < 20:
                    raise ValueError(f"GitHub Skill 缺少配置与付费审查：{row.get('title')}")
                if security.get("status") != "passed" or security.get("risk") not in {"low", "medium"} or len(str(security.get("evidence", "")).strip()) < 20:
                    raise ValueError(f"GitHub Skill 安全审查未通过：{row.get('title')}")
            if row.get("content_truncated") or row.get("content_status") == "partial":
                raise ValueError("正文被截断，不能发布为完整材料")
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
            source_validation = validate_source_anchors(row)
            if not source_validation.ok:
                raise ValueError(f"原文依据不完整：{row.get('title')}：{'；'.join(source_validation.errors)}")
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
