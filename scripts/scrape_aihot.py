from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import trafilatura
from bs4 import BeautifulSoup

from curator import clean_text, rank_candidates
from import_feedback import final_reviewed_ids
from report import generate_report


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
HEADERS = {"User-Agent": "StephenTopicCurator/1.0 (+https://github.com/Stephen-creater)"}


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def decode_html(raw: bytes, declared_encoding: str | None) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(declared_encoding or "utf-8", errors="replace")


def api_key() -> str:
    value = os.getenv("OPENROUTER_API_KEY", "").strip()
    if value:
        return value
    local_file = ROOT / ".config" / "openrouter_api_key.txt"
    return local_file.read_text(encoding="utf-8").strip() if local_file.exists() else ""


def fetch_rss(source: dict, settings: dict) -> list[dict]:
    response = requests.get(source["url"], headers=HEADERS, timeout=settings["request_timeout_seconds"])
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    items = []
    for entry in feed.entries[: settings["rss_items_per_source"]]:
        items.append(
            {
                "title": clean_text(entry.get("title")),
                "link": entry.get("link", ""),
                "summary": clean_text(entry.get("summary") or entry.get("description")),
                "published": entry.get("published") or entry.get("updated") or "",
                "source_name": source["name"],
                "source_category": source["category"],
                "source_priority": source["priority"],
                "source_type": "rss",
                "source_role": source.get("role", "candidate"),
                "language": source.get("language", "unknown"),
                "maturity": source.get("maturity", "unknown"),
                "content_form": "article",
                "content_status": "summary",
            }
        )
    return items


def fetch_web_index(source: dict, settings: dict) -> list[dict]:
    response = requests.get(source["url"], headers=HEADERS, timeout=settings["request_timeout_seconds"])
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    selectors = "article a[href], main a[href], div.bg-card a[href]"
    seen = set()
    items = []
    for anchor in soup.select(selectors):
        title = clean_text(anchor.get_text(" ", strip=True))
        link = urljoin(source["url"], anchor.get("href", ""))
        if len(title) < 12 or not link.startswith("http") or link in seen:
            continue
        if urlparse(link).netloc == urlparse(source["url"]).netloc and link.rstrip("/") == source["url"].rstrip("/"):
            continue
        seen.add(link)
        parent_text = clean_text(anchor.parent.get_text(" ", strip=True) if anchor.parent else "")
        items.append(
            {
                "title": title[:240],
                "link": link,
                "summary": parent_text[:600],
                "published": "",
                "source_name": source["name"],
                "source_category": source["category"],
                "source_priority": source["priority"],
                "source_type": "web",
                "source_role": source.get("role", "candidate"),
                "language": source.get("language", "unknown"),
                "maturity": source.get("maturity", "unknown"),
                "content_form": "article",
                "content_status": "summary",
            }
        )
        if len(items) >= settings["web_links_per_source"]:
            break
    return items


def fetch_aihot(source: dict, settings: dict) -> list[dict]:
    response = requests.get(source["url"], headers=HEADERS, timeout=settings["request_timeout_seconds"])
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    allowed = set(source.get("allowed_platforms", []))
    items = []
    for card in soup.find_all("div", class_=lambda value: value and "bg-card" in value and "text-card-foreground" in value):
        header = card.find("div", class_=lambda value: value and "justify-between" in value)
        platform = ""
        if header:
            name = header.find("span", class_=lambda value: value and "font-semibold" in value)
            platform = clean_text(name.get_text(" ", strip=True) if name else "")
        if allowed and platform not in allowed:
            continue
        for anchor in card.find_all("a", href=True):
            title_node = anchor.find("div", class_="font-[500]")
            title = clean_text(title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True))
            link = urljoin(source["url"], anchor["href"])
            if len(title) < 10 or not link.startswith("http"):
                continue
            description_node = anchor.find("div", class_=lambda value: value and "text-[#7a7b79]" in value)
            description = clean_text(description_node.get_text(" ", strip=True) if description_node else "")
            published = description if re.fullmatch(r"\d{4}-\d{2}-\d{2}", description) else ""
            items.append(
                {
                    "title": re.sub(r"^\d+\s*\.?\s*", "", title),
                    "link": link.replace(".com//", ".com/"),
                    "summary": "" if published else description,
                    "published": published,
                    "source_name": platform or source["name"],
                    "source_category": source["category"],
                    "source_priority": source["priority"],
                    "source_type": "web",
                    "source_role": source.get("role", "candidate"),
                    "language": source.get("language", "zh"),
                    "maturity": source.get("maturity", "secondary"),
                    "content_form": "article",
                    "content_status": "summary",
                }
            )
    return items


