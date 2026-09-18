from __future__ import annotations

import argparse
import base64
import concurrent.futures
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlparse

import feedparser
import requests
import trafilatura
from bs4 import BeautifulSoup

from curator import canonical_url, clean_text, rank_candidates
from source_config import load_sources
from discovery_history import delivered_candidates
from import_feedback import final_reviewed_candidates, final_reviewed_ids
from report import generate_report


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
HEADERS = {"User-Agent": "StephenTopicCurator/1.0 (+https://github.com/Stephen-creater)"}


def parse_feed(content: bytes):
    # Bodies are converted to plain text and escaped in the report, so feedparser's HTML sanitizing is pure cost.
    return feedparser.parse(content, sanitize_html=False, resolve_relative_uris=False)


class CachedResponse:
    """Minimal stand-in for requests.Response served from the shared on-disk cache."""

    status_code = 200

    def __init__(self, content: bytes, encoding: str | None):
        self.content, self.encoding = content, encoding

    @property
    def text(self) -> str:
        return decode_html(self.content, self.encoding)

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self) -> None:
        return None


def cache_path(settings: dict, key: str) -> Path | None:
    directory = settings.get("cache_dir")
    return Path(directory) / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json" if directory else None


def cache_read(settings: dict, key: str, ttl: int) -> dict | None:
    path = cache_path(settings, key)
    if not path or ttl <= 0 or not path.exists() or time.time() - path.stat().st_mtime > ttl:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_write(settings: dict, key: str, content: bytes, encoding: str | None, **extra) -> None:
    path = cache_path(settings, key)
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    # Atomic replace so two concurrent batches can share the cache without torn files.
    temp.write_text(json.dumps({"body": base64.b64encode(content).decode("ascii"), "encoding": encoding, **extra}), encoding="utf-8")
    os.replace(temp, path)


def http_get(url: str, settings: dict, params: dict | None = None, ttl: int | None = None):
    """GET through a shared TTL cache; sources update hourly at best, so repeat rounds should not refetch."""
    ttl = int(settings.get("cache_ttl_seconds", 3600) if ttl is None else ttl)
    key = url + ("?" + urlencode(sorted(params.items())) if params else "")
    cached = cache_read(settings, key, ttl)
    if cached is not None:
        return CachedResponse(base64.b64decode(cached["body"]), cached.get("encoding"))
    failure = cache_read(settings, "failed:" + key, int(settings.get("failure_cache_ttl_seconds", 0)))
    if failure is not None:
        raise requests.RequestException(f"最近已失败，暂不重试：{failure.get('error', '')}")
    kwargs = {"headers": HEADERS, "timeout": settings["request_timeout_seconds"]}
    if params:
        kwargs["params"] = params
    try:
        response = requests.get(url, **kwargs)
        response.raise_for_status()
    except requests.RequestException as exc:
        # Remember dead endpoints briefly so repeated rounds do not wait out the same timeouts.
        cache_write(settings, "failed:" + key, b"", None, error=str(exc)[:200])
        raise
    if cache_path(settings, key) and ttl > 0:
        cache_write(settings, key, response.content, response.encoding)
    return response


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


def html_to_text(value: str | None) -> str:
    """Keep paragraph breaks so feed and API bodies stay readable and anchorable."""
    soup = BeautifulSoup(value or "", "html.parser")
    for node in soup(["script", "style"]):
        node.decompose()
    lines = (clean_text(line) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def fetch_rss(source: dict, settings: dict) -> list[dict]:
    response = http_get(source["url"], settings, ttl=source.get("cache_ttl_seconds"))
    response.raise_for_status()
    feed = parse_feed(response.content)
    items = []
    for entry in feed.entries[: int(source.get("items_limit", settings["rss_items_per_source"]))]:
        body = html_to_text((entry.get("content") or [{}])[0].get("value")) if source.get("use_feed_content") else ""
        extra = {"content": body, "content_status": "fulltext", "content_origin": "feed_fulltext"} if len(body) >= 200 else {}
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
                "content_form": source.get("content_form", "article"),
                "audio_url": next((e.get("href") for e in entry.get("enclosures", [])
                                   if e.get("type", "").startswith("audio/")
                                   and e.get("href", "").startswith(("https://", "http://"))), None),
                "content_status": "summary",
                **extra,
            }
        )
    return items


