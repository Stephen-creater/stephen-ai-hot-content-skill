# Agent Reach 内置检索路由

本文件只保留热点选题需要的 Agent Reach 用法。用户只调用 `stephen-ai-hot-content-skill`，不需要单独理解或安装 Agent Reach。

## 首次运行

默认先用已有内容源、聚合检索、RSS、公开文章索引、网页抓取与可用 CLI。Ego Browser 仅是补充路径，不是首次运行或每轮必测项目。CLI 缺少 Cookie 或 Doctor 返回未验证时，不据此宣称整个平台不可用，也不强制启动浏览器；优先其他可用常规入口，确有材料缺口或用户指定时再用已授权的 Ego 登录态。

决定使用 Ego 后，按本次需要验证搜索、正文或作者页，不重复无关通路测试。已登录但列表为空只表示该操作未成功，检查加载状态和页面提示。仅在页面实际要求登录或验证时才请求用户操作；API 和付费接入另行评估并取得授权，不导出 Cookie。

覆盖报告必须注明已测试的后端与操作。Doctor 不能检测 Ego Browser 登录态；由 Doctor 推算的分数不能称为全渠道真实覆盖率。

若已登录但搜索列表为空，先检查 `pageInfo()` 的视口。宽高为 0 时，用 `cdp('Emulation.setDeviceMetricsOverride', {width:1280,height:900,deviceScaleFactor:1,mobile:false})` 设置正常视口，重新加载并等待列表出现；空视口不属于凭据问题。

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

仅在常规路径不足、值得读取的原文需要渲染/登录态/交互或用户指定时，按需使用 `ego-browser`。各任务独占空间，同一空间内的操作串行，禁止多个进程同时切换它的当前标签；不默认大量多开。完成后关闭自己的空间，不得启动、调试或操作用户的 Chrome。无需为了使用 Ego 先穷尽所有工具，也不能因为有动态页面就强制走浏览器。

## 热点选题检索组合

### Ego Browser 已验证的操作路径

- X：正常视口打开 `/search?q=查询词`，等 `article` 出现；逐条取正文和 `/status/` 链接，再打开详情。作者主页可用于连续追踪。检查是否自动翻译；原始材料语言以“显示原文”后的内容为准。
- 小红书：打开 `/search_result?keyword=查询词`，读取结果中的完整链接，进入详情核对正文、图片依赖、评论，再打开作者主页。详情链接里的 xsec_token 是页面链接参数，保留在私有材料内；不要把评论中的 AI 总结当作作者正文。
- Reddit：先打开目标社区 `/r/ChatGPT/`，用社区搜索 `/r/ChatGPT/search/?q=workflow&restrict_sr=1`；打开搜索结果中的帖子，读取正文和回复，再由页面作者链接追踪公开主页。
- 每个新标签页检查视口并等待内容实际出现，不能只在 load 事件后立刻把空列表判为失败。

首次检索记录 purpose=smoke；真正围绕选题进行搜索时记录 purpose=discovery。连通、材料质量、用户采纳分别验收，任何一步成功都不能替代下一步。

正文定位不能只取第一个 `<article>`：它可能是站内 AI 总结卡。先核对原始标题、正文起止和末尾署名，再确定容器。人人都是产品经理本轮验证正文在 `.article--content`，页面另有 `article-intelligence` 摘要卡；读取其他站点也须检查同类问题。页面辅助总结和评论不能混作作者正文。

不要只跑一个搜索引擎。每轮至少组合三个互补渠道：

1. Exa 找跨站深度文章与独立博客：

```bash
mcporter call exa.web_search_exa query="查询词" numResults=10
```

2. 中文成品材料：优先公开文章索引、中文 RSS、网页全文与非浏览器 CLI；Ego 仅在这些路径不足或原文确需交互时补充。下面浏览器命令是可选用法，不是必跑步骤。

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

X、Reddit 等没有稳定非浏览器后端时，可先转向其他常规来源；只有值得继续追踪的材料才用 Ego 独立空间补读，不能回退 OpenCLI。

Twitter、Reddit、V2EX、小红书短笔记和 GitHub 项目页默认只是线索。必须继续追到完整中文文章、原始长文、字幕或逐字稿，才能写入 `.local/source_inbox.json`。

## 阅读与字幕

字幕失败时，先查发布者官网/RSS 的原始音频和文字稿链接。已验证硅谷101官方 RSS 提供单集页面、日期和音频 enclosure，抓取器将其保存为 `audio_url`，不把 Show Notes 当逐字稿。

Apple Silicon 本地已有 MLX Whisper 模型时，可用本地转写兜底：

```bash
HF_HUB_OFFLINE=1 uv run --with mlx-whisper==0.4.3 python scripts/local_transcribe.py \
  本地音频.wav --model 本地模型目录 --output .local/work/转写.json \
  --initial-prompt "发布者给出的人名、公司名和术语"
```

此路径无外部音频上传。测试片段加 `--sample`；转写器始终不自行宣称原来源完整。正式材料须核对音频时长、尾部覆盖、专名与数字；不得把样本或异常重复转写标为完整逐字稿。没有本地模型时，先核验可用浏览器字幕，再决定是否需要安装或外部转写服务。

```bash
curl -s "https://r.jina.ai/URL"
yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "YOUTUBE_URL"
```

把通过人工判断的 YouTube 长视频直接加入 inbox 后，抓取脚本会调用 `yt-dlp` 获取字幕。字幕为空、过短或读取失败时，该视频不得进入正式候选；如需浏览器补充，只能用 Ego Browser，取得的逐字稿以本地文件路径加入 inbox。

公众号搜索结果需要继续打开原文。不能只拿搜狗摘要作为候选。遇到登录墙、关注墙、机器翻译、AI 总结页或正文截断，直接淘汰。

## 失败处理

- 先看 `status` 中的 `channels` 和 `missing_or_unverified_channels`。
- 不得因为 `doctor` 显示 OpenCLI 已连接而使用它；本项目明确禁用该后端。
- 普通 HTTP 抓取遇到 403 或动态渲染页时，先判断该材料是否值得补读；可换其他公开来源，或按需使用 Ego 获取正文再作为本地材料加入，不强制浏览器重试，不回退用户 Chrome。
- Exa 不可用时继续使用公众号、知乎、B站和现有网页检索，不降低质量标准。
- 任何渠道失败都不能用低质量候选补足 5 条；继续切换其他渠道，直到满足 `SKILL.md` 的数量、质量与来源构成要求。
