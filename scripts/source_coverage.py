"""Measure desired, connected, configured and recently attempted source coverage."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discovery_ledger import DEFAULT_LEDGER, load_entries


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "resources" / "source_portfolio.json"
SOURCES = ROOT / "resources" / "content_curator_sources.json"


def doctor_state() -> dict:
    result = subprocess.run(["agent-reach", "doctor", "--json"], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def audit_coverage(portfolio: dict, doctor: dict, sources: dict, entries: list[dict], verified: set[str] | None = None, now: datetime | None = None) -> dict:
    verified = verified or set()
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(portfolio["rolling_window_days"]))
    attempted_families = {
        row.get("family") for row in entries
        if datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")) >= cutoff
    }
    successful_families = {
        row.get("family") for row in entries
        if row.get("status") == "success"
        and row.get("purpose") == "discovery"
        and row.get("result_count", 0) > 0
        and datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")) >= cutoff
    }
    automated_types = {row.get("type") for row in sources.get("sources", [])}
    rows = []
    access_total = configured_total = attempted_total = 0.0
    for family in portfolio["families"]:
        channels = family.get("doctor_channels", [])
        active = [name for name in channels if name in verified]
        required_operations = ("search", "read", "author")
        evidence = [row for row in entries
                    if row.get("family") == family["id"]
                    and row.get("status") == "success"
                    and row.get("result_count", 0) > 0
                    and row.get("evidence_url")
                    and cutoff <= datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")) <= now]
        operations = sorted({row.get("operation") for row in evidence} & set(required_operations))
        fraction = len(operations) / len(required_operations)
        configured = any(row.get("family") == family["id"] for row in sources.get("sources", []))
        attempted = family["id"] in attempted_families
        successful = family["id"] in successful_families
        access_points = family["weight"] * fraction
        configured_points = family["weight"] if configured else 0
        attempted_points = family["weight"] if successful else 0
        access_total += access_points
        configured_total += configured_points
        attempted_total += attempted_points
        rows.append({
            "id": family["id"], "label": family["label"], "weight": family["weight"], "role": family["role"],
            "access_fraction": round(fraction, 2), "active_channels": active, "configured_automation": configured,
            "verified_operations": operations,
            "backends": sorted({row.get("channel", "unknown") for row in evidence}),
            "attempted_in_window": attempted, "successful_in_window": successful,
            "user_action": family.get("user_action", ""),
        })
    return {
        "generated_at": now.isoformat(),
        "measurement": "Verified search/read/author operations in the declared portfolio; not percentage of the Internet",
        "weights_are_planning_assumptions": True,
        "access_coverage": round(access_total, 1),
        "configured_automation_coverage": round(configured_total, 1),
        "rolling_attempt_coverage": round(attempted_total, 1),
        "access_target": portfolio["target_weighted_access_coverage"],
        "attempt_target": portfolio["target_rolling_attempt_coverage"],
        "access_gap": round(max(0, portfolio["target_weighted_access_coverage"] - access_total), 1),
        "attempt_gap": round(max(0, portfolio["target_rolling_attempt_coverage"] - attempted_total), 1),
        "families": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="审计热点选题来源组合的真实覆盖率")
    parser.add_argument("--portfolio", type=Path, default=PORTFOLIO)
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--doctor-json", type=Path)
    parser.add_argument("--verified-channel", action="append", default=[])
    parser.add_argument("--write-snapshot", type=Path)
    args = parser.parse_args()
    doctor = json.loads(args.doctor_json.read_text(encoding="utf-8")) if args.doctor_json else doctor_state()
    report = audit_coverage(
        json.loads(args.portfolio.read_text(encoding="utf-8")), doctor,
        json.loads(args.sources.read_text(encoding="utf-8")), load_entries(args.ledger), set(args.verified_channel),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.write_snapshot:
        args.write_snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.write_snapshot.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