BESTBLOGS_ID_RE = re.compile(r"/(article|podcast|video|status)/([0-9a-zA-Z]+)")


def bestblogs_transcript(podcast: dict) -> str:
    """Merge consecutive ASR segments by speaker into readable paragraphs."""
    paragraphs, speaker, buffer = [], None, []
    for segment in podcast.get("transcriptionSegments") or []:
        text = clean_text(segment.get("text"))
        if not text:
            continue
        current = segment.get("speakerName") or f"发言人{segment.get('speakerId', '')}"
        if current != speaker and buffer:
            paragraphs.append(f"{speaker}：{''.join(buffer)}")
            buffer = []
        speaker = current
        buffer.append(text)
    if buffer:
        paragraphs.append(f"{speaker}：{''.join(buffer)}")
    return "\n\n".join(paragraphs)


def fetch_bestblogs(source: dict, settings: dict) -> list[dict]:
    """Use BestBlogs' scored feed for discovery and its resource API to recover the original URL and body."""
    response = http_get(source["url"], settings, ttl=source.get("cache_ttl_seconds"))
    response.raise_for_status()
    feed = parse_feed(response.content)
    skip_types = set(source.get("skip_types", ["status", "video"]))
    targets, seen = [], set()
    for entry in feed.entries:
        match = BESTBLOGS_ID_RE.search(urlparse(entry.get("link", "")).path)
        if not match or match.group(1) in skip_types or match.group(2) in seen:
            continue
        seen.add(match.group(2))
        targets.append((match.group(1), match.group(2), entry))
        if len(targets) >= int(source.get("items_limit", 40)):
            break

    def resolve(target: tuple) -> dict | None:
        kind, resource_id, entry = target
        try:
            payload = http_get(source["api_url_template"].format(id=resource_id), settings, ttl=source.get("cache_ttl_seconds"))
            payload.raise_for_status()
            data = payload.json()
            data = data.get("data", data) if isinstance(data, dict) else {}
            meta = data.get("metaData") or {}
        except Exception:
            return None
        link = meta.get("url") or ""
        if not link.startswith(("https://", "http://")) or "bestblogs.dev" in urlparse(link).netloc:
            return None
        stamp = meta.get("publishTimeStamp")
        row = {
            "title": clean_text(meta.get("title") or entry.get("title")), "link": link,
            "summary": clean_text(entry.get("summary"))[:600],
            "published": datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime("%Y-%m-%d") if isinstance(stamp, (int, float)) else "",
            "source_name": clean_text(meta.get("sourceName")) or source["name"], "source_category": source["category"],
            "source_priority": source["priority"], "source_type": "web", "source_role": source.get("role", "candidate"),
            "language": source.get("language", "zh"), "maturity": source.get("maturity", "secondary"),
            "content_form": "podcast" if kind == "podcast" else "article", "content_status": "summary",
            "bestblogs_id": resource_id, "bestblogs_score": meta.get("score"), "discovery_source": source["name"],
        }
        if kind == "podcast":
            transcript = bestblogs_transcript(data.get("podCastContentData") or {})
            if transcript:
                # Machine transcript: speaker labels and proper nouns still need editing before delivery.
                row.update(content=transcript, content_status="transcript", content_origin="bestblogs_api")
        else:
            body = html_to_text((data.get("contentData") or {}).get("displayDocument"))
            if len(body) >= 200:
                row.update(content=body, content_status="fulltext", content_origin="bestblogs_api")
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(settings.get("hydrate_workers", 5))) as executor:
        return [row for row in executor.map(resolve, targets) if row]


