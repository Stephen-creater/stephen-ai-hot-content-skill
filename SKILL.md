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

- **条数**：每天一批，最多 10 条（口味档案 `default_topic_count`），**能过几条交几条，不凑数**。2026-09-23 Stephen 定的：按现在的标准，全网一天能过的中文稿大约 2 到 4 条（实验见评测方法的“信息源实验”），为凑 10 条连扩六七轮只会把标准磨松。用户说了要几条，按用户的。
- **构成**：不限文章、播客、GitHub 的比例。GitHub 项目必须附一篇中文文章解读，并写清中文用户能不能用、配置和付费成本、安全检查，发布脚本会检查。
- **轮次**：一般两轮。第 1 轮完整抓取，已经包括 X 中文作者巡检（`x_sweep.py`）、觉醒AI 最近两天的全部清单和各精选站，读完合格池里值得读的。第 2 轮只补两件事：当天多源刷屏的名字还没有中文好稿的，去 X、公众号、53AI 搜；X 首页时间线看一遍。找到的原文用 `add_source.py` 登记，再带 `--round 2` 重跑抓取。只有当天有重大发布、两轮后还没有中文实测时，才开第 3 轮专门找它。
- **记账**：抓取带 `--batch <批次ID> --round <轮次>` 会自动记账。手动搜索用 `.venv/bin/python3 scripts/discovery_ledger.py record --batch <批次ID> --owner 主力 --family <渠道类别> --channel <渠道> --query <查询> --status success --operation search --round <轮次> --result-count <结果数> --eligible-key <原文链接>`；没权限或没工具的渠道记 `--status blocked --failure-type <原因>`，结果数为 0。
- **什么时候可以停**：两轮读完就停，发布通过的。`discovery_ledger.py stop-check --batch <批次ID>` 用来确认高权重渠道都跑过了，没跑到的在缺口说明里写一句。
- **停下以后**：有几条通过就发布几条，附一段三五行的缺口说明；一条都没有就只交这段说明。用户暂停、取消或遇到真实权限问题时立即停。
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

- **开工第一件事**：`git pull --ff-only origin main`，用最新的 Skill 跑。抓取脚本会自己对一次远程，落后时打印警告并继续；发布脚本直接拒绝发布用旧版跑出来的批次（确实断网时才用 `--allow-stale`）。每次抓取把当时的 commit 记进 `run.json` 的 `skill_commit`。2026-09-20 有一批用旧版规则跑完才发现，整批作废。
- 反馈原文很大，不直接读。用 `feedback_audit.py` 看入选率、原因标签统计和没给原因的记录，读进度文件续跑，不靠对话记忆。
- 读本机私有的 `.local/articles/published_topics.md`：Stephen 已经写成文章的全部选题。写过的主题不再推荐（除非有实质新进展）；抓取时会机械对照这份清单，标出同名候选，见下面的“机器标记”；同一主题已经写了两篇以上的（例如 FDE 写了 4 篇），换个案例、换个说法也算重复，类型和写法以它为参照。有新文章时先跑 `.venv/bin/python3 scripts/sync_articles.py` 从飞书只读同步。
- 先读哪些来源，参考 `.venv/bin/python3 scripts/source_yield.py --min-decided 5`：键是公众号名或网站域名，审核不足 5 次的来源不参与排序。
- **读全文之前**把待读材料存成 JSON 数组，运行 `.venv/bin/python3 scripts/history_check.py <文件>` 查重。同一篇访谈常被不同站点换标题转载，链接不同但正文重合。
- 相似主题只有新事实、新方法或新结果才算新材料。

### 2. 抓取与找原文

