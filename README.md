# Stephen AI Hot Content Skill

Stephen 的个人 AI 热点选题 Skill。它优先寻找国内作者已经研究、解释和整理过的中文内容，包括公众号文章、中文播客、B站视频逐字稿和中文长文，再筛出适合日课二创的候选题。

## 核心能力

- 中文二手内容优先，英文官方来源只负责事实核验。
- 支持公众号、B站、播客链接和本地逐字稿 inbox。
- 按个人文章谱系做确定性评分和去重。
- 标记文字材料状态、二创成熟度和预计研究成本。
- API Key 可选，无 Key 也能运行。
- 生成可审核的静态 HTML。
- 正常报告只包含通过硬门槛的内容，允许少于配置数量或 0 条。
- 支持标记入选、淘汰和遗漏，并导入本地反馈。
- 已入选或已淘汰的同一条内容不会在后续报告中重复出现。
- 区分权威人物深度访谈与普通人物稿，并过滤活动广告、合作通稿和无名小发布。
- 内置经过 SHA-256 校验的 Agent Reach 运行时，用户无需单独安装另一个 Skill 即可启用多平台检索。

## 快速开始

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/agent_reach_runtime.py install
python3 scripts/add_source.py "内容链接" --platform wechat --creator "作者"
python3 scripts/add_source.py "YouTube 链接" --platform youtube --creator "频道名"
python3 scripts/scrape_aihot.py
```

需要一次性补齐 Exa、B站、OpenCLI 等系统渠道时，在明确允许用户级和全局工具安装后运行：

```bash
python3 scripts/agent_reach_runtime.py install --system --channels all
```

运行状态保存在用户自己的 `~/.agent-reach/`，Cookie、Token 和浏览器登录态不会进入本仓库。

输出位于 `topics/<时间戳>/index.html`。

审核页中的入选状态和备注会实时保存到当前浏览器，顶部工具栏会显示审核统计和是否存在未导出改动。由于浏览器不允许本地页面直接修改项目文件，JSON 会先进入下载目录。导入后的正式反馈保存在 `.local/editorial_feedback.jsonl`，使用 `--delete-source` 可在验证导入后自动清理下载文件。

离线演示：

```bash
python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --no-ai
```

导入人工审核：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json --delete-source
```

## 配置

- `resources/content_curator_sources.json` 管理信息源。
- `resources/editorial_profile.json` 管理读者、选题方向、排除项和权重。
- `.local/source_inbox.json` 保存人工投喂的公众号、视频、播客和逐字稿，仅本地使用。
- `OPENROUTER_API_KEY` 或 `.config/openrouter_api_key.txt` 用于可选模型复排。

API Key、本地反馈、缓存和运行结果均不会提交到公开仓库。
