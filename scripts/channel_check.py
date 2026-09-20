"""检查每个取材渠道在本机能不能用。

默认只看工具装没装；加 --live 会对每个渠道真的查一次，结果非空才算可用。
渠道的用法和限制见 references/channels.md。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess

# id -> (所需命令, 真实查询命令, 说明)
CHANNELS: dict[str, tuple[str | None, str | None, str]] = {
    "rss": (None, None, "订阅源，抓取脚本内置"),
    "web_reader": ("curl", 'curl -s -m 25 "https://r.jina.ai/https://example.com/"', "读取任意公开网页正文"),
    "exa_search": ("mcporter", 'mcporter call exa.web_search_exa query="AI Agent 复盘" numResults=2', "跨站搜索中英文长文"),
    "github": ("gh", 'gh search repos "claude skill" --limit 2', "搜索仓库、核验 Star 和更新时间"),
    "youtube": ("yt-dlp", 'yt-dlp --skip-download --print title "https://www.youtube.com/watch?v=dQw4w9WgXcQ"', "取视频字幕"),
    "bilibili": ("bili", 'bili search "AI Agent" --type video -n 2', "B 站搜索和字幕"),
    "twitter": ("twitter", 'twitter search "Claude Code" -n 2', "X 搜索（需要本机已有登录态）"),
    "v2ex": ("curl", 'curl -s -m 15 https://www.v2ex.com/api/topics/hot.json', "V2EX 热门和帖子"),
    "zhihu": ("opencli", "opencli zhihu --help -f yaml", "知乎只读命令说明；取数据需走浏览器登录态"),
    "browser": ("ego-browser", None, "隔离浏览器；X 每批必跑，另用于小红书、Reddit、知乎"),
    "local_transcribe": ("ffmpeg", None, "本机离线语音转文字的前置工具"),
}


def check(channel: str, live: bool) -> dict:
    tool, probe, note = CHANNELS[channel]
    if tool and not shutil.which(tool):
        return {"channel": channel, "status": "missing", "note": note, "detail": f"未安装 {tool}"}
    if not live or not probe:
        return {"channel": channel, "status": "installed", "note": note}
    try:
        result = subprocess.run(probe, shell=True, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"channel": channel, "status": "failed", "note": note, "detail": "60 秒超时"}
    output = (result.stdout or "").strip()
    if result.returncode == 0 and len(output) > 20 and '"ok": false' not in output and "ok: false" not in output:
        return {"channel": channel, "status": "ok", "note": note}
    detail = (result.stderr or result.stdout or "").strip().replace("\n", " ")[:160]
    return {"channel": channel, "status": "failed", "note": note, "detail": detail}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="对每个渠道真的查一次")
    parser.add_argument("channels", nargs="*", choices=sorted(CHANNELS), help="只检查这些渠道")
    args = parser.parse_args()
    rows = [check(name, args.live) for name in (args.channels or CHANNELS)]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
