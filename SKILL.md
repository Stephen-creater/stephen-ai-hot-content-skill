---
name: stephen-ai-hot-content-skill
description: "按 Stephen 的编辑标准发现、全文终审并发布 AI 选题候选批次，导入选题审核反馈，维护选题信息源；用户说给我选题、找 AI 选题热点、审核或导入选题反馈、优化选题信息源时使用。不写文章正文，不做每日 AI 资讯简报或求职等其他领域的信息整理。"
---

# Stephen AI 热点选题

本 Skill 是编辑判断系统，不是关键词过滤器。程序负责发现、资格检查、风险提示和去重；“值得写、读者有收获、能独立二创”必须读完整正文后人工终审。文章正文交给 `stephen-writing-skill`；每日资讯简报不属于本 Skill。

## 环境与依赖

在权威仓库根目录执行；所有命令都用虚拟环境里的解释器，系统 `python3` 不保证装有依赖：

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python3 -m unittest discover -s tests   # 冒烟：依赖齐全才会通过
```

并发 worktree 没有 `.venv`、`.local`、`topics`、`.config`：解释器用 `"$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/python3"`，并把后三个目录软链接到权威仓库。缺少这些私有目录时，不得运行抓取、发布或导入，否则历史去重和反馈会失效。

## 完成契约与停止条件

目标数量：用户指定数量（如 20 条）时以用户为准，否则 5 条；发布门槛始终是至少 5 条，用户要的少于 5 条时，先按清单交付，不登记发布。每条都必须未写、未审、未被另一任务预占，并通过机器资格检查和证据化人工终审；整批至少 4 条非 GitHub 材料（文章、播客或视频逐字稿），GitHub 最多 1 条。GitHub 候选需额外附中文文章解读、本地化、配置成本与安全审查，由发布脚本检查。

数量不足时继续扩源、读全文、筛选；单轮 0 条是正常中间状态。**不得降标、拿线索凑数，也不得让用户反复催“继续”。**

- **轮与合格**：一轮 = 一次抓取加随后的补充检索，终审完这一轮的材料再开下一轮。台账里的「合格」按机器资格门槛（有全文且资格通过）计，人工记录用同一口径。
- **记账**：抓取带 `--batch <批次ID> --round <轮次>` 自动记账。人工检索用 `.venv/bin/python3 scripts/discovery_ledger.py record --batch <批次ID> --owner 主力 --family <来源族> --channel <渠道> --query <查询> --status success --operation search --round <轮次> --result-count <结果数> --eligible-key <原文链接>`；没有授权或后端的来源族记 `--status blocked --failure-type <原因>`，数量为 0。
- **停止**：以 `.venv/bin/python3 scripts/discovery_ledger.py stop-check --batch <批次ID>` 的 `should_stop` 为准。它要求：候选且权重 ≥8 的来源族都检索过或记为 blocked，且不能全部 blocked；至少两轮；最近两轮至少有 2 个常规抓取以外、有结果的渠道；最近两轮没有此前未出现的合格材料（按链接跨轮去重）。
- **兜底**：连续 3 轮人工终审通过数为 0 时，即使 stop-check 未满足也停下，交付缺口报告，由用户决定是否继续。
- **停止后**：达标 ≥5 条照常发布，并在报告里说明缺口；不足 5 条不发布，报告已达标条目。用户暂停、取消或遇到真实权限阻塞时立即停下。
- **批次与检查点**：批次 ID 形如 `2026-09-17-main-a`。每轮抓取输出到 `.local/work/<批次ID>/<时间戳>/`。终审通过的条目按原文链接去重后，组装为 `topics/<批次ID>/candidates.json`（抓取字段加 `manual_editorial_review`）和 `run.json`（至少含 `batch_id`、`requested_count`、`candidate_count`）。检查点 `.local/work/<批次ID>/checkpoint.json` 至少包含 `batch`、`owner`、`target_count`、`round`、`passed`（id、link、source_sha256）、`rejected_links`、`next_step`。

## 读取路由

每批开始读取：[编辑判断模型](references/editorial-judgment.md)。导入反馈或修改判断规则时读取 [反馈学习协议](references/feedback-learning-protocol.md)。

按需读取：
- 边界难判：[正反校准案例](references/editorial-calibration-cases.md)
- 扩源或调整来源：[来源发现清单](references/source_discovery_playbook.md)
- 跨平台检索：[Agent Reach 路由](references/agent-reach-discovery.md)
- 知乎：[知乎 CLI 与 Ego 路由](references/zhihu-cli-ego.md)
- 朱雀检测：[朱雀说明](references/zhuque-aigc.md)

`resources/editorial_profile.json` 与 `resources/content_curator_sources.json` 主要供脚本读取，只在修改画像、修改来源或排查误判时打开。

## 决策流水线

### 1. 继承状态

- 反馈原文很大，不直接读：用 `feedback_audit.py`、`editorial_outcomes.py` 看反馈结论，读当前检查点续跑，不靠对话记忆。
- **终审前**把待读材料存成 JSON 数组，运行 `.venv/bin/python3 scripts/history_check.py <文件>` 去重：同一访谈常被不同站点换标题转载，链接不同但正文重合。
- 相似主题只有新增事实、方法或结果才算新材料；换标题、换转载地址不算。

### 2. 发现与全文恢复

- 运行 `.venv/bin/python3 scripts/scrape_aihot.py --batch <批次ID> --round <轮次> --output-root .local/work/<批次ID>`。模型复排默认关闭，`--ai` 才会调用 OpenRouter 并计费；配置朱雀后默认检测并计费，`--no-aigc` 跳过。它每次只输出 `report_candidate_count` 条待终审材料；用户要的数量更多时，从 `discovery.json`、各来源台账和补充检索中继续扩池。来源分层（BestBlogs 与觉醒AI 为主入口，访谈与转录为高命中层，英文一手只作雷达）见来源发现清单。
- 按原始发布时间从新到旧读。转载时间、网页更新时间、列表日期和重新上榜都不刷新内容年龄；交付前重新检查时效。
- 聚合页、社区、X 和英文官方资料只作线索或核验；GitHub 项目只能以附带完整中文解读的形式，作为那至多 1 条补充。补充检索找到的原文必须用 `scripts/add_source.py` 写入 inbox 后重新抓取，由程序做资格检查，禁止手写资格记录。机器转录须合并段落、校正专名、标注说话人，不能把字幕墙交给用户。
- 检查原始公开页面：登录、关注、验证码或付费后才可见的正文直接淘汰；代理或缓存抓到的隐藏文字不算公开完整。
- 单个来源失败写入 `run.json` 并继续其他来源；不得把网络、鉴权或解析失败说成“没有好材料”。
- 每次检索用 `discovery_ledger.py` 记账。`.local/source_coverage.json` 超过 7 天未更新时运行 `source_coverage.py` 检查覆盖缺口。

### 3. 资格门槛

资格是可确定的事实，未通过即停止评估：

- AI 相关、简体中文、完整材料、来源可访问，正文至少 2500 字；
- 未写、未审、未被预占；
- 即时事件不超过 5 天，深度材料遵守画像时间窗；
- GitHub 实时不少于 100 Star，且近 7 天有实质更新；
- 不属于屏蔽来源、屏蔽作者或精确主题状态；
- 文章自己没有披露由 AI 生成；已配置朱雀时，检测 `ai ≥ 98%` 同样硬淘汰（其余区间只作风险提示，见朱雀说明）；
- 关键内容不在缺失的图片里。

### 4. 五维人工终审

先用原文标题三态预筛：明显错位、值得读、信息不足。正向标题只换来全文阅读优先级。原页面标题存入 `source_title`，自拟切口存入 `editorial_angle`；不能用改题掩盖原文题材和受众。

按顺序判断五维：选题吸引力、读者改变、材料增量、二创独立性、长期价值。后项优点不能补救前项失败；“勉强能过”按不通过处理。每维的判定标准见[编辑判断模型](references/editorial-judgment.md)。

每条通过项写入 `manual_editorial_review`，字段缺失、只写抽象赞美或没有正文证据的，一律不得发布：

```json
{
  "status": "passed",
  "topic_appeal": "为什么目标读者会关心，引用正文事实",
  "reader_change": "读者看完具体会改变什么",
  "material_increment": "原文独有的新事实、机制或取舍",
  "re_authorability": "不依赖作者专属资产仍能成立的论证",
  "durability": "为什么过了热点期仍有价值",
  "counterargument": "最强淘汰理由",
  "decision_driver": "最终放行所依据的决定性证据",
  "source_sha256": "当前完整正文的 SHA-256",
  "source_anchors": [{"dimension": "material_increment", "quote": "正文原句"}, {"dimension": "re_authorability", "quote": "正文原句"}]
}
```

程序只验证原句真实存在，不证明解释正确；仍须检查原句能否支撑推荐理由。正文变化后重审。

AI 味、新闻腔、第一人称、技术词、访谈、图片多、垂直行业都只是调查信号。要追问它是否造成了实质缺陷（信息密度、专业门槛、私人素材依赖、只有转述、需求不真实）；不要因为命中一个词就淘汰，也不要另拟漂亮切口替原材料补价值。

### 5. 发布

```bash
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力 --check-only   # 只校验不登记
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

