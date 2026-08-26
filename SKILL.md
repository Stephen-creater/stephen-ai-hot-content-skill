---
name: stephen-ai-hot-content-skill
description: 按 Stephen 既有文章与人工反馈，抓取、筛选并排序适合日课创作的 AI 热点选题。用于寻找选题、生成候选报告、审核入选与淘汰项；不负责撰写文章正文。
---

# Stephen AI 热点选题

只负责发现与筛选选题。确认题目后的文章研究与写作交给 `stephen-writing-skill`。

## 选题标准

优先选择已经完成中文整合、可以低成本二创的内容：

- 国内高质量公众号文章、中文播客、B站小众深度视频和中文长文。
- 已有完整正文、字幕、逐字稿或详细 Show Notes 的内容。
- Agent、Codex、Claude Code、Harness、Skill、MCP 等系统与工作流变化。
- AI 对工作、组织、知识、教育和个人效率的真实影响。
- KV Cache、训练、上下文、智能涌现等能够用大白话讲透的机制。
- 作者已经提供明确判断、案例和因果链，二创时只需删减、重组和必要核验。
- 能找到一个具体切入点，并且具有长期回看价值。
- OpenAI、Anthropic、Google DeepMind 等核心团队人物的深度访谈，尤其是已有完整对话或逐字稿的内容。

默认排除：

- 只有融资、估值、跑分、榜单或小版本更新。
- 只有英文一手发布，需要从零补背景和中文解释。
- 多事件周报、新闻合集、商业通稿和缺少正文的标题党。
- 政治、娱乐、监控、武器等偏离既有文章谱系的内容。
- 需要大量专业背景，且无法转化成小白可理解价值的技术细节。
- 模型身份八卦、猎奇演示、夸张标题等只有热度没有深度的内容。
- 只讲重塑行业、未来趋势等宏大判断，却缺少具体机制、事件或用户价值。
- 科研、医疗等垂直专业题，除非能转化成普通读者可理解、可复用的核心机制。
- 无名小模型、小公司合作、活动招募、采购对接、签约和首发仪式。
- 纯融资、纯芯片算力新闻、硬件改造和用户无法复制的小众实操。
- 只复述新闻、篇幅很长却没有作者解读的内容。
- 只讲人物经历或群像的文章，权威访谈与完整对话材料除外。
- 宕机、故障、上线、发布等事件新闻超过两周时效窗口；权威访谈和深度实测不套用该短窗口。
- 只讨论企业维护成本、供应商锁定、准入基线或治理架构，难以转化成普通读者价值的内容。

详细权重与历史文章见 [编辑画像](resources/editorial_profile.json)，信息源见 [来源配置](resources/content_curator_sources.json)，人工投喂格式见 [inbox 示例](resources/source_inbox.example.json)。

## 运行

首次安装依赖：

```bash
python3 -m pip install -r scripts/requirements.txt
```

抓取并生成报告：

```bash
python3 scripts/scrape_aihot.py
```

正常报告只展示通过硬门槛的内容。`report_candidate_count` 是最大数量，不是必须凑满的配额。0 条合格时应直接输出 0 条，不得用低质量内容补位。

只有调试筛选规则时才可显式运行 `--include-rejected`，该模式不用于日常选题。

公众号、B站、播客或本地逐字稿先加入 inbox：

```bash
python3 scripts/add_source.py "内容链接" --platform wechat --creator "作者"
python3 scripts/add_source.py "B站链接" --platform bilibili --creator "UP主" --transcript "/path/to/transcript.txt"
python3 scripts/add_source.py "播客链接" --platform xiaoyuzhou --creator "节目" --transcript "/path/to/transcript.txt"
```

英文官方来源默认不进入候选池。需要为候选题补充核验线索时，运行 `--include-verification`。

没有 API Key 时使用确定性评分。需要模型复排时，配置环境变量 `OPENROUTER_API_KEY`，或把 Key 写入本地 `.config/openrouter_api_key.txt`。Key 禁止提交。

离线验证：

```bash
python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --no-ai
```

## 输出与人工审核

每次运行在 `topics/<时间戳>/` 生成：

- `candidates.json`：候选选题、分数、推荐理由、文字材料状态、二创成熟度与研究成本。
- `index.html`：人工审核页面。
- `run.json`：抓取数量和失败来源。

在 `index.html` 中标记应该入选、不应入选和遗漏选题。页面会将状态与备注实时保存到当前浏览器，但不会直接写入项目文件。完成审核后，点击「导出全部审核结果」。浏览器会先把 JSON 暂存在下载目录，正式反馈库位于 `.local/editorial_feedback.jsonl`。

导入反馈：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json
```

确认导入后同时删除下载的临时 JSON：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json --delete-source
```

反馈写入本地 `.local/editorial_feedback.jsonl`，不会进入公开仓库。后续根据反馈修改编辑画像、来源与评分逻辑。

已明确标记为入选或不入选的同一条内容，后续运行会自动跳过；待定内容仍可再次进入候选。

## 交付要求

- 默认展示候选报告，不擅自替用户确定最终选题。
- 抓取失败的来源写入 `run.json`，其余来源继续运行。
- 同一事件只保留信息最完整的一篇。
- 硬门槛未通过的内容禁止进入正常审核页。没有足够强的候选时允许少选或 0 条，不得用弱题凑数量。
- 运行测试后才能提交代码。