- 运行 `.venv/bin/python3 scripts/scrape_aihot.py --batch <批次ID> --round <轮次> --output-root .local/work/<批次ID>`。输出里的 `triage.md` 列出全部合格材料（已过一票否决和查重）的标题、来源、日期、字数和开头，按来源优先级和新鲜度排列；全文在 `eligible.json`。`triage.md` 开头的“最近 3 天多源刷屏”列出几天内在很多来源同时冒出来的新名字，这是单篇文章看不出的热度，先看它：每个刷屏的名字至少挑一篇最完整的稿子读全文；中文稿都不好时，用 `add_source.py` 登记中文 X 长帖或官网原文。然后**通读 `triage.md` 全部标题，自己挑出值得读全文的**，一般是目标条数的 3 倍左右（默认 10 条选题读约 30 篇）。`candidates.json` 只是按顺序截的前 30 篇，不代表推荐。缓存 1 小时（文章页 7 天，英文源 1 天），`--no-cache` 强制刷新。
- 重大发布是 Stephen 写得最多的一类。OpenAI（含 Developers）、Anthropic、Claude、Google DeepMind 的官方博客是候选源，发布后 5 天内的原文直接进 `triage.md` 并排在前面；其他英文正文抓取脚本直接否决（Grok 4.7、阶跃 Step 5 的英文官方稿都标“改写成本高”），这类发布去找中文稿。只重排官方分数和价格的短帖、快讯算通稿。
- **每批必跑 X**：Stephen 很多文章是在 X 上看到并二创的，这个渠道和公众号同等重要。用 ego-browser 打开他登录的 X，看首页时间线、翻重点作者主页、搜当天的关键词；长帖用 `add_source.py <链接> --platform x --creator "<作者>" --content-file <正文文件>` 登记成候选，重跑抓取走资格判定。做法见 [取材渠道手册](references/channels.md) 的“X（推特）”。交付时写明从 X 找到几条、搜了哪些词。订阅里那两个 X 源只覆盖 25 个固定账号，是补充，不能替代这一步。
- **每个订阅源都抓正文**，都按同一套标准判定；三家官方博客以外的英文源只能当线索（英文正文会被否决）。订阅覆盖不到的（浏览器里看到的长帖、别人给的链接）用 `harvest_leads.py` 补正文登记进 inbox，再带 `--inbox .local/source_inbox.json` 重跑。`scripts/source_audit.py --problems` 定期体检：每个源实际抓几条，报出取到几条、有正文几条、合格几条、卡在哪，不出货的当场修或去掉。
- 抓不到正文的自动走 ego-browser 兜底（微信、知乎只对真实浏览器放行）。正文是验证页的判成“站点返回验证页”，不再报成“正文偏短”；`run.json` 记 `blocked_by_site_count` 和 `browser_rescued_count`。X 短推按点赞数排序，纯链接和纯回复不显示。
- 按原始发布时间从新到旧读。转载、网页更新、重新上榜都不改变文章的真实年龄。
- **播客要有逐字稿才算数**：BestBlogs 覆盖的约三十档自带转录，没覆盖的用 `scripts/transcribe_podcasts.py <抓取输出目录> --limit 2` 本机转写（约 27 倍速，一期 154 分钟约 8 分钟），转完自动登记进 inbox。登录、关注、验证码或付费才能看的正文直接放弃；机器转录要校正专名、标出说话人，不能把字幕墙交给用户。
- 单个来源失败写进 `run.json`，继续其他来源。不能把网络、登录或解析失败说成“没有好材料”。
- 开始扩源前先跑 `channel_check.py --live`，看今天哪些渠道能用。

### 3. 一票否决

只有客观事实可以一票否决，命中就不再往下看：

- 不是 AI 相关、不是简体中文、正文不完整或打不开、正文太短（画像的 `minimum_article_chars`）；
- 已写过、已审过、已被另一个窗口认领；
- 即时新闻超过 5 天，深度材料超过画像的时间窗；
- GitHub 项目实时 Star 少于 100，或近 7 天没有实质更新；
- 屏蔽的来源、作者或已写主题；付费墙站点（画像 `paywalled_domains`，Wired 一篇 Stephen 说“要充钱才可以看”）；
- 文章自己说明由 AI 生成；关键内容在缺失的图片里。

### 4. 判断只来自读全文

程序不做任何“好不好”的判断：没有关键词打分，也没有关键词提示。挑稿看标题清单，推荐看读完全文后逐题回答的是 / 否题。

### 5. 终审：13 道是 / 否题

先看原文标题，分成三类：明显不对、值得读、看不出来。标题好只决定先读，不决定通过。原页面标题存 `source_title`，自拟切口存 `editorial_angle`；不能用改标题掩盖原文的题材和受众。

读完全文，逐题回答 `resources/review_questions.json` 里的 13 道题，每题只能答 yes、no 或 unsure，写一句为什么。**任何一题答到否决的那个答案，或者答 unsure，就不推荐；13 题全部答对才推荐。**没有总分可以拿来抵。每题怎么判、有哪些例子，见 [编辑判断标准](references/editorial-judgment.md)；答题前先对照 [正反例](references/editorial-calibration-cases.md) 开头“Stephen 选过什么”。待读材料多时，按来源拆给子 Agent 并行读全文、起草答案和原文引用，主 Agent 逐条复核后再放行。

每条推荐写入 `manual_editorial_review`。字段缺失、只有空泛好评或没有原文证据的，不能发布：

```json
{
  "status": "passed",
  "answers": {
    "reader_meets_it": {"answer": "yes", "note": "为什么这样答，写正文里的事实"},
    "reader_takeaway": {"answer": "yes", "note": "读完能做的那件事", "quote": "正文原句"},
    "has_substance": {"answer": "yes", "note": "别处看不到的是什么", "quote": "正文原句"},
    "...": "13 道题每道一条，题号见题目文件"
  },
  "counterargument": "最大疑点",
  "decision_driver": "最终放行的关键证据",
  "source_sha256": "当前完整正文的 SHA-256"
}
```

程序只检查答案、字段和原句是否存在，不能证明判断正确。原句必须真的支撑推荐理由。正文变了要重审。**机器标记**：抓取脚本会自己对照已发布文章和图片数，标出两种情况，`triage.md` 的标题行里能看到，发布脚本会拦：

