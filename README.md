# Stephen AI Hot Content Skill

Stephen 的个人 AI 选题系统：找能改写成文章的简体中文 AI 材料，读完全文判断值不值得推荐，交给 Stephen 审核，再从审核结果里学习。文章写作不在这里做。

执行步骤、条数和停止条件以 [SKILL.md](SKILL.md) 为准，这里只讲它是怎么工作的。

## 它怎么工作

一批选题分三层分工：

- **脚本**：抓取 197 个订阅源和手动登记的文章，做一票否决（语言、全文、时效、写过、Star 等客观条件）、排序和去重。
- **Agent**：先通读全部合格材料的标题和开头，挑出要读的；读完全文按六个维度各打 0 到 2 分（选题吸引力、读者改变、干货含量、可重写性、长期价值，外加只作参考的改写成本），前五维至少 6 分、读者改变和干货含量都不是 0 分就推荐，每条引用原文。
- **Stephen**：在审核页点要或不要，原因点标签。没点的默认算不要。

关键词不参与排序，也不参与判断。只有一票否决用到少量固定词（已写主题、屏蔽作者、登录墙提示语等）。

一批的流程：分轮抓取（含每批必跑的 X 渠道） → 读全文前查重 → 读全文打分 → 组装到 `topics/<批次ID>/` → 发布前检查 → 生成审核页 → 导入审核结果。

## 反馈和评测

审核结果存在本机 `.local/editorial_feedback.jsonl`，不上传。新反馈先按 [反馈学习规则](references/feedback-learning-protocol.md) 归类，单个标题、产品名或作者名不会直接变成禁令。

每次改规则都要用历史审核回放评测，确保 Stephen 选过的文章不会被新规则误伤，见 [评测方法](references/evaluation.md)：

```bash
.venv/bin/python3 scripts/eval_replay.py build     # 冻结一版基准集
.venv/bin/python3 scripts/eval_replay.py machine   # 程序层回放
.venv/bin/python3 scripts/eval_replay.py leak-check   # 规则里不能引用留出集文章
```

真正衡量效果的指标是 Stephen 的采纳率：`scripts/feedback_audit.py` 看历史结果，`scripts/source_yield.py` 看每个来源的采纳情况。

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python3 scripts/channel_check.py --live   # 看今天哪些取材渠道能用
```

本机 Homebrew Python 不允许直接 `pip install`，所以统一用 `.venv`。

离线试跑：

```bash
.venv/bin/python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --output-root .local/work/fixture
```

## 文件地图

给 Agent 读的说明：
- `SKILL.md`：操作手册，每次必读。
- `references/editorial-judgment.md`：六维打分标准。
- `references/editorial-calibration-cases.md`：正反例。
- `references/feedback-learning-protocol.md`：怎么从反馈里学、什么不能学。
- `references/evaluation.md`：评测方法。
- `references/source_discovery_playbook.md`：五层信息源和接新源的流程。
- `references/channels.md`：Exa、GitHub、YouTube、B 站、X、知乎、浏览器等取材渠道怎么用。

给脚本读的配置：
- `resources/editorial_profile.json`：口味档案。目标读者、条数、时效、已写主题、屏蔽名单和一票否决用到的少量词。
- `resources/content_curator_sources.json`：订阅清单，按类别和用途（候选源、线索源）标注；OpenAI（含 Developers）、Anthropic、Claude、Google DeepMind 的官方博客是候选源，只有发布后 5 天内的原文能进候选，过了窗口自动退回线索。
- `resources/source_portfolio.json`：12 类取材渠道和权重，收工检查用。

脚本（按流程）：
- `scrape_aihot.py`：抓取总入口；`skill_version.py`：确认跑批用的是最新 Skill；`curator.py`：一票否决和阅读顺序；`published.py`：对照已发布文章标出同名候选；`buzz.py`：找出最近 3 天在很多来源同时刷屏的新名字，列在标题清单开头。
- `add_source.py`：登记 Agent 手动找到的文章；`history_check.py`：读全文前查重。
- `editorial_judgment.py`：推荐理由格式检查（六维打分、原文引用、正文指纹）。
- `publish_batch.py`：发布前总检查，`--check-only` 只检查不登记；`report.py`：生成审核页。
- `import_feedback.py`：导入审核结果；`feedback_audit.py`：入选率、原因标签统计，找出没给原因或自相矛盾的反馈。
- `discovery_ledger.py`：搜索记录本和收工检查；`channel_check.py`：渠道能不能用。
- `eval_replay.py`：历史回放评测；`quality_audit.py`：仓库结构检查，只说明文件齐不齐，不代表选题好不好。
- `format_captions.py`、`local_transcribe.py`：整理字幕、本机离线转写。

私有目录（不提交）：`.local/`（反馈、评测、搜索记录、缓存、工作文件）、`topics/`（每批审核页）、`.config/`（密钥）。

## 隐私与浏览器

API Key、Cookie、登录态、审核反馈和完整候选正文都不进公开仓库。需要浏览器时只用隔离浏览器的独立任务空间，不操作 Stephen 的 Chrome。

## 验证

```bash
.venv/bin/python3 -m unittest discover -s tests -v
.venv/bin/python3 scripts/eval_replay.py machine
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
.venv/bin/python3 scripts/quality_audit.py
git diff --check
```
