"""把线索变成候选：给线索补上正文，够格的登记进 inbox，下一轮抓取按普通候选判定。

一半以上的源被定成“只作线索”，而线索变候选那一步一直靠人，结果这些源天天空转：
即刻和 X 上本来就是写完整的中文长帖，播客和视频有字幕，全都停在 discovery.md 里没人动。

这里按链接所在平台决定怎么取正文：
- 网页、即刻、微信：直连 → 网页读取 → ego-browser 兜底，取到的正文存本机，随登记一起带走；
- X：按整串取作者自己的部分；
- YouTube、B 站、小宇宙：不在这里取，登记成对应平台，抓取脚本会去拿字幕或逐字稿。

正文不够长的不登记——不是所有线索都能变候选，硬凑只会把噪音塞进候选池。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser_fetch
from add_source import append_source
from curator import canonical_url, clean_text, minimum_article_chars
from scrape_aihot import hydrate

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".local" / "work"
INBOX = ROOT / ".local" / "source_inbox.json"
TEXT_DIR = ROOT / ".local" / "harvest"
DEFAULT_LIMIT = 40

PLATFORMS = {
    "m.okjike.com": "web", "okjike.com": "web",
    "x.com": "x", "twitter.com": "x",
    "www.youtube.com": "youtube", "youtu.be": "youtube",
    "www.bilibili.com": "bilibili", "b23.tv": "bilibili",
    "www.xiaoyuzhoufm.com": "xiaoyuzhou",
}
# These carry their own transcript path inside the scraper; harvesting text here would duplicate it.
MEDIA = {"youtube", "bilibili", "xiaoyuzhou"}


def platform_for(link: str) -> str:
    host = urlsplit(link).netloc.lower()
    return PLATFORMS.get(host, "web")


def latest_run(work: Path = WORK) -> Path | None:
    runs = sorted(path.parent for path in work.glob("*/*/discovery.json"))
    return runs[-1] if runs else None


def known_urls(inbox: Path = INBOX) -> set[str]:
    try:
        rows = json.loads(inbox.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {canonical_url(row.get("url", "")) for row in rows}


def pick(leads: list[dict], limit: int, skip: set[str]) -> list[dict]:
    """Chinese first, then the ones the platform says are hot, then the newest."""
    rows = [row for row in leads if row.get("link") and canonical_url(row["link"]) not in skip]
    seen: set[str] = set()
    unique = []
    for row in rows:
        key = canonical_url(row["link"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    unique.sort(key=lambda row: (
        -len(re.findall(r"[一-鿿]", str(row.get("title") or ""))),
        -int(row.get("engagement") or 0),
        str(row.get("published") or ""),
    ))
    return unique[:limit]


def harvest(leads: list[dict], settings: dict, profile: dict, limit: int = DEFAULT_LIMIT,
            inbox: Path = INBOX, text_dir: Path = TEXT_DIR, use_browser: bool = True) -> dict:
    minimum = minimum_article_chars(profile)
    chosen = pick(leads, limit, known_urls(inbox))
    text_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict] = {}
    registered = 0
    pending: list[dict] = []
    for lead in chosen:
        platform = platform_for(lead["link"])
        source = clean_text(lead.get("source_name")) or urlsplit(lead["link"]).netloc
        stats = report.setdefault(source, {"看到": 0, "取到正文": 0, "登记": 0})
        stats["看到"] += 1
        if platform in MEDIA:
            _register(lead, platform, "", inbox)
            stats["登记"] += 1
            registered += 1
            continue
        item = hydrate({**lead, "source_role": "candidate", "content_status": "summary"}, settings)
        text = clean_text(item.get("content"))
        if len(text) < minimum:
            pending.append({"lead": lead, "platform": platform, "source": source})
            continue
        stats["取到正文"] += 1
        _register(lead, platform, _store(lead, text, text_dir), inbox)
        stats["登记"] += 1
        registered += 1
    if use_browser and pending:
        fetched = browser_fetch.fetch([row["lead"]["link"] for row in pending])
        for row in pending:
            got = clean_text((fetched.get(row["lead"]["link"]) or {}).get("text", ""))
            stats = report[row["source"]]
            if len(got) < minimum:
                continue
            stats["取到正文"] += 1
            _register(row["lead"], row["platform"], _store(row["lead"], got, text_dir), inbox)
            stats["登记"] += 1
            registered += 1
    return {"considered": len(chosen), "registered": registered, "by_source": report}


def _store(lead: dict, text: str, text_dir: Path) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "-", canonical_url(lead["link"]))[-80:] + ".md"
    path = text_dir / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _register(lead: dict, platform: str, content_file: str, inbox: Path) -> None:
    append_source(inbox, {
        "url": lead["link"],
        "platform": platform,
        "creator": clean_text(lead.get("source_name")),
        "title": clean_text(lead.get("title"))[:160],
        "source_title": clean_text(lead.get("title"))[:160],
        "editorial_angle": "",
        "published": lead.get("published", ""),
        "notes": f"线索转候选；{lead.get('engagement', '')} 赞" if lead.get("engagement") else "线索转候选",
        "maturity": "primary" if platform == "x" else "secondary",
        "language": lead.get("language", "zh"),
        "official_release": False,
        "transcript_path": "",
        "content_file": content_file,
        "content_url": "",
        "content_json_key": "",
        "github_stars": None,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", type=Path, help="抓取输出目录；不填用最近一次")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run = args.run or latest_run()
    if not run or not (run / "discovery.json").exists():
        raise SystemExit("找不到抓取输出目录里的 discovery.json")
    leads = json.loads((run / "discovery.json").read_text(encoding="utf-8"))
    settings = json.loads((ROOT / "resources/content_curator_sources.json").read_text(encoding="utf-8"))["fetch"]
    profile = json.loads((ROOT / "resources/editorial_profile.json").read_text(encoding="utf-8"))
    result = harvest(leads, settings, profile, args.limit, use_browser=not args.no_browser)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n登记 {result['registered']} 条到 {INBOX}；重跑抓取时加 --inbox {INBOX}")


if __name__ == "__main__":
    main()
