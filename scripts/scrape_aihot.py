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
from import_feedback import final_reviewed_candidates, final_reviewed_ids
from report import generate_report
from zhuque_aigc import ZhuqueClient, apply_policy, estimate_text_cost_yuan, load_config


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


def embedded_original_date(text: str) -> str:
    match = re.search(
        r"(?:发布于|发布日期|发布时间|来源发布日期)\s*[：:]?\s*"
        r"(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?",
        text,
        flags=re.I,
    )
    if not match:
        return ""
    year, month, day = (int(value) for value in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


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
    soup = BeautifulSoup(decode_html(response.content, response.encoding), "html.parser")
    selectors = "article a[href], main a[href], div.bg-card a[href]"
    include_path_prefix = source.get("include_path_prefix", "")
    seen = set()
    items = []
    for anchor in soup.select(selectors):
        title = clean_text(anchor.get_text(" ", strip=True))
        link = urljoin(source["url"], anchor.get("href", ""))
        if include_path_prefix:
            link_path = urlparse(link).path
            if not link_path.startswith(include_path_prefix) or link_path.rstrip("/") == include_path_prefix.rstrip("/"):
                continue
        heading = anchor.select_one("h1, h2, h3, [class*='title']")
        if heading:
            title = clean_text(heading.get_text(" ", strip=True))
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
    if item.get("content") and (
        item.get("content_status") == "transcript" or item.get("content_origin") in {"explicit_content_url", "local_fulltext"}
    ):
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
            if urlparse(item["link"]).netloc.lower().endswith("jxxy.net"):
                item["published"] = embedded_original_date(extracted) or item.get("published", "")
        metadata = trafilatura.bare_extraction(text, include_comments=False)
        meta = metadata.as_dict() if hasattr(metadata, "as_dict") else metadata or {}
        if not item.get("published") and isinstance(meta, dict):
            item["published"] = meta.get("date") or ""
        if not item.get("title") and isinstance(meta, dict):
            item["title"] = clean_text(meta.get("title"))
    except Exception as exc:
        item["fetch_error"] = str(exc)
    return item


def clean_transcript(raw: str) -> str:
    fragments = []
    previous = ""
    for line in raw.splitlines():
        text = clean_text(line)
        if not text or text == "WEBVTT" or "-->" in text or text.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if text != previous:
            fragments.append(text)
            previous = text

    sentences = []
    current = ""
    boundary_starters = ("然后", "但是", "所以", "另外", "最后", "接着", "我们", "大家", "这里", "其实", "因为", "那么")
    for fragment in fragments:
        if current and current[-1].isascii() and current[-1].isalnum() and fragment[0].isascii() and fragment[0].isalnum():
            current += " "
        current += fragment
        explicit_end = bool(re.search(r"[。！？!?]》?〉?$", fragment))
        soft_end = len(current) >= 46 and fragment.startswith(boundary_starters)
        hard_end = len(current) >= 72
        if explicit_end or soft_end or hard_end:
            sentences.append(current if explicit_end else current + "。")
            current = ""
    if current:
        sentences.append(current if re.search(r"[。！？!?]$", current) else current + "。")

    paragraphs = ["".join(sentences[index : index + 3]) for index in range(0, len(sentences), 3)]
    transcript = "\n\n".join(paragraphs).strip()
    if len(transcript) < 200:
        raise ValueError("逐字稿为空或过短")
    return transcript


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
    return clean_transcript(raw)


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
        "github_stars": row.get("github_stars"),
    }
    content_file = row.get("content_file")
    if content_file:
        path = Path(content_file).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        try:
            content = path.read_text(encoding="utf-8")
            if len(content.strip()) < 400:
                raise ValueError("本地正文过短")
            status = "transcript" if item["content_form"] in {"video", "podcast"} else "fulltext"
            item.update(content=content, content_status=status, content_origin="local_fulltext")
            return item
        except (OSError, ValueError) as exc:
            item["fetch_error"] = f"本地正文读取失败: {exc}"
            return item
    transcript_path = row.get("transcript_path")
    if transcript_path:
        path = Path(transcript_path).expanduser()
        if path.exists():
            item["content"] = clean_transcript(path.read_text(encoding="utf-8", errors="replace"))[:20000]
            item["content_status"] = "transcript"
            return item
        item["fetch_error"] = f"逐字稿不存在: {path}"

    content_url = row.get("content_url", "").strip()
    if content_url:
        try:
            response = requests.get(content_url, headers=HEADERS, timeout=settings["request_timeout_seconds"])
            response.raise_for_status()
            text = decode_html(response.content[: settings["max_article_bytes"]], response.encoding)
            content_json_key = row.get("content_json_key", "").strip()
            if content_json_key:
                match = re.search(r"=\s*(\{.*\})\s*;?\s*$", text, flags=re.S)
                if not match:
                    raise ValueError("原始正文映射格式无法识别")
                payload = json.loads(match.group(1))
                text = str(payload.get(content_json_key, ""))
            item["content"] = clean_text(text)[:20000]
            if len(item["content"]) < 400:
                raise ValueError("原始正文为空或过短")
            item["content_status"] = "fulltext"
            item["content_origin"] = "explicit_content_url"
            return item
        except Exception as exc:
            item["fetch_error"] = f"原始正文读取失败: {exc}"

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


