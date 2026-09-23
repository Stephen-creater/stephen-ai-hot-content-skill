"""X 中文作者巡检：逐个翻作者主页，收最近几天的中文长帖，取作者自己那一串的全文。

Stephen 很多文章是在 X 上看到的（Jev、Codex 百万上下文、李新宝那条 Opus 5.5 和 GPT-6 Sol 的选型帖）。
以前 X 只靠批次里临时搜几个词，一批也就翻三五次。现在按固定名单每批翻一遍，名单在口味档案旁的
resources/x_authors.json，是写中文 AI 内容的作者和历史上系统抓到过的中文长帖作者。

用 ego-browser 打开 Stephen 登录着的 X，只读：不点赞、不关注、不回复。相邻页面间隔 3 秒以上，
一次最多打开 max_details 个帖子详情页（频率规矩见 references/channels.md 的“浏览器渠道”）。
结果缓存 cache_hours 小时，同一批的后几轮抓取不重复翻。

    .venv/bin/python3 scripts/x_sweep.py --hours 48      # 单独试跑，打印收到的长帖
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORS = ROOT / "resources" / "x_authors.json"
CACHE = ROOT / ".local" / "cache" / "x_sweep.json"

SCRIPT = """
const input = %s;
const task = await taskSpace("X 中文作者巡检");
const page = task.page("p1");
const since = Date.now() - input.hours * 3600 * 1000;
const picked = [];
const scanned = [];
// 连续 3 个页面打不开，多半是被 X 限流了：按渠道手册的规矩立刻停，不重试绕过。
let failures = 0;
let throttled = false;
for (const handle of input.handles) {
  if (failures >= 3) { throttled = true; break; }
  try {
    await page.goto("https://x.com/" + handle);
    await page.waitForSelector("article", { timeout: 12000 });
    await page.waitForTimeout(2500);
    const rows = await page.evaluate((author) => [...document.querySelectorAll("article")].map((a) => {
      const links = [...a.querySelectorAll("a")].map((x) => x.href);
      const link = links.find((h) => /\\/status\\/\\d+$/.test(h)) || "";
      const text = a.querySelector('[data-testid="tweetText"]')?.innerText || "";
      return {
        author, time: a.querySelector("time")?.getAttribute("datetime") || "",
        link, own: link.toLowerCase().includes("/" + author.toLowerCase() + "/status/"),
        more: !!a.querySelector('[data-testid="tweet-text-show-more-link"]'),
        article: links.some((h) => h.includes("/article/")),
        preview: text,
      };
    }), handle);
    const fresh = rows.filter((r) => r.own && r.time && Date.parse(r.time) >= since);
    scanned.push({ handle, posts: fresh.length });
    // 只有带“显示更多”的帖子和 X 文章才可能写满 500 字；主页上能完整显示的都是短帖，不点。
    for (const r of fresh) if (r.more || r.article) picked.push(r);
    failures = 0;
  } catch (error) {
    failures += 1;
    scanned.push({ handle, error: String(error).slice(0, 120) });
  }
}
// X 文章优先，其余按作者轮流排，名单靠后的作者也能轮到，不是前面几个人占满详情页名额。
const byAuthor = {};
for (const r of picked) (byAuthor[r.author] ||= []).push(r);
const queue = picked.filter((r) => r.article);
for (let round = 0; queue.length < picked.length && round < 20; round++)
  for (const list of Object.values(byAuthor)) { const r = list.filter((x) => !x.article)[round]; if (r) queue.push(r); }
