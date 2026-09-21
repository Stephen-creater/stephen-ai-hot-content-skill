# 取材渠道手册

每个平台就是一个取材渠道。本文件写清楚每个渠道能拿到什么、用什么命令、有什么限制。先用 `.venv/bin/python3 scripts/channel_check.py --live` 看哪些渠道今天能用，再按缺口选渠道。

## 总原则

- 订阅源（`content_curator_sources.json`）是主力，抓取脚本自动跑。下面这些渠道用来补缺口：找作者、找原文、找文字稿。
- **线索不能停在清单里**：每批抓完跑 `harvest_leads.py`，给线索补正文再登记成候选；抓不到正文的自动用 ego-browser 兜底。一个源如果天天出现在清单里却从没产出过候选，就是空转，要么修取材方式，要么按 `source_yield.py` 的数据降级或去掉。
- 社交平台、社区、搜索结果、GitHub 页面只提供线索。能进候选的，必须是追到的完整中文文章、长文或逐字稿。
- 找到的原文一律用 `scripts/add_source.py` 登记，再重跑抓取，由程序检查资格。不要手写“这篇合格”。
- 每次搜索都用 `discovery_ledger.py record` 记下渠道、查询词和结果数。渠道名写下表的 id。
- 某个渠道失败，就换别的渠道，并在交付时写明“哪个渠道没查成、为什么”。不能说成“没有好材料”。

## 渠道一览

实测日期 2026-09-19。状态会变，以 `channel_check.py --live` 为准。

| id | 平台 | 能做什么 | 命令 | 实测 |
|---|---|---|---|---|
| `rss` | 各类订阅源 | 自动拉文章、播客、视频更新 | 抓取脚本内置 | 可用 |
| `waytoagi` | WayToAGI 知识库精选 | 每天一页人工精选的中文文章 | 抓取脚本内置（`type: waytoagi`） | 可用，2026-09-20 实测 17 条取到 11 条合格 |
| `web_reader` | 任意公开网页 | 取网页正文（Markdown） | `curl -s "https://r.jina.ai/<URL>"` | 可用 |
| `exa_search` | 全网 | 按主题跨站搜长文、博客 | `mcporter call exa.web_search_exa query="<查询>" numResults=10` | 可用，结果中 SEO 内容多，要逐条看 |
| `github` | GitHub | 搜仓库，核对 Star、最近更新、Release | `gh search repos "<查询>" --sort updated --limit 10` | 可用 |
| `youtube` | YouTube | 取字幕 | `yt-dlp --write-sub --write-auto-sub --sub-lang "zh-Hans,zh,en" --skip-download -o "/tmp/%(id)s" "<URL>"` | 可用 |
| `bilibili` | B 站 | 搜视频、取字幕 | `bili search "<查询>" --type video -n 10` | 可用 |
| `x` | X（推特） | 看首页时间线、作者主页、搜关键词，取长帖全文 | `ego-browser`，见下文“X（推特）” | 主力渠道，每批必跑；命令行 `twitter` 超时，不用 |
| `v2ex` | V2EX | 热门帖、节点、帖子详情 | `curl -s https://www.v2ex.com/api/topics/hot.json` | 可用 |
| `zhihu` | 知乎 | 搜索、读回答和专栏、看作者文章 | 见下文“知乎” | 需要浏览器登录态 |
| `browser` | 需要登录或渲染的页面 | X、小红书、Reddit、知乎的搜索、详情、作者页 | `ego-browser`（隔离浏览器） | 可用 |
| `local_transcribe` | 播客音频 | 本机离线转文字 | 见下文“音视频转文字” | 需要本地模型 |

## 国内站点的网络

本机代理是全局模式，国内站点（公众号原文、知乎、掘金、InfoQ、B 站、小红书、微博、抖音、百度等）要经本机的 `cn-direct` 直连才打得开。本仓库的会话启动时已自动配好：命令行里的 curl、Python、Node 和 `ego-browser` 都会自动走它，不用加前缀。

- 国内站点报 `SSL`、`WRONG_VERSION_NUMBER` 或 `ERR_SSL_PROTOCOL_ERROR`，是没走上直连，不是网站挂了。命令前加 `cn-direct` 重试，例如 `cn-direct curl -s <URL>`。
- `ego-browser` 提示 ego lite 缺少国内直连参数时，请你完全退出 ego lite，再重跑一次命令。
- 海外站点照常走代理，不受影响。