def select_report_candidates(
    ranked: list[dict],
    limit: int,
    include_rejected: bool = False,
    maximum_github: int | None = None,
) -> list[dict]:
    eligible = ranked if include_rejected else [item for item in ranked if item.get("recommended")]
    if include_rejected or maximum_github is None:
        return eligible[:limit]
    selected = []
    github_count = 0
    for item in eligible:
        is_github = urlparse(item.get("link", "")).netloc.lower() == "github.com"
        if is_github and github_count >= maximum_github:
            continue
        selected.append(item)
        github_count += int(is_github)
        if len(selected) >= limit:
            break
    return selected


def delivery_mix_ready(
    candidates: list[dict],
    minimum_count: int,
    minimum_non_github: int = 1,
    maximum_github: int = 1,
) -> bool:
    non_github_count = sum(1 for item in candidates if urlparse(item.get("link", "")).netloc.lower() != "github.com")
    github_count = len(candidates) - non_github_count
    return len(candidates) >= minimum_count and non_github_count >= minimum_non_github and github_count <= maximum_github


def normalized_content_shingles(value: str, size: int = 24) -> set[str]:
    normalized = re.sub(r"\W+", "", clean_text(value).lower())[:12000]
    if len(normalized) < 800:
        return set()
    return {normalized[index : index + size] for index in range(0, len(normalized) - size + 1, 12)}