并行任务用 `--owner 主力2`。发布脚本会在共享锁下复核证据、归属、跨任务去重和构成，失败时剔除该条再补，不绕过脚本。正常报告不含资格不合格项；抓取脚本的 `--include-rejected` 只用于调试。

审核卡面向没有过程上下文的人，只讲原文讲了什么、为什么值得看、可以写什么；不展示内部状态码、去重术语或自评分。淘汰、重复和仅供核验的资料不混入审核页。

### 6. 导入反馈

先核对批次 ID、归属、候选 ID、标题、链接及顺序，再导入：

```bash
.venv/bin/python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
```

导入成功并回读后才删除下载的 JSON，失败必须保留。按钮状态决定结果，备注负责学习原因；冲突、空备注或含义不清时按[反馈学习协议](references/feedback-learning-protocol.md)处理，禁止猜测。修改判断规则前先运行 `.venv/bin/python3 scripts/feedback_audit.py`。

## 交付回复格式

选题批次：
1. 批次 ID、审核页路径、条数与构成（文章/播客/GitHub）；
2. 与审核页同序的列表：原题、原文链接、一句话推荐理由；
3. 抓取失败或未覆盖的来源、剩余风险（如原文可读性待回核、转录专名待校对）；
4. 未达目标时附缺口报告：stop-check 的停止依据、各来源全文数和通过数、中文材料缺位的英文线索，以及继续扩源、换方向、调整数量三个选项。

