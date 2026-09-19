---
name: stephen-ai-hot-content-skill
description: "按 Stephen 的编辑标准找 AI 选题：读全文终审后发布一批候选，导入 Stephen 的审核反馈，维护信息源，并用历史审核回放评测规则改动。用户说给我选题、找 AI 选题热点、审核或导入选题反馈、优化选题信息源时使用。不写文章正文，不做每日 AI 资讯简报或求职等其他领域的信息整理。"
---

# Stephen AI 热点选题

这个 Skill 帮 Stephen 找能改写成文章的 AI 中文好材料。脚本负责抓取、一票否决和去重；Agent 自己看全部合格材料的标题和开头挑出要读的，读完全文按六个维度打分并引用原文；Stephen 在审核页拍板。关键词不参与排序，也不参与判断。文章正文交给 `stephen-writing-skill`，每日资讯简报不归这里管。

## 环境

在仓库根目录执行，所有命令用虚拟环境里的解释器：

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python3 -m unittest discover -s tests   # 依赖齐全才会通过
```

并发 worktree 里没有 `.venv`、`.local`、`topics`、`.config`：解释器用 `"$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/python3"`，后三个目录软链接到仓库主目录。缺这些目录时不要抓取、发布或导入，否则历史去重和反馈会失效。

## 交付规则

- **条数**：用户说了要几条就按用户的，没说就是 10 条。只交通过终审的；够不上就继续找，不降标准凑数。
- **构成**：不限文章、播客、GitHub 的比例。GitHub 项目必须附一篇中文文章解读，并写清中文用户能不能用、配置和付费成本、安全检查，发布脚本会检查。
- **轮次**：第 1 轮是完整抓取。第 2 轮起按缺口换渠道、换作者、换查询词去找；找到的原文用 `add_source.py` 登记，再带 `--round <n>` 重跑抓取（缓存会让没变的来源秒回）。读完这一轮再开下一轮。
- **记账**：抓取带 `--batch <批次ID> --round <轮次>` 会自动记账。手动搜索用 `.venv/bin/python3 scripts/discovery_ledger.py record --batch <批次ID> --owner 主力 --family <渠道类别> --channel <渠道> --query <查询> --status success --operation search --round <轮次> --result-count <结果数> --eligible-key <原文链接>`；没权限或没工具的渠道记 `--status blocked --failure-type <原因>`，结果数为 0。
- **什么时候可以停**：以 `.venv/bin/python3 scripts/discovery_ledger.py stop-check --batch <批次ID>` 的 `should_stop` 为准。它要求：权重不低于 8 的候选渠道类别都搜过或记为搜不了（不能全都搜不了）；至少两轮；最近两轮至少用了 2 个常规抓取以外、有结果的渠道；最近两轮没找到新的合格材料。另外，连续 3 轮终审一条没过，也停下交缺口报告。
- **停下以后**：有几条通过就发布几条，报告里写清缺口；一条都没有就只交缺口报告。用户暂停、取消或遇到真实权限问题时立即停。
- **批次与进度文件**：批次 ID 形如 `2026-09-19-main-a`。每轮抓取输出到 `.local/work/<批次ID>/<时间戳>/`。通过终审的条目按原文链接去重，组装成 `topics/<批次ID>/candidates.json`（抓取字段加 `manual_editorial_review`）和 `run.json`（至少含 `batch_id`、`requested_count`、`candidate_count`）。进度文件 `.local/work/<批次ID>/checkpoint.json` 至少写 `batch`、`owner`、`target_count`、`round`、`passed`（id、link、source_sha256）、`rejected_links`、`next_step`，中断后照它续跑。

## 读哪些文件

每批开始读 [编辑判断标准](references/editorial-judgment.md)。导入反馈或改判断规则时读 [反馈学习规则](references/feedback-learning-protocol.md) 和 [评测方法](references/evaluation.md)。

按需读：
- 边界拿不准：[正反例](references/editorial-calibration-cases.md)
- 扩源或调整来源：[信息源清单](references/source_discovery_playbook.md)
- 用 Exa、GitHub、YouTube、B 站、X、知乎、浏览器等渠道补材料：[取材渠道手册](references/channels.md)

`resources/editorial_profile.json`（口味档案）和 `resources/content_curator_sources.json`（订阅清单）主要给脚本读，改画像、改来源或查误判时再打开。

## 流程

### 1. 接上之前的状态

- 反馈原文很大，不直接读。用 `feedback_audit.py` 看入选率、原因标签统计和没给原因的记录，读进度文件续跑，不靠对话记忆。
- 读本机私有的 `.local/articles/published_topics.md`：Stephen 已经写成文章的全部选题。写过的主题不再推荐（除非有实质新进展）；同一主题已经写了两篇以上的（例如 FDE 写了 4 篇），换个案例、换个说法也算重复，类型和写法以它为参照。有新文章时先跑 `.venv/bin/python3 scripts/sync_articles.py` 从飞书只读同步。
- 先读哪些来源，参考 `.venv/bin/python3 scripts/source_yield.py --min-decided 5`：键是公众号名或网站域名，审核不足 5 次的来源不参与排序。
- **读全文之前**把待读材料存成 JSON 数组，运行 `.venv/bin/python3 scripts/history_check.py <文件>` 查重。同一篇访谈常被不同站点换标题转载，链接不同但正文重合。
- 相似主题只有新事实、新方法或新结果才算新材料。

### 2. 抓取与找原文

- 运行 `.venv/bin/python3 scripts/scrape_aihot.py --batch <批次ID> --round <轮次> --output-root .local/work/<批次ID>`。输出里的 `triage.md` 列出全部合格材料（已过一票否决和查重）的标题、来源、日期、字数和开头，按来源优先级和新鲜度排列；全文在 `eligible.json`。**先通读 `triage.md` 全部标题，自己挑出值得读全文的**，一般是目标条数的 3 倍左右（默认 10 条选题读约 30 篇）。`candidates.json` 只是按顺序截的前 30 篇，不代表推荐。缓存 1 小时（文章页 7 天，英文源 1 天），`--no-cache` 强制刷新。
- 重大发布是 Stephen 写得最多的一类，他常直接拿英文官方原文写当天解读。所以 OpenAI（含 Developers）、Anthropic、Claude、Google DeepMind 的官方博客是候选源：发布后 5 天内的原文直接进 `triage.md` 并排在前面，超过 5 天自动退回线索。官方博客里客户案例、合作、公益和政策稿占多数，这些不推荐；值得读的是三类：新模型、新产品、新功能的正式发布，厂商自己团队的一手做法和内部数据，头部实验室首次展示的新能力方向。X 上的官方发布帖或官方文档页用 `add_source.py <链接> --platform web --language en --official-release --content-file <正文>` 登记。有中文首发报道或实测时，两篇都可以读，推荐讲得更清楚的那篇。
- 其余线索源（播客、YouTube、X、即刻、GitHub Changelog）只进 `discovery.md`。
- 按原始发布时间从新到旧读。转载、网页更新、重新上榜都不改变文章的真实年龄。
- 登录、关注、验证码或付费后才能看到的正文直接放弃；代理或缓存抓到的隐藏文字不算公开。
- 机器转录要合并段落、校正专名、标出说话人，不能把字幕墙交给用户。
- 单个来源失败写进 `run.json`，继续其他来源。不能把网络、登录或解析失败说成“没有好材料”。
- 开始扩源前先跑 `channel_check.py --live`，看今天哪些渠道能用。

### 3. 一票否决

只有客观事实可以一票否决，命中就不再往下看：

- 不是 AI 相关、不是简体中文、正文不完整或打不开、正文太短（画像的 `minimum_article_chars`）；
- 已写过、已审过、已被另一个窗口认领；
- 即时新闻超过 5 天，深度材料超过画像的时间窗；
- GitHub 项目实时 Star 少于 100，或近 7 天没有实质更新；
- 屏蔽的来源、作者或已写主题；
- 文章自己说明由 AI 生成；关键内容在缺失的图片里。

### 4. 判断只来自读全文

程序不做任何“好不好”的判断：没有关键词打分，也没有关键词提示。挑稿看标题清单，推荐看读完全文后的六维打分。

### 5. 六维终审

先看原文标题，分成三类：明显不对、值得读、看不出来。标题好只决定先读，不决定通过。原页面标题存 `source_title`，自拟切口存 `editorial_angle`；不能用改标题掩盖原文的题材和受众。

读完全文，六个维度各打 0、1、2 分（2 分：明显做到，有正文证据；1 分：部分做到或有明显短板；0 分：基本没做到）。判定标准见 [编辑判断标准](references/editorial-judgment.md)，打分前先对照 [正反例](references/editorial-calibration-cases.md) 开头“Stephen 选过什么”。

**前五维（除改写成本外）总分至少 6 分（满分 10），且“读者改变”“干货含量”都不是 0 分，就推荐。** 击中大部分要求就够。改写成本照样打分写给 Stephen 看，不参与门槛。整篇明显由 AI 写、关键内容靠大量截图或视频画面、主体是实验室安全风险，这三种读完确认后不推荐。待读材料多时，按来源拆给子 Agent 并行读全文、起草打分和原文引用，主 Agent 逐条复核后再放行。

每条推荐写入 `manual_editorial_review`。字段缺失、只有空泛好评或没有原文证据的，不能发布：

```json
{
  "status": "passed",
  "scores": {"topic_appeal": 2, "reader_change": 2, "material_increment": 2, "re_authorability": 1, "durability": 1, "rewrite_effort": 2},
  "topic_appeal": "为什么目标读者会关心，引用正文事实",
  "reader_change": "读完具体会改变什么：之前怎么做，之后怎么做",
  "material_increment": "原文独有的新事实、方法或取舍",
  "re_authorability": "去掉作者身份、截图和公司后，论证是否还成立",
  "durability": "热度过去后为什么还有人看",
  "rewrite_effort": "离能发还有多远：沿用结构只换语气，还是要重组或重写",
  "counterargument": "最大疑点",
  "decision_driver": "最终放行的关键证据",
  "source_sha256": "当前完整正文的 SHA-256",
  "source_anchors": [{"dimension": "material_increment", "quote": "正文原句"}, {"dimension": "re_authorability", "quote": "正文原句"}]
}
```

程序只检查打分、字段和原句是否存在，不能证明判断正确。原句必须真的支撑推荐理由。正文变了要重审。

### 6. 发布

```bash
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力 --check-only   # 只检查不登记
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