## 浏览器渠道

只在常规渠道不够、原文确实需要登录或渲染、或你指定平台时才用。

- 使用隔离浏览器（Ego Browser）的独立任务空间。不启动、不操作你日常用的 Chrome，不导出 Cookie，不替你登录。
- 每个任务一个空间，用完关掉。同一空间里的操作一个一个来，不并发切标签。
- 登录态只用来发现和核对。候选原文必须是不登录也能公开读到的完整正文。
- 控制频率：相邻页面操作间隔至少 3 秒，每个查询最多翻 3 页，每次任务最多打开 30 个详情页。遇到验证码、429、登录失效或风控提示立刻停，换渠道，不重试绕过。只有你指定的平台或唯一的缺口，才请你来处理验证。
- 页面列表是空的，先查视口：宽高为 0 时设置 1280×900 再重新加载。空视口不是登录问题。
- 取正文时不要只拿第一个 `<article>`，它可能是站内 AI 总结卡。先核对标题、正文起止和结尾署名。例如人人都是产品经理的正文在 `.article--content`，另有一个 `article-intelligence` 总结卡。

已走通的路径：

- 小红书：打开 `/search_result?keyword=<查询>`，进详情核对正文、图片依赖、评论，再看作者主页。评论区的 AI 总结不是作者正文。
- Reddit：先进社区 `/r/ChatGPT/`，再用社区内搜索 `/r/ChatGPT/search/?q=<查询>&restrict_sr=1`。

## X（推特）

Stephen 日常刷 X，很多文章就是在这里看到并二创的。这个渠道和公众号、中文精选站同等重要，**每批都要跑**，不是缺口时才用。
没有可用接口：`twitter` 命令行超时，公开 RSS 只覆盖 25 个固定账号，都只能当补充。主力方式是用 ego-browser 打开他登录着的 X。

每批至少做这三件事，做完把查询词和结果数记进 `discovery_ledger.py record`：

1. **首页时间线**：打开 `https://x.com/home`，看最近 24 小时。这是他关注的人今天在聊什么，别的渠道看不到。
2. **重点作者主页**：打开 `https://x.com/<handle>`，看有没有新的长帖或实测。名单见 `resources/content_curator_sources.json` 里 `X 一线作者雷达` 和 `follow-builders` 两组，也可以从时间线里新发现的人补。
3. **关键词搜索**：`https://x.com/search?q=<查询>&f=live`（按时间）或 `&f=top`（按热度）。查询词围绕 [信息源清单](source_discovery_playbook.md) 的“搜索组合”，再加上当天多源刷屏里冒出来的名字。

三段实测可用的取材代码（2026-09-20 实测通过，`ego-browser nodejs < 脚本文件`；一个批次共用一个 task space）：

```js
// 1. 首页时间线：他关注的人今天在聊什么
const task = await taskSpace("X 渠道");           // 后续轮次用 taskSpace(<上一轮打印的 spaceId>)
const page = task.page("p1");
await page.goto("https://x.com/home");
await page.waitForTimeout(4000);
console.log(await page.evaluate(() => [...document.querySelectorAll("article")].slice(0, 30).map((a) => ({
  text: a.innerText.replace(/\n/g, " ").slice(0, 160),
  link: [...a.querySelectorAll("a")].map((x) => x.href).find((h) => h.includes("/status/")),
}))));
```

```js
// 2. 关键词搜索：f=live 按时间，f=top 按热度；作者主页把 URL 换成 https://x.com/<handle>
await page.goto("https://x.com/search?q=" + encodeURIComponent("Agent 实测") + "&f=live");
```

```js
// 3. 长帖取全文：只留作者自己的那几条，连起来才是完整正文
await page.goto("<帖子链接>");
await page.waitForTimeout(4000);
console.log(await page.evaluate(() => {
  const author = location.pathname.split("/")[1].toLowerCase();
  return [...document.querySelectorAll("article")]
    .map((a) => ({
      handle: ([...a.querySelectorAll("a")].map((x) => new URL(x.href).pathname.split("/")[1]).find(Boolean) || "").toLowerCase(),
      text: a.innerText,
    }))
    .filter((p) => p.handle === author)
    .map((p) => p.text)
    .join("\n");
}));
```