- 标题和某篇已发布文章同名，或命中它登记的别名（`written_topic_hint`）：要在终审卡里加 `new_progress`，写明这次有什么新进展。2026-09-20 一批 20 条里有 9 条是写过的主题，靠 Agent 自己对照清单没拦住，所以改成机械标记。别名登记在本机私有的 `.local/articles/topic_aliases.json`（文章标题对应一组别名），Stephen 说某条“写过了”而标题对不上时，就把那个说法登记成别名；读稿时仍要自己认题，机器只按字面对。
- 配图 7 张及以上（`many_images`）或嵌了视频（`has_video`）：要在终审卡里加 `image_plan`，写明二创时这些图和视频怎么办。图只是展示界面、文字讲得清的，写清楚就能过（9 张界面图的 ChatGPT 进 Word 被选中过）。10 张及以上、或 2 段及以上视频，抓取时直接一票否决，阈值在口味档案（2026-09-21 b 批三篇正好 10 张的全被拒，写了 image_plan 也没用）。

标记不等于淘汰，但不写这两句就发布不了。宁可标多，也不要放过。另外，终审卡的 `counterargument` 里自己写了“Stephen 写过”，发布脚本同样要求 `new_progress`，而且写的必须是新事实，不是换个人再说一遍；疑点里点名了正反例的某个“不选”类型，那就是不推荐，见判断标准的“判断纪律”。**发布脚本还直接拦这些**：任何一题答到否决答案或答 unsure；疑点里写了“勉强过线”“放行是因为”这类放行说辞。抓取阶段直接否决：正文 5 行以上代码、英文正文（OpenAI、Anthropic、Google 官方发布稿除外）、正文图 10 张以上。**凑不够条数就交缺口报告，不要改写疑点绕过检查。**

### 6. 发布

```bash
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力 --check-only   # 只检查不登记
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

并行任务用 `--owner 主力2`。发布脚本在文件锁下复核理由、认领和跨窗口去重，并把每条链接再打开一次，站点没响应的（2026-09-21 觉醒AI 整站打不开，Stephen 点开一条是“打不开”）拒绝发布：换成能打开的原文链接（转述站的稿子附原始出处）或剔掉那条，不绕过脚本；`--skip-link-check` 只在确实断网时用。抓取脚本的 `--include-rejected` 只用于调试。

审核卡写给没看过过程的人：原文讲了什么、为什么值得看、可以怎么写、改写成本多高。不展示内部代码、去重术语或分数。

### 7. 导入反馈

审核页的用法：只点想要的那几条，原因点按钮，按钮说不清时再写一句；导出时没点的默认记为“不要”。每个原因按钮对应一道或几道是 / 否题。**改任何规则之前先做时间外测试**：用当前规则开两个互不可见的子 Agent 盲判这批（`eval_suite.py export --suite <批次ID>`），导入并 build 后 `eval_replay.py forward record`。这是唯一没见过答案的考试，做法见 [评测方法](references/evaluation.md)。

先核对批次 ID、认领、候选 ID、标题、链接和顺序，再导入：

```bash
.venv/bin/python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
```

导入成功并回读后才删除下载的 JSON，失败就保留。按钮决定结果，原因标签和备注决定能学什么。`feedback_audit.py` 的 `batch_level` 是北极星：每批通过几条、多少批至少通过一条。每天一批、能过几条交几条，标准不降。冲突、含义不清时按 [反馈学习规则](references/feedback-learning-protocol.md) 处理，不要猜。

### 8. 改判断规则之前和之后都要跑评测

改口味档案、脚本检查、是 / 否题、正反例或终审标准时，按 [评测方法](references/evaluation.md) 走：Stephen 每条带理由的拒稿先对应到题目（`eval_suite.py unmapped`、`map-reasons`），改完用现在的规则重跑回归测试集和负向用例，再过上线前检查：

```bash
.venv/bin/python3 scripts/eval_replay.py build        # 有新反馈时冻结一版新基准
.venv/bin/python3 scripts/eval_replay.py machine      # 你选中过的文章不能被脚本拦下
.venv/bin/python3 scripts/eval_replay.py leak-check   # 规则里不能引用验证集、测试集文章
.venv/bin/python3 scripts/eval_suite.py gate          # 回归测试集至少 95% 判对且写成文章的全对，负向用例一条不推
```

任何一条报错都不能提交；`gate` 已经装成 git 提交前自动运行（`sh scripts/hooks/install.sh`）。`eval_suite.py report` 出一页评测报告。

## 交付时怎么回复

选题批次：
1. 批次 ID、审核页路径、条数与构成；
2. 与审核页同序的列表：原题、原文链接、一句话推荐理由、改写成本；
3. 没抓成或没覆盖的来源、剩余风险（如原文可读性待回核、转录专名待校对）；
4. 缺口说明，三五行就够：合格池多少条、读了多少、通过几条；今天刷屏的事里哪件没找到能用的中文稿；哪个源抓取出了故障。不列选项清单。

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
