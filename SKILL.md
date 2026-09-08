---
name: stephen-ai-hot-content-skill
description: 按 Stephen 的历史文章与人工审核反馈，持续发现、全文核验并筛选适合日课二创的简体中文 AI 选题。用于寻找新选题、生成候选审核页、导入反馈和迭代编辑判断；不负责撰写文章正文。
---

# Stephen AI 热点选题

本 Skill 是编辑判断系统，不是关键词过滤器。自动程序负责发现、资格检查、风险提示和去重；“值得写、读者有收获、能够独立二创”必须依据完整正文进行人工终审。

## 完成契约

每批只有同时满足以下条件才算完成：

- 至少 5 条未写、未审、未被并发任务占用的新材料。
- 至少 4 条文章型材料，GitHub 最多 1 条；仓库只是补充，不能成为主体。
- 每条均通过机器资格检查和证据化人工终审。
- 已用 `publish_batch.py` 完成归属登记、跨任务去重和审核页重建。
- 回复中的原文链接与 HTML 卡片数量、标题、URL、顺序完全一致。

不足时继续扩源、全文读取与筛选。单轮 0 条是正常中间状态，不得降标、拿线索凑数或要求用户再次催“继续”。用户主动暂停、取消或真实权限阻塞除外。长任务在 `.local/work/` 维护一个可续跑检查点。

## 必读与按需加载

每批开始必须读取：

1. [编辑判断模型](references/editorial-judgment.md)
2. [反馈学习协议](references/feedback-learning-protocol.md)
3. [编辑画像配置](resources/editorial_profile.json)
4. [来源配置](resources/content_curator_sources.json)
5. [加权来源组合](resources/source_portfolio.json)

边界难判时读取 [正反校准案例](references/editorial-calibration-cases.md)。扩源时读取 [来源发现清单](resources/source_discovery_playbook.md)。多平台检索读取 [Agent Reach 路由](references/agent-reach-discovery.md)。使用朱雀时读取 [朱雀说明](references/zhuque-aigc.md)。

## 决策流水线

### 1. 继承状态

- 读取 `.local/editorial_feedback.jsonl`、已交付批次和当前任务检查点。
- 按 URL、候选 ID、主题族和正文去重。
- 主力与主力2只处理自己的批次；不得按下载时间猜反馈归属。

### 2. 发现与全文恢复

- 默认优先中文作者已经整理、解释和判断过的完整材料。
- 英文官方资料用于事实核验，不直接占候选名额。
- 聚合页、社区、X、Reddit、GitHub 先作为线索；回到完整简体中文正文、字幕或逐字稿后才能成为候选。
- 视频或播客没有逐字稿时只保留为线索。逐字稿须去时间码、恢复标点和段落，不能把字幕墙交给用户。
- 检查原始公开页面。登录、关注、验证码或付费后才能看到剩余正文时直接淘汰；代理或缓存抓到隐藏文字不算公开完整。
- 单个来源抓取失败时记录到 `run.json` 并继续其他来源；不得把网络、鉴权或解析失败误报为“没有好材料”。所有可用路径都失败且需要新授权时，才作为真实阻塞说明。
- 每次搜索必须用 `discovery_ledger.py` 记录来源族、渠道、查询、结果数、全文数、合格数和最终入选数。安装但未实测、配置但本周未使用，都不算覆盖。
- 每周运行 `source_coverage.py`。覆盖率按高价值来源族权重计算：真实连通目标至少 85%，近 7 天实际探索目标至少 80%；未达标时优先补覆盖缺口，不得继续重复同一批网页关键词。

### 3. 资格门槛

资格问题是可确定事实，未通过即停止评估：

- AI 相关、简体中文、完整材料、来源可访问。
- 未写、未审、未被另一任务交付或预占。
- 即时事件不超过 5 天；普通深度材料遵守画像时间窗。
- GitHub 实时不少于 100 Star，且最近 7 天有与候选价值相关的实质更新。
- 不属于明确屏蔽来源、作者或精确主题状态。

### 4. 五维人工终审

