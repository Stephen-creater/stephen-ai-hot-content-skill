from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def already_imported(target: Path, exported_at: str | None, payload: dict | None = None) -> bool:
    if not target.exists() or not exported_at:
        return False
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            if record.get("exported_at") == exported_at and (
                payload is None or all(record.get(key) == value for key, value in payload.items())
            ):
                return True
        except json.JSONDecodeError:
            continue
    return False


def final_reviewed_ids(target: Path) -> set[str]:
    decisions: dict[str, str] = {}
    if not target.exists():
        return set()
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            reviews = json.loads(line).get("reviews", {})
        except json.JSONDecodeError:
            continue
        for item_id, review in reviews.items():
            status = review.get("status")
            if status in {"selected", "rejected", "pending"}:
                decisions[str(item_id)] = status
    return {item_id for item_id, status in decisions.items() if status in {"selected", "rejected", "pending"}}


def final_reviewed_candidates(target: Path) -> list[dict]:
    decisions: dict[str, str] = {}
    candidates: dict[str, dict] = {}
    if not target.exists():
        return []
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        for candidate in payload.get("candidates", []):
            if isinstance(candidate, dict) and candidate.get("id"):
                candidates[str(candidate["id"])] = candidate
        for item_id, review in payload.get("reviews", {}).items():
            status = review.get("status")
            if status in {"selected", "rejected", "pending"}:
                decisions[str(item_id)] = status
    return [candidates[item_id] for item_id in decisions if item_id in candidates]


def validate_batch(payload: dict, expected_batch: str, expected_owner: str | None = None) -> None:
    if not re.fullmatch(r"[\w-]+", expected_batch) or payload.get("generated_at") != expected_batch:
        raise ValueError("反馈批次不匹配，保留原文件")
    folder = ROOT / "topics" / expected_batch
    candidates = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    signature = lambda rows: [(r.get("id"), r.get("title"), r.get("link")) for r in rows]
    if signature(payload.get("candidates", [])) != signature(candidates):
        raise ValueError("反馈候选顺序、标题或链接与本批报告不匹配，保留原文件")
    ids = [str(r["id"]) for r in candidates]
    if len(ids) != len(set(ids)) or not set(payload.get("reviews", {})).issubset(ids):
        raise ValueError("反馈包含不属于本批的候选 ID，保留原文件")
    manifest = json.loads((folder / "run.json").read_text(encoding="utf-8")) if (folder / "run.json").exists() else {}
    owners = [v for v in (payload.get("batch_owner"), manifest.get("batch_owner"), expected_owner) if v]
    if len(set(owners)) > 1:
        raise ValueError("反馈任务归属不匹配，保留原文件")


def import_feedback(feedback: Path, delete_source: bool = True, *, expected_batch: str | None = None, expected_owner: str | None = None) -> tuple[Path, bool]:
    original = feedback.read_bytes()
    payload = json.loads(original)
    if not isinstance(payload, dict) or not isinstance(payload.get("reviews", {}), dict):
        raise ValueError("反馈文件格式不正确")
    if not payload.get("exported_at"):
        raise ValueError("缺少导出时间，保留原文件")
    if expected_batch is not None:
        validate_batch(payload, expected_batch, expected_owner)

    target = ROOT / ".local" / "editorial_feedback.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        duplicate = already_imported(target, payload.get("exported_at"), payload)
        if not duplicate:
            record = {"imported_at": datetime.now().isoformat(), **payload}
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

        if not already_imported(target, payload.get("exported_at"), payload):
            raise RuntimeError("反馈未能在本地库中验证，保留原文件")
        if delete_source:
            if feedback.read_bytes() != original:
                raise RuntimeError("导入期间源文件发生变化，保留原文件")
            feedback.unlink()
    return target, duplicate


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 index.html 导出的人工审核结果")
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--expected-batch", required=True, help="当前任务交付的批次 ID；不从下载文件名推断")
    parser.add_argument("--owner", choices=["主力", "主力2"], required=True)
    cleanup = parser.add_mutually_exclusive_group()
    cleanup.add_argument("--delete-source", dest="delete_source", action="store_true", help="确认导入后删除临时 JSON（默认）")
    cleanup.add_argument("--keep-source", dest="delete_source", action="store_false", help="显式保留原始 JSON")
    parser.set_defaults(delete_source=True)
    args = parser.parse_args()

    payload = json.loads(args.feedback.read_text(encoding="utf-8"))
    target, duplicate = import_feedback(args.feedback, delete_source=args.delete_source, expected_batch=args.expected_batch, expected_owner=args.owner)

    reviews = payload.get("reviews", {})
    selected = sum(1 for value in reviews.values() if value.get("status") == "selected")
    rejected = sum(1 for value in reviews.values() if value.get("status") == "rejected")
    action = "已跳过重复反馈" if duplicate else "已导入"
    print(f"{action}：入选 {selected}，不入选 {rejected}，遗漏 {len(payload.get('missed', []))}")
    print(target)
    if args.delete_source:
        print(f"已删除临时文件：{args.feedback}")


if __name__ == "__main__":
    main()