def fetch_source(source: dict, settings: dict) -> tuple[list[dict], str | None]:
    try:
        if source["type"] == "rss":
            rows = fetch_rss(source, settings)
        elif source["type"] == "aihot":
            rows = fetch_aihot(source, settings)
        else:
            rows = fetch_web_index(source, settings)
        return rows, None if rows else f"{source['name']}: 未发现条目"
    except Exception as exc:
        return [], f"{source['name']}: {exc}"


def hydrate(item: dict, settings: dict) -> dict:
    if not item.get("link"):
        return item
    if item.get("content_status") == "transcript" and item.get("content"):
        return item
    try:
        with requests.get(
            item["link"],
            headers=HEADERS,
            timeout=settings["request_timeout_seconds"],
            stream=True,
        ) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                remaining = settings["max_article_bytes"] - size
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
            raw = b"".join(chunks)
            text = decode_html(raw, response.encoding)
        extracted = trafilatura.extract(text, include_comments=False, include_tables=True) or ""
        if extracted:
            item["content"] = clean_text(extracted)[:5000]
            item["content_status"] = "shownotes" if item.get("content_form") in {"video", "podcast"} else "fulltext"
        metadata = trafilatura.bare_extraction(text, include_comments=False)
        meta = metadata.as_dict() if hasattr(metadata, "as_dict") else metadata or {}
        if not item.get("published") and isinstance(meta, dict):
            item["published"] = meta.get("date") or ""
        if not item.get("title") and isinstance(meta, dict):
            item["title"] = clean_text(meta.get("title"))
    except Exception as exc:
        item["fetch_error"] = str(exc)
    return item