def fetch_follow_builders(source: dict, settings: dict) -> list[dict]:
    """Builder tweets are radar only: they point to a topic, never to deliverable Chinese material."""
    response = http_get(source["url"], settings, ttl=source.get("cache_ttl_seconds"))
    response.raise_for_status()
    builders = response.json().get("x")
    if not isinstance(builders, list):
        raise ValueError("follow-builders 数据结构变化：缺少 x 列表")
    rows = []
    for builder in builders:
        if not isinstance(builder, dict):
            continue
        for tweet in builder.get("tweets") or []:
            link = tweet.get("url", "") if isinstance(tweet, dict) else ""
            if not str(link).startswith("https://"):
                continue
            rows.append({
                "title": clean_text(tweet.get("text"))[:240], "link": link, "summary": clean_text(builder.get("bio")),
                "published": str(tweet.get("createdAt", ""))[:10], "source_name": f"{builder.get('name', '')} (@{builder.get('handle', '')})",
                "source_category": source["category"], "source_priority": source["priority"], "source_type": "web",
                "source_role": "discovery", "language": "en", "maturity": "primary", "content_form": "article",
                "content_status": "summary", "engagement": tweet.get("likes", 0),
            })
    rows.sort(key=lambda row: row["engagement"], reverse=True)
    return rows[: int(source.get("items_limit", 60))]


def fetch_paged_web_index(source: dict, settings: dict) -> list[dict]:
    """Walk numbered list pages so a high-yield library is not limited to its homepage."""
    limit = int(source.get("items_limit", settings["web_links_per_source"]))
    page_settings = {**settings, "web_links_per_source": limit}
    rows, seen = [], set()
    for page in range(1, int(source.get("pages", 1)) + 1):
        url = source["url"] if page == 1 else source["page_url_template"].format(page=page)
        for row in fetch_web_index({**source, "url": url}, page_settings):
            if row["link"] not in seen:
                seen.add(row["link"])
                rows.append(row)
        if len(rows) >= limit:
            break
    return rows[:limit]


def fetch_wechat_index(source: dict, settings: dict) -> list[dict]:
    """Read a public WeChat article index, keeping interviews and long-horizon practice over news flashes."""
    end = datetime.now()
    start = end - timedelta(days=int(source.get("lookback_days", 5)))
    response = http_get(
        source["url"], settings, ttl=source.get("cache_ttl_seconds"),
        params={"start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "limit": int(source.get("index_limit", 2000))},
    )
    articles = response.json().get("articles")
    if not isinstance(articles, list):
        raise ValueError("公众号公开索引数据结构变化：缺少 articles 列表")
    include = re.compile(source["title_include_pattern"])
    exclude = re.compile(source["title_exclude_pattern"]) if source.get("title_exclude_pattern") else None
    preferred = set(source.get("preferred_accounts", []))
    rows, seen = [], set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        raw_title = str(article.get("title") or "")
        title, account, link = clean_text(raw_title), clean_text(article.get("account_name")), article.get("url", "")
        # Image-text posts put their whole body in the title field; they are not articles.
        if not title or "\n" in raw_title or len(title) > 80 or not str(link).startswith(("https://", "http://")):
            continue
        if exclude and exclude.search(title):
            continue
        # Preferred accounts rank first but still need an interview or practice title.
        if not include.search(title):
            continue
        key = str(article.get("article_key") or "")
        if not key or link in seen:
            continue
        seen.add(link)
        day = key[:8]
        rows.append({
            "title": title, "link": link.replace("http://", "https://", 1), "summary": clean_text(article.get("lead")),
            "published": f"{day[:4]}-{day[4:6]}-{day[6:]}" if day.isdigit() else "",
            "source_name": account or source["name"], "source_category": source["category"],
            "source_priority": source["priority"] + (1 if account in preferred else 0),
            "source_type": "web", "source_role": source.get("role", "candidate"),
            "language": source.get("language", "zh"), "maturity": source.get("maturity", "secondary"),
            "content_form": "article", "content_status": "summary", "index_article_key": key,
        })
    rows.sort(key=lambda row: (row["source_name"] in preferred, row["published"]), reverse=True)
    rows = rows[: int(source.get("items_limit", 60))]

    def attach_body(row: dict) -> dict:
        try:
            body = http_get(source["content_url_template"].format(key=quote(row["index_article_key"], safe="")),
                            settings, ttl=int(settings.get("page_cache_ttl_seconds", 0)))
            payload = body.json()
            article = payload.get("article", payload) if isinstance(payload, dict) else {}
            content = str(article.get("content") or "").strip()
            if content:
                # Cached body is a reading aid; the original page must still be checked before delivery.
                row.update(content=content, content_status="fulltext", content_origin="public_index_cache")
        except Exception as exc:
            row["fetch_error"] = str(exc)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=int(settings.get("hydrate_workers", 5))) as executor:
        return list(executor.map(attach_body, rows))


