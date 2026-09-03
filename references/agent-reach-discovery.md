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

## 热点选题检索组合

不要只跑一个搜索引擎。每轮至少组合三个互补渠道：

1. Exa 找跨站深度文章与独立博客：

```bash
mcporter call exa.web_search_exa query="查询词" numResults=10
```

2. 中文成品材料：

```bash
opencli weixin search "查询词" -f yaml
opencli zhihu search "查询词" -f yaml
opencli xiaohongshu search "查询词" -f yaml
bili search "查询词" --type video -n 10
opencli youtube search "查询词" -f yaml
```

3. 一手线索和反面意见：

```bash
opencli twitter search "查询词" -f yaml
opencli reddit search "查询词" -f yaml
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"
gh search repos "查询词" --sort updated --limit 10
```

Twitter、Reddit、V2EX、小红书短笔记和 GitHub 项目页默认只是线索。必须继续追到完整中文文章、原始长文、字幕或逐字稿，才能写入 `.local/source_inbox.json`。

## 阅读与字幕

```bash
opencli web read "URL" -f yaml
opencli bilibili subtitle BV号 -f yaml
opencli youtube transcript "URL" -f yaml
```

把通过人工判断的 YouTube 长视频直接加入 inbox 后，抓取脚本会调用 OpenCLI 获取完整字幕；字幕为空、过短或读取失败时，该视频不得进入正式候选。

公众号搜索结果需要继续打开原文。不能只拿搜狗摘要作为候选。遇到登录墙、关注墙、机器翻译、AI 总结页或正文截断，直接淘汰。

## 失败处理

- 先看 `status` 中的 `channels` 和 `missing_or_unverified_channels`。
- `doctor` 为避免读取 Cookie，可能把已经可用的 OpenCLI 平台标成未验证；只有任务需要该平台时，执行一次只读搜索，以真实非空结果验收。
- OpenCLI 未连接时，引导用户安装浏览器扩展；不得自动登录。
- Exa 不可用时继续使用公众号、知乎、B站和现有网页检索，不降低质量标准。
- 任何渠道失败都不能用低质量候选补足 3 条；继续切换其他渠道。
