---
name: stephen-ai-hot-content-skill
description: 按 Stephen 既有文章与人工反馈，抓取、筛选并排序适合日课创作的 AI 热点选题。用于寻找选题、生成候选报告、审核入选与淘汰项；不负责撰写文章正文。
---

# Stephen AI 热点选题

只负责发现与筛选选题。确认题目后的文章研究与写作交给 `stephen-writing-skill`。

## 选题标准

优先选择：

- Agent、Codex、Claude Code、Harness、Skill、MCP 等系统与工作流变化。
- 重要模型、API、开源项目或产品发布，且能说清普通人的使用价值。
- AI 对工作、组织、知识、教育和个人效率的真实影响。
- KV Cache、训练、上下文、智能涌现等能够用大白话讲透的机制。
- 有明确事件、事实、数字、案例、冲突或反常识判断，能形成单一因果链。

默认排除：

- 只有融资、估值、跑分、榜单或小版本更新。
- 多事件周报、新闻合集、商业通稿和缺少正文的标题党。
- 政治、娱乐、监控、武器等偏离既有文章谱系的内容。
- 需要大量专业背景，且无法转化成小白可理解价值的技术细节。

详细权重与历史文章见 [编辑画像](resources/editorial_profile.json)，信息源见 [来源配置](resources/content_curator_sources.json)。

## 运行

首次安装依赖：

```bash
python3 -m pip install -r scripts/requirements.txt
```

抓取并生成报告：

```bash
python3 scripts/scrape_aihot.py
```

没有 API Key 时使用确定性评分。需要模型复排时，配置环境变量 `OPENROUTER_API_KEY`，或把 Key 写入本地 `.config/openrouter_api_key.txt`。Key 禁止提交。

离线验证：

```bash
python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --no-ai
```

## 输出与人工审核

每次运行在 `topics/<时间戳>/` 生成：

- `candidates.json`：候选选题、分数、推荐理由与排除原因。
- `index.html`：人工审核页面。
- `run.json`：抓取数量和失败来源。

在 `index.html` 中标记应该入选、不应入选和遗漏选题，然后导出 `selection_feedback.json`。

导入反馈：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json
```

反馈写入本地 `.local/editorial_feedback.jsonl`，不会进入公开仓库。后续根据反馈修改编辑画像、来源与评分逻辑。

## 交付要求

- 默认展示候选报告，不擅自替用户确定最终选题。
- 抓取失败的来源写入 `run.json`，其余来源继续运行。
- 同一事件只保留信息最完整的一篇。
- 没有足够强的候选时，允许少选，不用弱题凑数量。
- 运行测试后才能提交代码。