def fetch_youtube_transcript(url: str) -> str:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("未找到 yt-dlp")
    with tempfile.TemporaryDirectory(prefix="stephen-youtube-") as directory:
        template = str(Path(directory) / "%(id)s")
        subprocess.check_output(
            [
                "yt-dlp",
                "--write-sub",
                "--write-auto-sub",
                "--sub-lang",
                "zh-Hans,zh,en",
                "--sub-format",
                "vtt",
                "--skip-download",
                "-o",
                template,
                url,
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        paths = sorted(Path(directory).glob("*.vtt"))
        if not paths:
            raise ValueError("yt-dlp 没有生成字幕文件")
        raw = paths[0].read_text(encoding="utf-8", errors="replace")
    lines = []
    previous = ""
    for line in raw.splitlines():
        text = clean_text(line)
        if not text or text == "WEBVTT" or "-->" in text or text.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if text != previous:
            lines.append(text)
            previous = text
    transcript = clean_text("\n".join(lines))
    if len(transcript) < 200:
        raise ValueError("YouTube 字幕为空或过短")
    return transcript


def inbox_item(row: dict, settings: dict) -> dict:
    platform = row.get("platform", "web")
    item = {
        "title": clean_text(row.get("title")),
        "link": row.get("url", ""),
        "summary": clean_text(row.get("notes")),
        "content": "",
        "published": row.get("published", ""),
        "source_name": row.get("creator") or platform,
        "source_category": "中文人工投喂",
        "source_priority": int(row.get("priority", 5)),
        "source_type": platform,
        "source_role": "candidate",
        "language": row.get("language", "zh"),
        "maturity": row.get("maturity", "secondary"),
        "content_form": "video" if platform in {"bilibili", "youtube"} else "podcast" if platform in {"xiaoyuzhou", "podcast"} else "article",
        "content_status": "summary",
    }
    transcript_path = row.get("transcript_path")
    if transcript_path:
        path = Path(transcript_path).expanduser()
        if path.exists():
            item["content"] = clean_text(path.read_text(encoding="utf-8", errors="replace"))[:20000]
            item["content_status"] = "transcript"
            return item
        item["fetch_error"] = f"逐字稿不存在: {path}"

    if platform == "youtube" and item["link"]:
        try:
            item["content"] = fetch_youtube_transcript(item["link"])[:20000]
            item["content_status"] = "transcript"
            return item
        except Exception as exc:
            item["fetch_error"] = f"YouTube 字幕读取失败: {exc}"

    if platform in {"bilibili", "youtube"} and item["link"] and shutil.which("yt-dlp"):
        try:
            output = subprocess.check_output(["yt-dlp", "--dump-single-json", "--skip-download", item["link"]], text=True, timeout=45)
            metadata = json.loads(output)
            item["title"] = item["title"] or clean_text(metadata.get("title"))
            item["summary"] = item["summary"] or clean_text(metadata.get("description"))
            upload_date = metadata.get("upload_date", "")
            if upload_date and not item["published"]:
                item["published"] = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        except Exception as exc:
            label = "B站" if platform == "bilibili" else "YouTube"
            item["fetch_error"] = f"{label} 元数据读取失败: {exc}"

    return hydrate(item, settings)


def load_inbox(path: Path | None, settings: dict) -> list[dict]:
    if not path or not path.exists():
        return []
    rows = load_json(path)
    if not isinstance(rows, list):
        raise ValueError("source inbox 必须是 JSON 数组")
    return [inbox_item(row, settings) for row in rows]


def ai_rerank(candidates: list[dict], profile: dict, model: str) -> list[dict]:
    key = api_key()
    if not key:
        return candidates
    compact = [
        {
            "id": item["id"],
            "title": item["title"],
            "summary": item.get("summary") or item.get("content", "")[:500],
            "score": item["score"],
            "pillars": item["pillars"],
        }
        for item in candidates
    ]
    prompt = {
        "task": "按 Stephen 的文章选题偏好重新排序候选选题",
        "target_readers": profile["target_readers"],
        "positive_signals": profile["positive_signals"],
        "weak_signals": profile["weak_signals"],
        "requirements": [
            "只返回 JSON 对象，顶层字段为 items",
            "items 是数组",
            "每项包含 id、title_zh、reason",
            "优先单一事件、有具体切入点、机制清楚、普通读者有收获的选题",
            "优先能够解释机制、架构、工作流或重大产品变化，且具有长期回看价值的题",
            "OpenAI、Anthropic、Google DeepMind 等核心团队人物的深度访谈，若有完整对话或逐字稿，应优先考虑",
            "降低纯炒作、模型身份八卦、宏大行业叙事、商业通稿和缺少大众切口的科研医疗题",
            "排除无名小模型、活动招募、采购对接、合作签约、纯融资、纯硬件新闻和没有解读的新闻复述",
            "宕机、故障、发布等事件新闻超过两周后不再当作热点；权威访谈和深度实测可保留更长时间",
            "排除只讨论企业维护成本、供应商锁定、准入基线或治理架构，却难以转化成普通读者价值的内容",
            "排除 SEO 站、AI 批量内容站、商业导流站和只列工具清单的泛化横评；保留有统一任务、真实数字与明确结论的对比实测",
            "技术深度不能替代用户价值；排除深入到 CUDA 核函数、logit、依赖包或缓存量化，但目标读者用不到也看不懂的题",
            "排除只有故事性的一次性 AI 奇闻；优先有数周持续实践、明确评分规则、真实结果和调整过程的复盘",
            "不得为了多样性保留弱选题",
        ],
        "candidates": compact,
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "你是 Stephen 的 AI 热点选题编辑。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(re.sub(r"^```json|```$", "", content.strip(), flags=re.M))
    rows = parsed.get("items", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        return candidates
    lookup = {item["id"]: item for item in candidates}
    ordered = []
    for row in rows:
        item = lookup.get(str(row.get("id"))) or lookup.get(row.get("id"))
        if not item:
            continue
        ordered.append({**item, "title_zh": row.get("title_zh", item["title"]), "ai_reason": row.get("reason", "")})
    ordered_ids = {item["id"] for item in ordered}
    ordered.extend(item for item in candidates if item["id"] not in ordered_ids)
    return ordered


def select_report_candidates(ranked: list[dict], limit: int, include_rejected: bool = False) -> list[dict]:
    eligible = ranked if include_rejected else [item for item in ranked if item.get("recommended")]
    return eligible[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="为 Stephen 筛选 AI 热点选题")
    parser.add_argument("--fixture", type=Path, help="使用本地 JSON 数据，不联网")
    parser.add_argument("--inbox", type=Path, default=ROOT / ".local" / "source_inbox.json", help="公众号、B站、播客和本地逐字稿入口")
    parser.add_argument("--include-verification", action="store_true", help="同时抓取英文官方核验来源")
    parser.add_argument("--include-rejected", action="store_true", help="调试时在报告中包含未通过硬门槛的内容")
    parser.add_argument("--no-ai", action="store_true", help="不调用模型复排")
    parser.add_argument("--model", default="google/gemini-3-flash-preview")
    parser.add_argument("--output-root", type=Path, default=ROOT / "topics")
    args = parser.parse_args()

    source_config = load_json(RESOURCES / "content_curator_sources.json")
    profile = load_json(RESOURCES / "editorial_profile.json")
    settings = source_config["fetch"]
    errors = []

    if args.fixture:
        items = load_json(args.fixture)
    else:
        items = load_inbox(args.inbox, settings)
        enabled_sources = [source for source in source_config["sources"] if args.include_verification or source.get("role") != "verification"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_source, source, settings) for source in enabled_sources]
            for future in concurrent.futures.as_completed(futures):
                rows, error = future.result()
                items.extend(rows)
                if error:
                    errors.append(error)
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings["hydrate_workers"]) as executor:
            items = list(executor.map(lambda item: hydrate(item, settings), items))

    ranked = rank_candidates(items, profile)
    feedback_store = ROOT / ".local" / "editorial_feedback.jsonl"
    reviewed_ids = set() if args.fixture else final_reviewed_ids(feedback_store)
    skipped_reviewed_count = sum(1 for item in ranked if str(item["id"]) in reviewed_ids)
    ranked = [item for item in ranked if str(item["id"]) not in reviewed_ids]
    report_count = profile["report_candidate_count"]
    minimum_delivery_count = int(profile.get("minimum_delivery_count", 3))
    rejected_by_gate_count = sum(1 for item in ranked if not item.get("recommended"))
    candidates = select_report_candidates(ranked, report_count, include_rejected=args.include_rejected)
    if not args.no_ai and api_key():
        try:
            candidates = ai_rerank(candidates, profile, args.model)
        except Exception as exc:
            errors.append(f"AI 复排失败，已使用确定性排序: {exc}")

    selection_count = profile["selection_count"]
    for index, item in enumerate(candidates):
        item["selected_by_default"] = index < selection_count and item["recommended"]

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    output_dir = args.output_root / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "run.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "input_count": len(items),
                "skipped_reviewed_count": skipped_reviewed_count,
                "rejected_by_gate_count": rejected_by_gate_count,
                "candidate_count": len(candidates),
                "minimum_delivery_count": minimum_delivery_count,
                "delivery_ready": len(candidates) >= minimum_delivery_count,
                "include_rejected": args.include_rejected,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    generate_report(candidates, output_dir / "index.html", timestamp)
    print(f"合格候选 {len(candidates)} 条，输入 {len(items)} 条，硬门槛拒绝 {rejected_by_gate_count} 条")
    if len(candidates) < minimum_delivery_count and not args.fixture:
        print(f"尚未达到交付门槛 {minimum_delivery_count} 条：继续扩展来源并检索，不得交付或用弱题补位")
    if errors:
        print("抓取告警：")
        for error in errors:
            print(f"- {error}")
    print(output_dir / "index.html")


if __name__ == "__main__":
    main()