const results = [];
for (const r of queue.slice(0, input.maxDetails)) {
  if (failures >= 3) { throttled = true; break; }
  try {
    await page.goto(r.link);
    await page.waitForSelector("article", { timeout: 12000 });
    await page.waitForTimeout(3000);
    // 这个账号的界面会让 Grok 把中文帖自动翻成英文，点“显示原文”切回原文再读。只切换显示，不改账号设置。
    const flipped = await page.evaluate(() => {
      const labels = ["Show original", "显示原文", "顯示原文", "Mostrar original", "Ver original"];
      const hits = [...document.querySelectorAll("article span, article button, article [role=button]")].filter((el) => labels.includes((el.innerText || "").trim()));
      hits.forEach((el) => el.click());
      return hits.length;
    });
    if (flipped) await page.waitForTimeout(2500);
    const text = await page.evaluate((author) => [...document.querySelectorAll("article")]
      .filter((a) => ([...a.querySelectorAll("a")].map((x) => new URL(x.href).pathname.split("/")[1]).find(Boolean) || "").toLowerCase() === author.toLowerCase())
      .map((a) => a.querySelector('[data-testid="twitterArticleRichTextView"]')?.innerText || a.querySelector('[data-testid="tweetText"]')?.innerText || "")
      .filter(Boolean).join("\\n\\n"), r.author);
    results.push({ ...r, text });
    failures = 0;
  } catch (error) {
    // 主页上的预览可能是 Grok 的英文译文，不能拿来顶替正文。
    failures += 1;
    results.push({ ...r, text: "", error: String(error).slice(0, 120) });
  }
}
await task.finish({ keep: [] });
console.log("EGO_JSON_START" + JSON.stringify({ scanned, results, throttled, skipped: Math.max(0, queue.length - input.maxDetails) }) + "EGO_JSON_END");
"""


def load_authors(path: Path = AUTHORS) -> list[str]:
    return [row["handle"] for row in json.loads(path.read_text(encoding="utf-8"))["authors"]] if path.exists() else []


def run_browser(handles: list[str], hours: int, max_details: int, timeout: int) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(SCRIPT % json.dumps({"handles": handles, "hours": hours, "maxDetails": max_details}, ensure_ascii=False))
        script_path = handle.name
    try:
        with open(script_path, encoding="utf-8") as script:
            result = subprocess.run(["ego-browser", "nodejs"], stdin=script, capture_output=True, text=True, timeout=timeout)
    finally:
        Path(script_path).unlink(missing_ok=True)
    text = result.stdout + result.stderr
    if "EGO_JSON_START" not in text:
        raise RuntimeError("X 巡检没有返回结果：" + text[-300:])
    return json.loads(text.split("EGO_JSON_START", 1)[1].split("EGO_JSON_END", 1)[0])


def to_rows(payload: dict, source: dict) -> list[dict]:
    rows = []
    for post in payload.get("results", []):
        text = (post.get("text") or "").strip()
        if not text or post.get("error"):
            continue
        first = next((line.strip() for line in text.splitlines() if line.strip()), text)[:80]
        rows.append({
            "title": first, "link": post["link"], "summary": text[:300], "content": text,
            "published": post.get("time", ""), "source_name": f"X：{post['author']}",
            "source_category": source.get("category", "X 中文作者"), "source_priority": source.get("priority", 5),
            "source_type": "x", "source_role": "candidate", "social_post": True,
            "language": "zh", "maturity": "secondary", "content_form": "article",
            "content_status": "fulltext" if len(text) >= 200 else "summary", "content_origin": "x_sweep",
        })
    return rows


def fetch(source: dict, cache: Path = CACHE, runner=run_browser) -> list[dict]:
    """抓取脚本调用的入口。缓存没过期就直接用，免得同一批每一轮都翻一遍 X。"""
    ttl = float(source.get("cache_hours", 3)) * 3600
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if time.time() - cached.get("at", 0) < ttl:
            return to_rows(cached["payload"], source)
    handles = load_authors()
    if not handles:
        return []
    payload = runner(handles, int(source.get("hours", 48)), int(source.get("max_details", 30)),
                     timeout=int(source.get("timeout_seconds", 900)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"at": time.time(), "payload": payload}, ensure_ascii=False), encoding="utf-8")
    if payload.get("throttled"):
        print("X 巡检中途被限流，停在半路，这一轮只用已经拿到的部分；三小时内不再翻。")
    return to_rows(payload, source)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--max-details", type=int, default=30)
    args = parser.parse_args()
    payload = run_browser(load_authors(), args.hours, args.max_details, timeout=900)
    print(json.dumps(payload["scanned"], ensure_ascii=False))
    for row in to_rows(payload, {}):
        print(json.dumps({"link": row["link"], "chars": len(row["content"]), "title": row["title"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