按顺序回答，不能用后项优点补救前项失败：

1. **选题吸引力**：问题、产品或矛盾本身是否值得目标读者关心？无趣产品不能靠负面批评变成好题。
2. **读者改变**：读者看完会改变哪个行动、方法或重要判断？“了解趋势”“获得启发”不算。
3. **材料增量**：原文是否提供新的事实、机制、失败、因果链或有条件的取舍？篇幅、数字、权威身份和案例数量不等于增量。
4. **二创独立性**：去掉作者身份、私人截图、企业数据和品牌素材后，能否依据公共事实与可迁移逻辑重新建立论证？
5. **长期价值**：即时性消失后是否仍值得阅读？若只靠新闻刺激，必须在即时窗口内处理。

每条通过项必须写入 `manual_editorial_review`：

```json
{
  "status": "passed",
  "topic_appeal": "为什么目标读者会关心，引用正文事实",
  "reader_change": "读者看完具体会改变什么",
  "material_increment": "原文独有的新事实、机制或取舍",
  "re_authorability": "不依赖作者专属资产仍能成立的论证",
  "durability": "为什么过了热点期仍有价值",
  "counterargument": "最强淘汰理由",
  "decision_driver": "最终放行所依据的决定性证据"
}
```

缺任一字段、只写抽象赞美、没有正文证据，均不得发布。

### 5. 风险信号的使用方式

AI 味、新闻腔、宣传、第一人称、技术词、宏观词、图片多、QA、访谈、论文或垂直行业只是调查信号，不是类别禁令。必须继续问它是否造成了实质缺陷：

- 信息密度是否被模板结构取代？
- 读者是否必须掌握专业背景才能理解主线？
- 论证是否依赖私人素材或单一公司环境？
- 作者是否只有翻译、拼接和转述，没有自己的判断？
- 产品与问题是否缺乏真实需求和吸引力？

不要因为命中一个词直接淘汰，也不要另拟漂亮切口替原材料补价值。边界判断使用成对案例校准。

### 6. 报告、发布与反馈

运行：

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/scrape_aihot.py
python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

另一任务使用 `--owner 主力2`。正常报告不得包含资格不合格项；`--include-rejected` 只用于调试。

用户审核后，先核对批次 ID、归属、候选 ID、标题、链接及顺序，再导入：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
```

导入成功并回读后才删除下载 JSON；失败必须保留。按钮状态决定当前候选结果，备注负责学习原因。按钮与备注冲突、只有空备注否决或含义不清时，按 [反馈学习协议](references/feedback-learning-protocol.md) 处理，禁止猜测。

优化判断前先运行 `python3 scripts/feedback_audit.py`，确认反馈批次、数量、空备注、重复候选和待解释冲突均被覆盖。审计只输出安全摘要，不自动把备注变成规则。

## 运行边界

- 不撰写文章正文；选题确认后交给 `stephen-writing-skill`。
- 不提交 `.local/`、`.config/`、`topics/`、反馈、密钥、Cookie 或登录态。
- 本项目不调用 OpenCLI，避免接管用户 Chrome；动态或登录页面使用 Ego Browser 隔离空间。
- Ego Browser 的现成登录态是正式检索途径。CLI 缺凭据时先实测站内搜索与正文，不得直接要求导出 Cookie 或购买接口；按操作记录成功与失败。
- 朱雀和模型复排都是辅助证据。未配置或失败表示未知，不能证明文章由人创作。
- 自动分数名为 `discovery_score`，只负责发现排序。最终发布必须通过证据化人工终审。
- 单批反馈不得把读者兴趣、题材偏好、技术难度、行业价值或二创难度升级为客观硬失败。它们只能成为风险信号或待验证假设；只有语言、公开完整性、时效、精确历史状态、来源安全和可核验平台门槛等事实可以硬拦截。

## 修改后的验证

```bash
.venv/bin/python3 -m unittest discover -s tests -v
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check
```

修改后只提交本次相关文件，推送 `origin/main`，并回读确认本地 `HEAD`、`origin/main` 与远程 `main` 一致。禁止 force push。
