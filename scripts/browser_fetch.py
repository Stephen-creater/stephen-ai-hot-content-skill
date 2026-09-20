"""抓不到的正文，用 ego-browser 兜底取回来。

微信、知乎这类站点对脚本请求返回验证页（“环境异常，完成验证后即可继续访问”），
直连和网页读取都拿不到正文。浏览器带着登录态和真实环境能打开，所以它是最后一道兜底：
抓取脚本发现正文被拦或抓取失败时，把这些链接交给这里，取回正文再继续判定。

只读页面，不点赞不发帖不改任何账号状态。一次任务共用一个 task space，用完关掉。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIMIT = 25
PER_PAGE_TIMEOUT_MS = 20000

SCRIPT = """
const urls = %s;
const task = await taskSpace("兜底取正文");
const page = task.page("p1");
const results = [];
for (const url of urls) {
  try {
    await page.goto(url);
    await page.waitForTimeout(3500);
    const row = await page.evaluate(() => {
      const pick = ["#js_content", ".rich_media_content", "article", "main", ".article-content", ".post-content"];
      let node = null;
      for (const selector of pick) {
        const found = document.querySelector(selector);
        if (found && found.innerText && found.innerText.trim().length > (node?.innerText?.trim().length || 0)) node = found;
      }
      const text = (node || document.body)?.innerText || "";
      return { title: document.title || "", text: text.trim().slice(0, 60000), images: document.querySelectorAll("img").length };
    });
    results.push({ url, ok: true, ...row });
  } catch (error) {
    results.push({ url, ok: false, error: String(error).slice(0, 200) });
  }
}
await task.finish({ keep: [] });
console.log("EGO_JSON_START" + JSON.stringify(results) + "EGO_JSON_END");
"""


def fetch(urls: list[str], limit: int = DEFAULT_LIMIT, timeout: int | None = None) -> dict[str, dict]:
    """{url: {title, text, images}}；打不开的不返回。"""
    urls = [url for url in dict.fromkeys(urls) if url.startswith("http")][:limit]
    if not urls:
        return {}
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(SCRIPT % json.dumps(urls, ensure_ascii=False))
        script_path = handle.name
    try:
        with open(script_path, encoding="utf-8") as script:
            result = subprocess.run(["ego-browser", "nodejs"], stdin=script, capture_output=True, text=True,
                                    timeout=timeout or (len(urls) * (PER_PAGE_TIMEOUT_MS // 1000) + 60))
    except (OSError, subprocess.SubprocessError):
        return {}
    finally:
        Path(script_path).unlink(missing_ok=True)
    # ego-browser 把脚本的 console.log 写在 stderr 上。
    text = result.stdout + result.stderr
    if "EGO_JSON_START" not in text or "EGO_JSON_END" not in text:
        return {}
    payload = text.split("EGO_JSON_START", 1)[1].split("EGO_JSON_END", 1)[0]
    try:
        rows = json.loads(payload)
    except ValueError:
        return {}
    return {row["url"]: row for row in rows if isinstance(row, dict) and row.get("ok") and row.get("text")}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    for url, row in fetch(args.urls, args.limit).items():
        print(json.dumps({"url": url, "title": row.get("title", ""), "chars": len(row.get("text", "")),
                          "head": row.get("text", "")[:120]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