并行任务用 `--owner 主力2`。发布脚本在文件锁下复核理由、认领和跨窗口去重，失败就剔掉那条，不绕过脚本。抓取脚本的 `--include-rejected` 只用于调试。

审核卡写给没看过过程的人：原文讲了什么、为什么值得看、可以怎么写、改写成本多高。不展示内部代码、去重术语或分数。

### 7. 导入反馈

审核页的用法：只点想要的那几条，原因点标签，标签说不清时再写一句；导出时没点的默认记为“不要”。

先核对批次 ID、认领、候选 ID、标题、链接和顺序，再导入：

```bash
.venv/bin/python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
```

导入成功并回读后才删除下载的 JSON，失败就保留。按钮决定结果，原因标签和备注决定能学什么。冲突、含义不清时按 [反馈学习规则](references/feedback-learning-protocol.md) 处理，不要猜。

### 8. 改判断规则之前和之后都要跑评测

改口味档案、一票否决、打分或终审标准时，按 [评测方法](references/evaluation.md) 用历史审核回放：

```bash
.venv/bin/python3 scripts/eval_replay.py build     # 有新反馈时冻结一版新基准
.venv/bin/python3 scripts/eval_replay.py machine   # 你选中过的文章不能被拦下
.venv/bin/python3 scripts/eval_replay.py leak-check   # 规则里不能引用留出集文章
```

