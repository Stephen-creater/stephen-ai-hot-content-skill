from __future__ import annotations

import argparse
import fcntl
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def already_imported(target: Path, exported_at: str | None) -> bool:
    if not target.exists() or not exported_at:
        return False
    for line in target.read_text(encoding="utf-8").splitlines():
        try:
            if json.loads(line).get("exported_at") == exported_at:
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


def import_feedback(feedback: Path, delete_source: bool = False) -> tuple[Path, bool]:
    payload = json.loads(feedback.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("reviews", {}), dict):
        raise ValueError("反馈文件格式不正确")

    target = ROOT / ".local" / "editorial_feedback.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        duplicate = already_imported(target, payload.get("exported_at"))
        if not duplicate:
            record = {"imported_at": datetime.now().isoformat(), **payload}
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        if not already_imported(target, payload.get("exported_at")):
            raise RuntimeError("反馈未能在本地库中验证，保留原文件")
    if delete_source:
        feedback.unlink()
    return target, duplicate


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 index.html 导出的人工审核结果")
    parser.add_argument("feedback", type=Path)
    parser.add_argument("--delete-source", action="store_true", help="确认导入后删除下载的临时 JSON")
    args = parser.parse_args()

    payload = json.loads(args.feedback.read_text(encoding="utf-8"))
    target, duplicate = import_feedback(args.feedback, delete_source=args.delete_source)

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
