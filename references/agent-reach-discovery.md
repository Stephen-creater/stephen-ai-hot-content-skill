# Agent Reach 内置检索路由

本文件只保留热点选题需要的 Agent Reach 用法。用户只调用 `stephen-ai-hot-content-skill`，不需要单独理解或安装 Agent Reach。

## 首次运行

先执行只读检查：

```bash
python3 scripts/agent_reach_runtime.py status
```

若 `installed` 为 `false`，运行下面的命令。它只把固定版本安装到 `~/.agent-reach/stephen-hot-content-runtime`，不会安装全局工具或读取浏览器 Cookie：

```bash
python3 scripts/agent_reach_runtime.py install
```

若核心渠道仍缺失，先向用户说明将安装的上游工具和登录边界。用户明确允许系统级安装后再运行：

```bash
python3 scripts/agent_reach_runtime.py install --system --channels all
```

不得把 API Key、Token、Cookie 或浏览器登录态写入本仓库。登录态平台只使用用户已经存在且明确控制的会话，不替用户登录。

## 浏览器隔离硬规则

本项目不得运行 `opencli`。当前 OpenCLI Browser Bridge 会连接用户的 Google Chrome，不能可靠绑定 Ego Browser 的隔离 Task Space，会弹出调试提示并干扰用户操作。

所有需要浏览器渲染、登录态或交互的页面统一直接使用 `ego-browser`，为热点选题复用同一个独立任务空间。任务完成后关闭该空间；不得启动、调试或操作用户的 Chrome。公开网页优先使用 HTTP、RSS、Exa 和平台 CLI，只有这些路径拿不到完整内容时才进入 Ego Browser。

## 热点选题检索组合

不要只跑一个搜索引擎。每轮至少组合三个互补渠道：

1. Exa 找跨站深度文章与独立博客：

```bash
mcporter call exa.web_search_exa query="查询词" numResults=10
```

2. 中文成品材料：B站先用非浏览器 CLI；公众号、知乎和小红书等动态页面使用 Ego Browser 独立空间检索。

```bash
bili search "查询词" --type video -n 10

ego-browser nodejs <<'EOF'
const task = await useOrCreateTaskSpace('stephen topic research')
await openOrReuseTab('搜索页面 URL', { wait: true, timeout: 30 })
cliLog(await snapshotText())
EOF
```

3. 一手线索和反面意见：

```bash
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"
gh search repos "查询词" --sort updated --limit 10
```

X、Reddit 等没有稳定非浏览器后端时，只能在 Ego Browser 独立空间中读取，不能回退 OpenCLI。

Twitter、Reddit、V2EX、小红书短笔记和 GitHub 项目页默认只是线索。必须继续追到完整中文文章、原始长文、字幕或逐字稿，才能写入 `.local/source_inbox.json`。

## 阅读与字幕

```bash
curl -s "https://r.jina.ai/URL"
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "YOUTUBE_URL"
```

把通过人工判断的 YouTube 长视频直接加入 inbox 后，抓取脚本会调用 `yt-dlp` 获取字幕。字幕为空、过短或读取失败时，该视频不得进入正式候选；如需浏览器补充，只能用 Ego Browser，取得的逐字稿以本地文件路径加入 inbox。

公众号搜索结果需要继续打开原文。不能只拿搜狗摘要作为候选。遇到登录墙、关注墙、机器翻译、AI 总结页或正文截断，直接淘汰。

## 失败处理

- 先看 `status` 中的 `channels` 和 `missing_or_unverified_channels`。
- 不得因为 `doctor` 显示 OpenCLI 已连接而使用它；本项目明确禁用该后端。
- 普通 HTTP 抓取遇到 403 或动态渲染页时，使用 Ego Browser 隔离空间人工获取正文，再作为本地材料加入；不得回退用户 Chrome。
- Exa 不可用时继续使用公众号、知乎、B站和现有网页检索，不降低质量标准。
- 任何渠道失败都不能用低质量候选补足 3 条；继续切换其他渠道。