def fetch_web_index(source: dict, settings: dict) -> list[dict]:
    response = http_get(source["url"], settings, ttl=source.get("cache_ttl_seconds"))
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
    response = http_get(source["url"], settings, ttl=source.get("cache_ttl_seconds"))
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


def fetch_learnprompt_radar(source: dict, settings: dict) -> list[dict]:
    response = http_get(source["data_url"], settings, ttl=source.get("cache_ttl_seconds"))
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("items_all") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("AI News Radar 数据结构变化：缺少 items_all 列表")
    rows, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        link = entry.get("url", "")
        title = clean_text(entry.get("title_original") or entry.get("title"))
        if not isinstance(link, str) or urlparse(link).scheme not in {"http", "https"} or not urlparse(link).netloc or not title or link in seen:
            continue
        seen.add(link)
        rows.append({
            "title": title, "link": link,
            "summary": clean_text(entry.get("summary")),
            "published": entry.get("published_at") or "",
            "discovered_at": entry.get("first_seen_at") or "",
            "source_name": clean_text(entry.get("source") or entry.get("site_name") or source["name"]),
            "source_category": source["category"], "source_priority": source["priority"],
            "source_type": "web", "source_role": "discovery",
            "language": "unknown", "maturity": "unknown",
            "content_form": "article", "content_status": "summary",
            "discovery_source": source["url"], "discovery_generated_at": payload.get("generated_at", ""),
        })
        if len(rows) >= int(source.get("items_limit", 250)):
            break
    return rows


def fetch_source(source: dict, settings: dict) -> tuple[list[dict], str | None]:
    try:
        if source["type"] == "rss":
            rows = fetch_rss(source, settings)
        elif source["type"] == "aihot":
            rows = fetch_aihot(source, settings)
        elif source["type"] == "learnprompt_radar":
            rows = fetch_learnprompt_radar(source, settings)
        elif source["type"] == "wechat_index":
            rows = fetch_wechat_index(source, settings)
        elif source["type"] == "paged_web":
            rows = fetch_paged_web_index(source, settings)
        elif source["type"] == "bestblogs":
            rows = fetch_bestblogs(source, settings)
        elif source["type"] == "follow_builders":
            rows = fetch_follow_builders(source, settings)
        else:
            rows = fetch_web_index(source, settings)
        for row in rows:
            row.setdefault("collected_by", source["name"])
        # wechat_index applies its own exclusion before fetching bodies.
        if source.get("title_exclude_pattern") and source["type"] != "wechat_index":
            exclude = re.compile(source["title_exclude_pattern"])
            rows = [row for row in rows if not exclude.search(row.get("title", ""))]
        if source.get("title_include_pattern") and source["type"] != "wechat_index":
            include = re.compile(source["title_include_pattern"], re.I)
            rows = [row for row in rows if include.search(row.get("title", ""))]
        return rows, None if rows else f"{source['name']}: 未发现条目"
    except Exception as exc:
        return [], f"{source['name']}: {exc}"


