"""逐个体检信息源：每个源实际抓一遍，看它到底能不能出货。

名单里写着却从不出货的源，等于没写。这里对每个源抓几条、取正文、按一票否决打一遍分，
报出「取到几条、有正文几条、合格几条、卡在哪」，把空转的源摆在明面上。

    .venv/bin/python3 scripts/source_audit.py                 # 全部源，每个抓 3 条
    .venv/bin/python3 scripts/source_audit.py --sample 5      # 抓得多一点
    .venv/bin/python3 scripts/source_audit.py --only 公众号    # 只看名字或分类里带这几个字的源
    .venv/bin/python3 scripts/source_audit.py --problems      # 只列有问题的

结果同时写到 .local/audit/source-audit-<时间>.json。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from curator import clean_text, parse_datetime, score_item
from scrape_aihot import fetch_source, hydrate, rescue_with_browser
from source_config import load_sources

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".local" / "audit"
DEFAULT_SAMPLE = 3


def audit_source(source: dict, settings: dict, profile: dict, sample: int, now: datetime, use_browser: bool = True) -> dict:
    row = {"name": source.get("name", ""), "category": source.get("category", ""), "type": source.get("type", ""),
           "role": source.get("role", "candidate"), "items": 0, "with_text": 0, "eligible": 0,
           "error": "", "blocked": 0, "newest_days": None, "short_form": False, "reasons": {}}
    try:
        items, error = fetch_source(source, settings)
    except Exception as exc:  # 抓取脚本自己会吞掉大部分异常，这里兜住剩下的
        row["error"] = str(exc)[:160]
        return row
    row["error"] = (error or "")[:160]
    row["items"] = len(items)
    dates = [parse_datetime(item.get("published")) for item in items]
    fresh = [(now - date).days for date in dates if date]
    row["newest_days"] = min(fresh) if fresh else None
    sampled = [hydrate({**item}, settings) for item in items[:sample]]
    # 体检要和真实抓取一样：被站点挡住的，走一次浏览器兜底再判。
    if use_browser:
        rescue_with_browser(sampled, {**settings, "browser_fallback_limit": sample})
    row["short_form"] = bool(sampled) and all(
        "x.com" in str(item.get("link", "")) or "okjike.com" in str(item.get("link", "")) for item in sampled)
    for hydrated in sampled:
        text = clean_text(hydrated.get("content"))
        if hydrated.get("content_status") == "blocked":
            row["blocked"] += 1
        if len(text) >= 400:
            row["with_text"] += 1
        verdict = score_item(hydrated, profile, now=now)
        if verdict["editorial_decision"]["eligibility"]["status"] == "passed":
            row["eligible"] += 1
        else:
            for reason in verdict["penalty"].split("；"):
                reason = reason.strip()
                if reason:
                    row["reasons"][reason] = row["reasons"].get(reason, 0) + 1
    return row


def verdict_of(row: dict) -> str:
    """一句话说清这个源现在是什么状态。"""
    if row["error"] and not row["items"]:
        return "抓不到：" + row["error"][:60]
    if not row["items"]:
        return "抓到 0 条"
    if row["newest_days"] is not None and row["newest_days"] > 45:
        return f"更新慢：最新一篇是 {row['newest_days']} 天前"
    if row["blocked"]:
        return f"被站点拦（{row['blocked']} 条验证页），靠浏览器兜底"
    if row["role"] == "discovery":
        return "线索源，正文由 harvest_leads 补"
    if not row["eligible"] and row["reasons"].get("播客缺少逐字稿，无法低成本二创"):
        return "播客源：这档节目本轮没有逐字稿（BestBlogs 转录覆盖到的会自动带稿）"
    if row["short_form"] and not row["eligible"]:
        return "平台短内容：只有长帖够格，长帖由 harvest_leads 登记"
    if not row["with_text"]:
        return "有条目但取不到正文"
    if not row["eligible"]:
        top = max(row["reasons"], key=row["reasons"].get) if row["reasons"] else ""
        return f"有正文但样本全被否决（最常见：{top[:24]}）"
    return "正常出货"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="每个源抓几条做体检")
    parser.add_argument("--only", default="", help="只看名字或分类里含这个词的源")
    parser.add_argument("--problems", action="store_true", help="只列出有问题的源")
    parser.add_argument("--workers", type=int, default=3, help="并发太高会把本机代理打挂")
    parser.add_argument("--no-browser", action="store_true", help="体检时不跑浏览器兜底")
    args = parser.parse_args()

    config = load_sources()
    profile = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
    # 和正式抓取共用缓存：体检不该把本机代理再打一遍。
    settings = {**config["fetch"], "failure_cache_ttl_seconds": 0,
                "cache_dir": str(ROOT / ".local" / "cache" / "http")}
    sources = [s for s in config["sources"] if isinstance(s, dict) and s.get("url")]
    if args.only:
        sources = [s for s in sources if args.only in f"{s.get('name','')} {s.get('category','')} {s.get('group','')}"]
    now = datetime.now(timezone.utc)

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        for row in executor.map(lambda s: audit_source(s, settings, profile, args.sample, now, not args.no_browser), sources):
            rows.append(row)
    for row in rows:
        row["verdict"] = verdict_of(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"source-audit-{now.strftime('%Y-%m-%d-%H%M%S')}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    shown = [row for row in rows if not args.problems or row["verdict"] != "正常出货"]
    shown.sort(key=lambda row: (row["verdict"] == "正常出货", row["category"], row["name"]))
    for row in shown:
        print(f"{row['name'][:26]:28} {row['items']:4} 条  正文 {row['with_text']}/{args.sample}  合格 {row['eligible']}  {row['verdict']}")
    ok = sum(1 for row in rows if row["verdict"] == "正常出货")
    leads = sum(1 for row in rows if row["verdict"].startswith("线索源"))
    slow = sum(1 for row in rows if row["verdict"].startswith("更新慢"))
    short = sum(1 for row in rows if row["verdict"].startswith("平台短内容"))
    rest = len(rows) - ok - leads - slow - short
    print(f"\n共 {len(rows)} 个源：正常出货 {ok}，平台短内容 {short}，更新慢 {slow}，要修 {rest}。明细：{path}")


if __name__ == "__main__":
    main()
