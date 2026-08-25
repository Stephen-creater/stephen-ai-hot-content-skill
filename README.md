# Stephen AI Hot Content Skill

Stephen 的个人 AI 热点选题 Skill。它根据既有文章和人工审核反馈，从 RSS 与网页来源中筛出适合日课创作的候选题。

## 核心能力

- RSS 优先、网页兜底。
- 按个人文章谱系做确定性评分和去重。
- API Key 可选，无 Key 也能运行。
- 生成可审核的静态 HTML。
- 支持标记入选、淘汰和遗漏，并导入本地反馈。

## 快速开始

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/scrape_aihot.py
```

输出位于 `topics/<时间戳>/index.html`。

离线演示：

```bash
python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --no-ai
```

导入人工审核：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json
```

## 配置

- `resources/content_curator_sources.json` 管理信息源。
- `resources/editorial_profile.json` 管理读者、选题方向、排除项和权重。
- `OPENROUTER_API_KEY` 或 `.config/openrouter_api_key.txt` 用于可选模型复排。

API Key、本地反馈、缓存和运行结果均不会提交到公开仓库。