def hydrate(item: dict, settings: dict) -> dict:
    if not item.get("link") or item.get("source_role") == "discovery":
        return item
    if item.get("content") and (
        item.get("content_status") == "transcript" or item.get("content_origin") in {"explicit_content_url", "local_fulltext", "public_index_cache", "bestblogs_api", "feed_fulltext"}
    ):
        return item
    try:
        # Article pages rarely change after publication, so they are cached longer than feeds.
        page_ttl = int(settings.get("page_cache_ttl_seconds", 0))
        cached = cache_read(settings, item["link"], page_ttl)
        failure = None if cached is not None else cache_read(settings, "failed:" + item["link"], int(settings.get("failure_cache_ttl_seconds", 0)))
        if failure is not None:
            raise requests.RequestException(f"最近已失败，暂不重试：{failure.get('error', '')}")
        if cached is not None:
            raw, truncated = base64.b64decode(cached["body"]), bool(cached.get("truncated"))
            text = decode_html(raw, cached.get("encoding"))
        else:
            with requests.get(
                item["link"],
                headers=HEADERS,
                timeout=settings["request_timeout_seconds"],
                stream=True,
            ) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                truncated = False
                for chunk in response.iter_content(65536):
                    if not chunk:
                        continue
                    remaining = settings["max_article_bytes"] - size
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        truncated = True
                    chunks.append(chunk[:remaining])
                    size += min(len(chunk), remaining)
                raw = b"".join(chunks)
                text = decode_html(raw, response.encoding)
            if page_ttl > 0:
                cache_write(settings, item["link"], raw, response.encoding, truncated=truncated)
    except requests.RequestException as exc:
        if not str(exc).startswith("最近已失败"):
            cache_write(settings, "failed:" + item["link"], b"", None, error=str(exc)[:200])
        item["fetch_error"] = str(exc)
        return item
    except Exception as exc:
        item["fetch_error"] = str(exc)
        return item
    try:
        extracted = trafilatura.extract(text, include_comments=False, include_tables=True) or ""
        if extracted:
            item["content"] = extracted.strip()
            item["content_truncated"] = truncated
            item["content_status"] = "partial" if truncated else ("shownotes" if item.get("content_form") in {"video", "podcast"} else "fulltext")
            if urlparse(item["link"]).netloc.lower().endswith("jxxy.net"):
                structured = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', text)
                # List pages show refresh dates; prefer the page's own publication date.
                item["published"] = embedded_original_date(extracted) or (structured.group(1) if structured else "") or item.get("published", "")
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
        # Alphabetical order selects .en before .zh even when Chinese exists.
        paths = sorted(Path(directory).glob("*.vtt"), key=lambda p: (
            0 if ".zh-Hans." in p.name else 1 if ".zh." in p.name else 2, p.name))
        if not paths:
            raise ValueError("yt-dlp 没有生成字幕文件")
        raw = paths[0].read_text(encoding="utf-8", errors="replace")
    return clean_transcript(raw)