维护任务：改动文件、测试与校验结果、push 回读结果、剩余风险。

## 运行边界

- 不撰写文章正文；选题确认后交给 `stephen-writing-skill`。
- 不提交 `.local/`、`.config/`、`topics/`、反馈、密钥、Cookie 或登录态。
- 默认不调用 OpenCLI；只有知乎扩源可按知乎路由读取适配器的能力契约。不为取得 Cookie 启动或接管用户 Chrome。
- Ego Browser 只在常规来源不足、原文确需浏览器或用户指定时按缺口使用；登录态只用于发现与核验，候选原文必须公开可读，不索取、不导出 Cookie。空间、限频与验证码处理见 [Agent Reach 路由](references/agent-reach-discovery.md)。
- 只有用户明确要求时才开启多任务协作。协作时认领不重叠的来源，工作文件分开放；共同批次由一个归属任务发布并导入反馈，不按下载时间猜反馈归属。
- 朱雀除 `ai ≥ 98%` 硬淘汰外、以及模型复排，都只是辅助证据；未配置或失败表示未知，不能证明由人创作。自动分数 `discovery_score` 只负责排序。
- 单批反馈不得把读者兴趣、题材偏好、技术难度或二创难度升级为硬失败。只有语言、公开完整性、时效、精确历史状态、来源安全和可核验平台门槛这类事实可以硬拦截。

## 修改后的验证

```bash
.venv/bin/python3 -m unittest discover -s tests -v
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
.venv/bin/python3 scripts/quality_audit.py
git diff --check
```

只提交本次相关文件，推送 `origin/main`，并回读确认本地 `HEAD`、`origin/main` 与远程 `main` 一致。禁止 force push。