def is_historical_content_duplicate(item: dict, reviewed_candidates: list[dict], threshold: float = 0.68) -> bool:
    current = normalized_content_shingles(item.get("content", ""))
    if not current:
        return False
    for reviewed in reviewed_candidates:
        previous = normalized_content_shingles(reviewed.get("content", ""))
        if not previous:
            continue
        overlap = len(current & previous) / min(len(current), len(previous))
        if overlap >= threshold:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="为 Stephen 筛选 AI 热点选题")
    parser.add_argument("--fixture", type=Path, help="使用本地 JSON 数据，不联网")
    parser.add_argument("--inbox", type=Path, default=ROOT / ".local" / "source_inbox.json", help="公众号、B站、播客和本地逐字稿入口")
    parser.add_argument("--include-verification", action="store_true", help="同时抓取英文官方核验来源")
    parser.add_argument("--include-rejected", action="store_true", help="调试时在报告中包含未通过硬门槛的内容")
    parser.add_argument("--no-ai", action="store_true", help="不调用模型复排")
    parser.add_argument("--no-aigc", action="store_true", help="不调用朱雀 AIGC 文本检测")
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
    reviewed_candidates = [] if args.fixture else final_reviewed_candidates(feedback_store)
    skipped_reviewed_count = sum(1 for item in ranked if str(item["id"]) in reviewed_ids)
    ranked = [item for item in ranked if str(item["id"]) not in reviewed_ids]
    skipped_content_duplicate_count = sum(1 for item in ranked if is_historical_content_duplicate(item, reviewed_candidates))
    ranked = [item for item in ranked if not is_historical_content_duplicate(item, reviewed_candidates)]
    report_count = profile["report_candidate_count"]
    minimum_delivery_count = int(profile.get("minimum_delivery_count", 5))
    minimum_non_github_candidates = int(profile.get("minimum_non_github_candidates", 1))
    maximum_github_candidates = int(profile.get("maximum_github_candidates", 1))

    aigc_status = "disabled" if args.no_aigc or args.fixture else "not_configured"
    aigc_checked_count = 0
    aigc_rejected_count = 0
    aigc_estimated_max_cost_yuan = 0.0
    if not args.no_aigc and not args.fixture:
        try:
            zhuque_config = load_config()
            if zhuque_config:
                client = ZhuqueClient(zhuque_config)
                eligible_items = [
                    item for item in ranked
                    if (
                        item.get("recommended")
                        and item.get("content_status") in {"fulltext", "transcript"}
                        and len(item.get("content", "")) >= 1000
                    )
                ]
                eligible_ids = {id(item) for item in eligible_items}
                aigc_estimated_max_cost_yuan = round(
                    sum(
                        estimate_text_cost_yuan(item["content"])
                        for item in eligible_items
                        if not client.has_cached_text(item["content"])
                    ),
                    2,
                )
                if aigc_estimated_max_cost_yuan > zhuque_config.max_cost_yuan_per_run:
                    aigc_status = "budget_exceeded"
                    errors.append(
                        f"朱雀本轮费用上限保护：最多约 {aigc_estimated_max_cost_yuan:.2f} 元，"
                        f"超过配置上限 {zhuque_config.max_cost_yuan_per_run:.2f} 元，未发起检测"
                    )
                else:
                    aigc_status = "completed"
                    updated_ranked = []
                    for item in ranked:
                        eligible = id(item) in eligible_ids
                        if not eligible:
                            updated_ranked.append(item)
                            continue
                        try:
                            detected = apply_policy(item, client.classify_text(item["content"]), zhuque_config)
                            aigc_checked_count += 1
                            aigc_rejected_count += int(detected.get("aigc_policy") == "rejected")
                            updated_ranked.append(detected)
                        except Exception as exc:
                            errors.append(f"朱雀检测失败 {item.get('title', '未知标题')}: {exc}")
                            updated_ranked.append({**item, "aigc_policy": "unknown"})
                    ranked = sorted(updated_ranked, key=lambda item: (item.get("recommended", False), item.get("score", 0)), reverse=True)
        except Exception as exc:
            aigc_status = "configuration_error"
            errors.append(f"朱雀配置无效，未执行 AIGC 检测: {exc}")

    rejected_by_gate_count = sum(1 for item in ranked if not item.get("recommended"))
    candidates = select_report_candidates(
        ranked,
        report_count,
        include_rejected=args.include_rejected,
        maximum_github=maximum_github_candidates,
    )
    if not args.no_ai and api_key():
        try:
            candidates = ai_rerank(candidates, profile, args.model)
        except Exception as exc:
            errors.append(f"AI 复排失败，已使用确定性排序: {exc}")

    selection_count = profile["selection_count"]
    for index, item in enumerate(candidates):
        item["selected_by_default"] = index < selection_count and item["recommended"]

    non_github_candidate_count = sum(1 for item in candidates if urlparse(item.get("link", "")).netloc.lower() != "github.com")
    github_candidate_count = len(candidates) - non_github_candidate_count
    ready_to_deliver = delivery_mix_ready(
        candidates,
        minimum_delivery_count,
        minimum_non_github_candidates,
        maximum_github_candidates,
    )

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
                "skipped_content_duplicate_count": skipped_content_duplicate_count,
                "rejected_by_gate_count": rejected_by_gate_count,
                "aigc_status": aigc_status,
                "aigc_checked_count": aigc_checked_count,
                "aigc_rejected_count": aigc_rejected_count,
                "aigc_estimated_max_cost_yuan": aigc_estimated_max_cost_yuan,
                "candidate_count": len(candidates),
                "minimum_delivery_count": minimum_delivery_count,
                "minimum_non_github_candidates": minimum_non_github_candidates,
                "maximum_github_candidates": maximum_github_candidates,
                "non_github_candidate_count": non_github_candidate_count,
                "github_candidate_count": github_candidate_count,
                "delivery_ready": ready_to_deliver,
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
    elif non_github_candidate_count < minimum_non_github_candidates and not args.fixture:
        print("候选全部来自 GitHub：继续补充高质量中文文章、博客或完整音视频材料，不得交付单一来源批次")
    if errors:
        print("抓取告警：")
        for error in errors:
            print(f"- {error}")
    print(output_dir / "index.html")


if __name__ == "__main__":
    main()