def inbox_item(row: dict, settings: dict) -> dict:
    platform = row.get("platform", "web")
    item = {
        "title": clean_text(row.get("title")),
        "source_title": clean_text(row.get("source_title")),
        "editorial_angle": clean_text(row.get("editorial_angle")),
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
            item["content"] = clean_transcript(path.read_text(encoding="utf-8", errors="replace"))
            item["content_status"] = "transcript"
            return item
        item["fetch_error"] = f"逐字稿不存在: {path}"

    content_url = row.get("content_url", "").strip()
    if content_url:
        try:
            response = requests.get(content_url, headers=HEADERS, timeout=settings["request_timeout_seconds"])
            response.raise_for_status()
            if len(response.content) > settings["max_article_bytes"]:
                item["content_truncated"] = True
                item["content_status"] = "partial"
                item["fetch_error"] = "指定正文超过读取上限，不能标为完整材料"
                return item
            text = decode_html(response.content, response.encoding)
            content_json_key = row.get("content_json_key", "").strip()
            if content_json_key:
                match = re.search(r"=\s*(\{.*\})\s*;?\s*$", text, flags=re.S)
                if not match:
                    raise ValueError("原始正文映射格式无法识别")
                payload = json.loads(match.group(1))
                text = str(payload.get(content_json_key, ""))
            if re.search(r"<(?:html|body|!doctype)\b", text, re.I):
                text = trafilatura.extract(text, include_comments=False, include_tables=True) or ""
            item["content"] = text.strip()
            if len(item["content"]) < 400:
                raise ValueError("原始正文为空或过短")
            item["content_status"] = "fulltext"
            item["content_origin"] = "explicit_content_url"
            return item
        except Exception as exc:
            item["fetch_error"] = f"原始正文读取失败: {exc}"

    if platform == "youtube" and item["link"]:
        try:
            item["content"] = fetch_youtube_transcript(item["link"])
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


def load_inbox(path: Path | None, settings: dict, skip_urls: set[str] | None = None) -> list[dict]:
    if not path or not path.exists():
        return []
    rows = load_json(path)
    if not isinstance(rows, list):
        raise ValueError("source inbox 必须是 JSON 数组")
    skipped = skip_urls or set()
    return [inbox_item(row, settings) for row in rows if canonical_url(row.get("url", "")) not in skipped]


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
        "task": "只按正文证据辅助排序 Stephen 的候选材料；不得用关键词、名气或自动分数代替编辑判断",
        "target_readers": profile["target_readers"],
        "decision_model": profile["decision_model"],
        "requirements": [
            "只返回 JSON 对象，顶层字段为 items",
            "items 是数组",
            "每项包含 id、title_zh、reason",
            "依次评估选题吸引力、读者改变、材料增量、二创独立性和长期价值",
            "reason 必须指出正文中的决定性事实和最强反对理由，不能只写深度、权威、热门或有启发",
            "访谈、第一人称、技术词、新闻来源、清单结构和图片数量都只是风险信号，不是类别禁令",
            "去掉作者身份、私人截图、企业数据和品牌素材后论证仍成立，才算可独立二创",
            "高质量文章如果题目无吸引力、读者无具体改变或需要大量专业背景，仍应降级",
            "长逐字稿、数字和案例数量不等于信息密度；必须存在新的事实、因果链或有条件取舍",
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
    min_article_chars: int = 0,
) -> list[dict]:
    eligible = ranked if include_rejected else [
        item for item in ranked
        if (item.get("editorial_decision", {}).get("machine_disposition") in {"shortlist", "review"}
            or ("editorial_decision" not in item and item.get("recommended")))
        # Publishing rejects short articles anyway; do not spend reading time on them.
        and not (min_article_chars and item.get("content_status") == "fulltext" and len(item.get("content", "")) < min_article_chars)
    ]
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


@functools.lru_cache(maxsize=8192)
def normalized_content_shingles(value: str, size: int = 24) -> frozenset[str]:
    normalized = re.sub(r"\W+", "", clean_text(value).lower())[:12000]
    if len(normalized) < 800:
        return frozenset()
    # Anchor shingles on content rather than fixed offsets, so a repost with an extra preface still aligns.
    # Memoized: each history item is compared against every new item, so recomputing dominated run time.
    return frozenset(
        normalized[index : index + size]
        for index in range(len(normalized) - size + 1)
        if zlib.crc32(normalized[index : index + 4].encode("utf-8")) % 12 == 0
    )


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


def record_source_attempts(attempts: list[dict], items: list[dict], ranked: list[dict], args, max_age_days: int, errors: list[str]) -> None:
    """Write one ledger row per configured source so the stop condition is computed, not remembered."""
    from discovery_ledger import DEFAULT_LEDGER, eligible_key, record_attempt

    fulltext: dict[str, int] = {}
    eligible: dict[str, list[str]] = {}
    for item in items:
        if item.get("content_status") in {"fulltext", "transcript"}:
            fulltext[item.get("collected_by", "")] = fulltext.get(item.get("collected_by", ""), 0) + 1
    for item in ranked:
        if item.get("editorial_decision", {}).get("eligibility", {}).get("status") == "passed" and item.get("content_status") in {"fulltext", "transcript"}:
            key = eligible_key(item.get("link", ""))
            eligible.setdefault(item.get("collected_by", ""), []).append(key)
    for attempt in attempts:
        if not attempt.get("family"):
            continue
        name, results = attempt["source"], attempt["result_count"]
        full = min(fulltext.get(name, 0), results)
        keys = sorted(set(eligible.get(name, [])))[:full]
        try:
            record_attempt(DEFAULT_LEDGER, {
                "batch": args.batch, "owner": args.owner, "family": attempt["family"], "channel": "scrape_aihot",
                "query": name, "status": "success" if results and not attempt.get("error") else "failed",
                "result_count": results, "fulltext_count": full, "eligible_count": len(keys), "eligible_keys": keys,
                "selected_count": 0, "failure_type": (attempt.get("error") or "")[:120],
                "purpose": "discovery" if attempt.get("role") != "verification" else "smoke",
                "operation": "search", "evidence_url": attempt["url"], "round": args.round, "max_age_days": max_age_days,
            })
        except (OSError, ValueError) as exc:
            errors.append(f"检索账本写入失败 {name}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="为 Stephen 筛选 AI 热点选题")
    parser.add_argument("--fixture", type=Path, help="使用本地 JSON 数据，不联网")
    parser.add_argument("--inbox", type=Path, default=ROOT / ".local" / "source_inbox.json", help="公众号、B站、播客和本地逐字稿入口")
    parser.add_argument("--include-verification", action="store_true", help="同时抓取英文官方核验来源")
    parser.add_argument("--include-rejected", action="store_true", help="调试时在报告中包含未通过硬门槛的内容")
    parser.add_argument("--ai", action="store_true", help="调用 OpenRouter 模型复排（会计费，默认关闭）")
    parser.add_argument("--no-ai", action="store_true", help="兼容旧命令：不调用模型复排（现为默认行为）")
    parser.add_argument("--no-aigc", action="store_true", help=argparse.SUPPRESS)  # 朱雀检测已移除，保留以兼容旧命令
    parser.add_argument("--model", default="google/gemini-3-flash-preview")
    parser.add_argument("--output-root", type=Path, default=ROOT / "topics")
    parser.add_argument("--batch", help="写入检索账本时使用的批次 ID；不填则不记账")
    parser.add_argument("--owner", choices=["主力", "主力2"], default="主力")
    parser.add_argument("--round", type=int, help="本批第几轮检索，从 1 开始；与 --batch 同时使用")
    parser.add_argument("--pool", type=int, help="输出的待终审条数，默认取画像 report_candidate_count；要 20 条选题时可设 40")
    parser.add_argument("--no-cache", action="store_true", help="忽略共享抓取缓存，全部重新请求")
    args = parser.parse_args()
    if args.batch and (args.round is None or args.round < 1):
        parser.error("使用 --batch 记账时必须同时提供 --round（从 1 开始）")

    source_config = load_sources(RESOURCES / "content_curator_sources.json")
    profile = load_json(RESOURCES / "editorial_profile.json")
    settings = dict(source_config["fetch"])
    if not args.fixture and not args.no_cache:
        settings["cache_dir"] = str(ROOT / ".local" / "cache" / "http")
    errors = []
    source_attempts = []
    feedback_store = ROOT / ".local" / "editorial_feedback.jsonl"
    reviewed_candidates = [] if args.fixture else final_reviewed_candidates(feedback_store)
    if not args.fixture:
        reviewed_candidates += delivered_candidates(ROOT / "topics")
    reviewed_urls = {canonical_url(row.get("link", "")) for row in reviewed_candidates if row.get("link")}

    if args.fixture:
        items = load_json(args.fixture)
    else:
        items = load_inbox(args.inbox, settings, skip_urls=reviewed_urls)
        enabled_sources = [source for source in source_config["sources"] if args.include_verification or source.get("role") != "verification"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_source, source, settings): source for source in enabled_sources}
            for future in concurrent.futures.as_completed(futures):
                rows, error = future.result()
                source = futures[future]
                source_attempts.append({"source": source["name"], "url": source["url"],
                                        "family": source.get("family"), "role": source.get("role"),
                                        "result_count": len(rows), "error": error})
                items.extend(rows)
                if error:
                    errors.append(error)
        items = [item for item in items if canonical_url(item.get("link", "")) not in reviewed_urls]
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings["hydrate_workers"]) as executor:
            items = list(executor.map(lambda item: hydrate(item, settings), items))

    ranked = rank_candidates(items, profile)
    reviewed_ids = set() if args.fixture else final_reviewed_ids(feedback_store)
    skipped_reviewed_count = sum(1 for item in ranked if str(item["id"]) in reviewed_ids)
    ranked = [item for item in ranked if str(item["id"]) not in reviewed_ids]
    skipped_content_duplicate_count = sum(1 for item in ranked if is_historical_content_duplicate(item, reviewed_candidates))
    ranked = [item for item in ranked if not is_historical_content_duplicate(item, reviewed_candidates)]
    report_count = args.pool or profile["report_candidate_count"]
    minimum_delivery_count = int(profile.get("minimum_delivery_count", 5))
    minimum_non_github_candidates = int(profile.get("minimum_non_github_candidates", 1))
    maximum_github_candidates = int(profile.get("maximum_github_candidates", 1))

    if args.batch and not args.fixture:
        record_source_attempts(source_attempts, items, ranked, args, int(profile["max_age_days"]), errors)

    rejected_by_gate_count = sum(
        1 for item in ranked
        if item.get("editorial_decision", {}).get("eligibility", {}).get("status") == "failed"
    )
    held_for_editorial_review_count = sum(
        1 for item in ranked
        if item.get("editorial_decision", {}).get("machine_disposition") == "review"
    )
    candidates = select_report_candidates(
        ranked,
        report_count,
        include_rejected=args.include_rejected,
        maximum_github=maximum_github_candidates,
        min_article_chars=0 if args.fixture else int(settings.get("minimum_review_chars", 0)),
    )
    if args.ai and not args.no_ai and api_key():
        try:
            candidates = ai_rerank(candidates, profile, args.model)
        except Exception as exc:
            errors.append(f"AI 复排失败，已使用确定性排序: {exc}")

    selection_count = profile["selection_count"]
    for index, item in enumerate(candidates):
        item["selected_by_default"] = index < selection_count and item.get("machine_shortlisted", item["recommended"])

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
    discovery_items = [item for item in items if item.get("source_role") == "discovery"]
    (output_dir / "discovery.json").write_text(json.dumps(discovery_items, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "run.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "input_count": len(items),
                "source_attempts": source_attempts,
                "discovery_count": len(discovery_items),
                "skipped_reviewed_count": skipped_reviewed_count,
                "skipped_content_duplicate_count": skipped_content_duplicate_count,
                "rejected_by_gate_count": rejected_by_gate_count,
                "held_for_editorial_review_count": held_for_editorial_review_count,
                "candidate_count": len(candidates),
                "minimum_delivery_count": minimum_delivery_count,
                "minimum_non_github_candidates": minimum_non_github_candidates,
                "maximum_github_candidates": maximum_github_candidates,
                "non_github_candidate_count": non_github_candidate_count,
                "github_candidate_count": github_candidate_count,
                "composition_ready": ready_to_deliver,
                "delivery_ready": False,
                "include_rejected": args.include_rejected,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    generate_report(candidates, output_dir / "index.html", timestamp)
    print(f"待终审材料 {len(candidates)} 条，输入 {len(items)} 条，资格拒绝 {rejected_by_gate_count} 条；须完成原文终审与发布登记")
    if len(candidates) < minimum_delivery_count and not args.fixture:
        print(f"尚未达到交付门槛 {minimum_delivery_count} 条：继续扩源，直到满足完成契约或停止条件；不得用弱题补位")
    elif non_github_candidate_count < minimum_non_github_candidates and not args.fixture:
        print("候选全部来自 GitHub：继续补充高质量中文文章、博客或完整音视频材料，不得交付单一来源批次")
    if errors:
        print("抓取告警：")
        for error in errors:
            print(f"- {error}")
    print(output_dir / "index.html")


if __name__ == "__main__":
    main()