`machine` 或 `leak-check` 报错时不能提交。改终审标准时，还要用盲评集让子 Agent 重新判断，再用 `eval_replay.py score` 对照结论。

## 交付时怎么回复

选题批次：
1. 批次 ID、审核页路径、条数与构成；
2. 与审核页同序的列表：原题、原文链接、一句话推荐理由、改写成本；
3. 没抓成或没覆盖的来源、剩余风险（如原文可读性待回核、转录专名待校对）；
4. 没达到目标条数时附缺口报告：stop-check 的停止依据、各来源读了几篇和通过几篇、有英文线索但没有中文材料的题目，以及三个选项：继续扩源、换方向、调整数量。

维护任务：改了哪些文件、测试和评测结果、推送回读结果、剩余风险。

## 边界

- 不写文章正文；选题确认后交给 `stephen-writing-skill`。
- 不提交 `.local/`、`.config/`、`topics/`、反馈、密钥、Cookie 或登录态。
- 浏览器只用隔离的任务空间，不启动或接管 Stephen 的 Chrome，不导出 Cookie，不替他登录。何时用、怎么限频见 [取材渠道手册](references/channels.md)。
- 只有用户明确要求时才开多个窗口并行。并行时各认领不重叠的来源，工作文件分开放；同一批次由认领它的窗口发布和导入反馈。
- 阅读顺序 `reading_order` 只看来源优先级、新鲜度和有没有全文，Agent 还要自己通读全部标题。
- 单批反馈不能把读者兴趣、题材偏好、技术难度或改写难度变成一票否决。只有语言、公开完整、时效、写过或审过的精确记录、来源安全、GitHub 可核验门槛这类事实可以一票否决。

## 修改后的验证

```bash
.venv/bin/python3 -m unittest discover -s tests -v
.venv/bin/python3 scripts/eval_replay.py machine
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
.venv/bin/python3 scripts/quality_audit.py
git diff --check
```

只提交这次相关的文件，推送 `origin/main`，回读确认本地 `HEAD`、`origin/main` 与远程 `main` 一致。禁止 force push。