取材要点：

- **长帖要展开**：一条主推下面常挂着整串（thread），点开“显示更多”和回复串，把作者自己的部分连起来才是完整正文。只取第一条等于断章。
- **看数字**：转赞数、谁转的、评论区在吵什么，这些是热度判断的依据，抓取脚本拿不到。写进登记时的备注。
- **注意自动翻译**：X 会把外文自动译成中文，原文语言以“显示原文”为准。中文长帖才算中文材料。界面语言不一定是中文（实测这个账号是葡萄牙语，“显示原文”写作 Mostrar tradução），所以按结构取元素，不要按按钮文字找。
- **篇幅**：X 和即刻的帖子写满五百字就算完整一篇（公众号长文要八百字），这是平台原生写法的差别，不是放低标准。
- **登记**：值得读全文的长帖存成文本文件，再 `.venv/bin/python3 scripts/add_source.py <帖子链接> --platform x --creator "<作者>" --content-file <正文文件> --notes "转赞数、为什么值得"`。英文官方发布帖加 `--language en --official-release`。登记后重跑抓取，由程序走资格判定，不要手写“这篇合格”。
- **只读**：不发帖、不点赞、不关注、不回复，不动 Stephen 的账号状态。

## 知乎

知乎的历史入选率低（43 条审核里选中 2 条），入选的都是产品负责人或创始人围绕具体产品决策的完整访谈。只在知乎是明确缺口或你指定时使用。

- `opencli zhihu --help -f yaml` 可以查看只读命令（搜索、问题、回答详情、作者回答、作者文章）和它们用的接口。这个命令不需要浏览器。
- 取数据时，在浏览器渠道里打开 `https://www.zhihu.com`，用页面内的请求调用同样的只读接口，例如搜索 `/api/v4/search_v3?q=<查询>&t=general&offset=0&limit=20`，完整回答 `/api/v4/answers/<id>`。
- 不运行 `opencli` 的登录命令，不让它接管你的 Chrome。记账时渠道写 `zhihu`，说明是浏览器会话取回的。
- 频率：同一接口相邻请求间隔至少 2 秒，每个查询最多 5 页，每次最多读 50 篇正文。
- 热榜、问题页、搜索列表都只是线索。逐条打开原文，核对作者、日期、正文是否完整。

## 音视频转文字

按顺序取，前一步拿到就停：

1. 节目方或公众号发布的中文文字版。
2. BestBlogs 的播客转录。说话人只有编号、专名可能错，交付前补上主持人和嘉宾名字，校对专名。
3. 平台字幕：YouTube 用 `yt-dlp`，B 站用 `bili`。字幕和发布者文字版都有时，用 `scripts/format_captions.py <字幕> <文字版> <输出>` 生成可读稿：只借文字版的标点和分段，不改字幕原词。
4. 本机离线转写（Apple Silicon，本地已有 MLX Whisper 模型时）：

```bash
HF_HUB_OFFLINE=1 uv run --with mlx-whisper==0.4.3 python scripts/local_transcribe.py \
  本地音频.wav --model 本地模型目录 --output .local/work/转写.json \
  --initial-prompt "发布者给出的人名、公司名和术语"
```

转写结果没有标点、专名错得多。正式使用前要核对音频时长、结尾是否转完、专名和数字。样本转写不能当完整逐字稿。没有可读文字稿的音视频只算线索。

字幕为空、太短或读取失败的视频，不进候选。关键内容只在画面里（“点这里”“可以看到”一类操作演示）的视频，在审稿时重点核实文字能不能单独讲清楚。

## 失败时怎么办

- 网页返回 403 或需要渲染：先判断值不值得补读，值得就换公开来源或用浏览器渠道取正文，保存为本地文件后登记。
- 公众号搜索结果要打开原文，不能只拿搜索摘要。遇到登录墙、关注墙、机器翻译页、AI 总结页或正文截断，直接放弃这条。
- Exa 不可用时，继续用订阅源、公众号、网页读取和 B 站或 YouTube 字幕，标准不降。
