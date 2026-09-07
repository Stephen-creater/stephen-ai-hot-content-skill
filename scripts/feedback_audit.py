"""Audit private editorial feedback without exporting its full text.

The report proves coverage and surfaces records that need interpretation. It
never turns notes into new rules automatically.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


FINAL_STATUSES = {"selected", "rejected", "pending"}
TOPIC_STATE_PHRASES = ("写过", "已经写", "之前写", "已经做过", "之前做过")
NEGATIVE_PHRASES = ("不适合", "不应该", "不能入选", "淘汰", "不考虑", "不推荐")


def load_records(path: Path) -> tuple[list[tuple[int, object]], list[dict]]:
    """Load either one exported feedback object or the persistent JSONL store."""
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        records = []
        invalid = []
        for line_number, raw in enumerate(text.splitlines(), 1):
            try:
                records.append((line_number, json.loads(raw)))
            except json.JSONDecodeError as exc:
                invalid.append({"line": line_number, "error": str(exc)})
        return records, invalid
    if isinstance(payload, list):
        return list(enumerate(payload, 1)), []
    return [(1, payload)], []


def audit_feedback(path: Path) -> dict:
    batches = []
    status_counts: Counter[str] = Counter()
    owners: Counter[str] = Counter()
    seen_decisions: dict[str, list[tuple[str, str, str]]] = {}
    unexplained = []
    interpretation_queue = []
    records, invalid_records = load_records(path)

    for line_number, record in records:
        if not isinstance(record, dict):
            invalid_records.append({"line": line_number, "error": "feedback record must be an object"})
            continue
        batch = str(record.get("generated_at", ""))
        owner = str(record.get("batch_owner", "unassigned") or "unassigned")
        reviews = record.get("reviews", {})
        if not batch or not isinstance(reviews, dict):
            invalid_records.append({"line": line_number, "error": "missing generated_at or reviews"})
            continue
        owners[owner] += 1
        batch_counts: Counter[str] = Counter()
        candidates = {
            str(row.get("id")): row.get("title", "")
            for row in record.get("candidates", [])
            if isinstance(row, dict) and row.get("id")
        }
        for item_id, review in reviews.items():
            review = review if isinstance(review, dict) else {}
            status = str(review.get("status", ""))
            note = str(review.get("note", "")).strip()
            title = str(candidates.get(str(item_id), ""))
            batch_counts[status] += 1
            status_counts[status] += 1
            seen_decisions.setdefault(str(item_id), []).append((status, batch, note))
            if status in FINAL_STATUSES and not note:
                unexplained.append({"batch": batch, "id": str(item_id), "status": status, "title": title})
            if status == "selected" and any(phrase in note for phrase in TOPIC_STATE_PHRASES):
                interpretation_queue.append({
                    "type": "topic_state",
                    "batch": batch,
                    "id": str(item_id),
                    "title": title,
                    "reason": "selected button with an already-covered note",
                })
            elif status == "selected" and any(phrase in note for phrase in NEGATIVE_PHRASES):
                interpretation_queue.append({
                    "type": "possible_status_note_conflict",
                    "batch": batch,
                    "id": str(item_id),
                    "title": title,
                    "reason": "selected button with negative note language",
                })
        batches.append({"batch": batch, "owner": owner, "reviews": sum(batch_counts.values()), "statuses": dict(batch_counts)})

    repeated = []
    for item_id, decisions in seen_decisions.items():
        if len(decisions) > 1:
            repeated.append({
                "id": item_id,
                "occurrences": len(decisions),
                "statuses": [status for status, _, _ in decisions],
                "batches": [batch for _, batch, _ in decisions],
            })

    return {
        "contract_version": 1,
        "source": str(path),
        "batch_count": len(batches),
        "review_count": sum(status_counts.values()),
        "status_counts": dict(status_counts),
        "owner_batch_counts": dict(owners),
        "unexplained_decisions": unexplained,
        "interpretation_queue": interpretation_queue,
        "repeated_candidate_decisions": repeated,
        "invalid_records": invalid_records,
        "batches": batches,
        "safe_summary_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="审计审核反馈覆盖度，不自动生成偏好规则")
    parser.add_argument("feedback", type=Path, nargs="?", default=Path(__file__).resolve().parents[1] / ".local" / "editorial_feedback.jsonl")
    args = parser.parse_args()
    print(json.dumps(audit_feedback(args.feedback), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
