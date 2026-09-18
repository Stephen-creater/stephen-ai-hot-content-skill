# 高质量选题扩源清单

当合格材料不足本批目标数量时，按下面顺序持续扩源，直到满足 `SKILL.md` 的完成契约或 stop-check 停止条件。扩源的目标是找到更多高质量材料，不是降低门槛。

## 先量化覆盖，不凭感觉扩源

`resources/source_portfolio.json` 把求解空间分成 12 个来源族并按预期价值加权。每周运行一次覆盖检查，并在扩源前查看台账：

```bash
.venv/bin/python3 scripts/source_coverage.py --verified-channel exa_search --verified-channel github --write-snapshot .local/source_coverage.json
.venv/bin/python3 scripts/discovery_ledger.py report
```

`verified-channel` 只能填写本轮已经完成非空冒烟测试的渠道。Doctor 的 `warn`、工具安装成功或配置文件存在都不能算真实连通。

每次检索后按 `SKILL.md`「记账」一条的命令记录实际产出，额外可加 `--evidence-url` 留下已读取的搜索结果页。

一周滚动窗口内应覆盖至少 80 分来源族；真实连通能力应达到至少 85 分。覆盖不足时从最高权重缺口开始补，不能用低权重 GitHub 搜索代替公众号、X、播客或中文长文。

权重是待校准的规划假设，不代表互联网内容份额。每个来源族分别验证 search、read、author；只计有时间、非空结果和证据 URL 的操作。Doctor 和命令安装不加分，连通测试使用 purpose=smoke，不计实际选题探索覆盖。最终入选数只能在用户审核后填写，不能由 Agent 代填。

## 分层来源模型

五个来源层描述「从哪里取材、按什么顺序取」；`source_portfolio.json` 的 12 个来源族用于覆盖率记账和停止条件判断。一个层可以对应多个族，例如访谈公众号记在 `wechat`，播客转录记在 `chinese_podcasts`。

历史入选材料集中在少数「访谈与编译号、精选站、一线博主」，资讯媒体几乎不出货；不少入选访谈的上游是英文播客或演讲，中文稿是编译或整理。因此按作者和栏目订阅，不再扩综合媒体。具体地址与说明以 `content_curator_sources.json` 为准。

### 第一层：中文精选主入口

- BestBlogs（`type: bestblogs`）：官方公开 RSS 带 category、minScore、featured、type、timeFilter 参数；资源接口返回原文 URL、来源、评分和正文。评分和摘要由它的 AI 生成，只决定先读什么；交付前回核原文。
- 觉醒AI（`type: paged_web`）：遍历文章库分页，用页面 datePublished 判定时效；旧 X 帖子重新导入时，还要按正文提到的模型版本核对。
- 宝玉：官方 feed 只有摘要，抓取时回原页取全文。

### 第二层：访谈与文字稿公众号

公众号源在配置里按 `rss_group` 分组：组内共用 `defaults`（全文、优先级、噪音排除），单个号只写名称、地址和与默认不同的字段；单号的 `title_exclude_pattern` 追加在组规则之后，不会覆盖组规则。

- 访谈与文字稿组：语言即世界（张小珺）、Web3天空之城、Founder Park、十字路口、海外独角兽、晚点AI、晚点再听、深思圈、乱翻书、产品犬舍、AI炼金术、有新Newin、42章经；2026-09 新增非凡产研、极客公园（公众号全文），以及 B 级的 Z Potentials、随机小分队、硅谷101、爱范儿、APPSO、智能涌现、硅星人Pro、51CTO技术栈。
- 一线实践与方法组：花叔、一泽Eze、范冰、刘言飞语、AI产品黄叔、歸藏、刘小排；新增阿真Irene、小互AI、卡尔的AI沃茨、佳芮的创业笔记、艾逗笔、言午、强少来了，以及 B 级的 AI产品阿颖、沃垠AI、向阳乔木推荐看、山行AI、土猛的员外、MacTalk、夕小瑶科技说、AI前线、AI科技大本营、王建硕、飞哥说AI、二一的笔记、Memm设计知识分享、产品二姐、caoz的梦呓、李继刚、HelloSREAgent。
- 大厂技术团队 Agent 实践组：京东、携程、腾讯云开发者、百度Geek说、字节、阿里、腾讯技术工程、大淘宝、dbaplus、InfoQ、Qunar技术沙龙、有赞coder、哔哩哔哩技术、转转技术、高可用架构。这些号大多写底层基建，组规则用 `title_include_pattern` 只收 Agent 落地、AI Coding、评测方法类标题。
- 人人都是产品经理：历史审核 5/36 入选，以普通 RSS 接入并回原页取全文。
- 公众号作战室索引（`type: wechat_index`）作为补充，只保留访谈、实录、复盘和长期实测标题。
- 按号判断价值，不按平台：同一个号的访谈可能入选，活动报名和资讯不入选，已用标题排除过滤。

### 第三层：播客变文字稿

按顺序取材，前一步拿到就停：

1. 官方或编辑过的中文文字版（公众号全文、节目方发布的文字稿）。
2. BestBlogs 播客转录：按说话人合并成段落；专名可能错，说话人只有编号，交付前补主持人/嘉宾标签并校对专名。
3. 本地转写 `scripts/local_transcribe.py`：离线零费用，但没有标点、专名错误多，只在前两步都没有时使用。

没有可读文字稿的音频只作线索。

中文播客访谈线索组（discovery）：硅谷101、硅谷早知道、张小珺商业访谈录、十字路口、晚点聊、42章经、二分电台、AI炼金术、What's Next 科技早知道、开始连接 LinkStart、硅基立场、卫诗婕漫谈、此话当真、AI Odyssey、跨国串门儿计划，以及 B 级的牛油果烤面包、津津乐道、剩余价值、三五环、GGV 创业者访谈、乱翻书、屠龙之术、AI每周谈、科技乱炖、硬地骇客、Web Worker。小宇宙节目用公共 RSSHub 的 `/xiaoyuzhou/podcast/<ID>` 订阅，RSS 带约 1500 字节目介绍和音频地址。

### 第四层：英文一手雷达（discovery，不进候选）

- follow-builders：X 上 Claude Code、Codex 等团队一线作者的推文。
- Anthropic Engineering、OpenAI Developers、Cursor 的 RSS 镜像；The Pragmatic Engineer、Latent Space、Lenny、Simon Willison、Hamel Husain、Addy Osmani、Jason Liu、Every AI & I、Training Data、YC Lightcone。红杉 Training Data 与 Latent Space 带免费英文逐字稿，可用来核对中文编译稿是否忠实，但英文稿本身不进候选。
- 2026-09 新增：Ben's Bites、Dwarkesh Patel、Stratechery、LukeW、NN/g、Evil Martians。
- X 一线作者雷达组：xgo.ing 生成的公开 RSS（只能用已有地址，新建要登录）。Karpathy、Simon Willison、Mike Krieger、Harrison Chase、Jerry Liu，以及 B 级的歸藏、orange.ai、Tw93、Viking、Amjad Masad、Varun Mohan、Andrew Ng、Philipp Schmid、Martin Fowler、Akshay Kothari、Sahil Lavingia、a16z。
- YouTube 一线实操雷达组：How I AI、AI Engineer、Riley Brown、Matt Pocock。YouTube 官方频道 feed 对这些频道返回 404，统一走 RSSHub `/youtube/channel/<频道ID>`；命中后用 yt-dlp 取字幕。
- 中文一线短内容线索组：即刻用户（RSSHub `/jike/user/<ID>`）歸藏、AI产品黄叔、卡尔的AI沃茨、橘AI、一泽、花叔、李继刚、空格.space、Kenny、艾逗笔、甲木未来派、Indie-Fox、Barret李靖；Telegram 频道 DPS Build、冰器库、Laisky's Notes。短帖只作线索，命中后找作者长文或访谈。
- 雷达命中后依次找中文成熟稿：宝玉、Web3天空之城、瓜哥AI新知、Z Finance、海外独角兽、BestBlogs 关键词 feed。都没有就说明中文材料缺位，标记为高研究成本，交给用户判断是否原创。

### 第五层：独立博客低频池

`独立博客低频池` 分组：向阳乔木、最小可读、Tw93、唐巧、Joway、wklken、Sagasu、XINDOO、明立非、谢乾坤、创见思考、imlee-tech；2026-09 新增罗磊、bmpi、电波障害、枫言枫语，以及 B 级的 manateelazycat、范叶亮、懒程序员改变世界、Limboy、Reorx、编码记录、蚊BloG、Yubolun、重归混沌、Design Scenes、张可。更新慢但多为一线复盘，非 AI 文章由资格门槛过滤。

### 公共 RSSHub 实例

`rsshub.bestblogs.dev` 为主，`rsshub.imlg.co` 为备（配置里写 `mirror_hosts`，主实例失败时按同一路径切换）；`rsshub.app` 官方实例返回 403。实测可用路由：小宇宙播客、YouTube 频道与用户、即刻用户、Telegram 频道、掘金、少数派、知乎热榜。B 站用户、知乎个人、X、小红书路由需要 Cookie，公共实例返回 503 或超时。知乎专栏可用 `rss.lilydjwg.me/zhihuzhuanlan/<专栏>`，但知乎历史审核 2/43，暂不接入。

### 不再接入

- 以资讯为主：36氪、虎嗅、少数派、IT之家、Solidot、Readhub、机器之心、新智元。
- 需要 Cookie 或已不可用：公共 RSSHub 的知乎和 X 路由、nitter/xcancel、搜狗微信、feeddd、wewe-rss。
- 已停更：OnBoard!、AI局内人、海外独角兽播客。
- 2026-09 RSS 合集中确认失效：xyzfm 托管的播客地址全部超时；一批 `.cn` 个人博客证书过期（curl 同样失败）。
- 各层仍用 `discovery_ledger.py` 记账；连续多轮全文通过率为 0 的来源降为 discovery，不凭印象增删。

## 接入新源的流程

用户提供 OPML 或订阅清单时，按实测数据和逐源评级接入，不整包导入：

1. 解析并去掉已接入的地址，丢弃只属于生活、理财、前端、移动端、后端和运维分类的源。
2. 低并发探测（wechat2rss 在高并发下会超时）：记录是否可用、近 45 天篇数、AI 相关篇数、正文不少于 2500 字的篇数。近 45 天 AI 全文少于 2 篇的源不进入评审。
3. 按近 45 天标题逐源评级，依据是编辑判断模型和 `source_yield.py` 列出的真实入选、否决样例。A 级（至少 3 篇像会入选的）按组默认值接入；B 级（1 到 2 篇）用 priority 3，items_limit 低于组默认值；C 级只作线索或不接；X 级不接。
4. 排除规则只写可以反复出现的噪音栏目或事件类型，例如早报、报名、大会、招聘；不要拿某一篇具体标题里的字眼当规则，否则以后的好文章会被误伤。标题党和炒作用语放进编辑画像的 `hype_or_gossip_terms`，对所有来源统一生效。
5. 用 `--pool 40` 试抓一轮，比较新旧来源各占多少待终审名额，并逐条看新来源带进来的噪音；噪音集中在某一类标题时，回到第 4 步补规则。


## 搜索组合

围绕以下结构交叉搜索，而不是只搜“AI 热点”：

- `AI Agent + 一个月/半年/一年 + 复盘/失败/踩坑`
- `Claude Code/Codex + 正式项目 + commits/测试/交付`
- `AI + 学习/记忆/认知/创造力 + 实证研究`
- `Agent + 真实工作流 + 数字/成本/成功率/留存`
- `AI + 组织变化 + 岗位/流程/协作 + 案例`
- `访谈/播客/逐字稿 + 核心团队 + 具体问题`

## 持续搜索循环

1. 优先复用已验证的常规来源和非浏览器后端；浏览器、OpenCLI 与知乎例外按 [Agent Reach 路由](agent-reach-discovery.md) 执行。
2. 运行常规来源与本地 inbox。
3. 合格候选不足目标数量时，先组合 Exa、公开文章索引、中文 RSS、网页检索与 B站/YouTube 字幕；仍有材料缺口时，知乎可用“CLI 适配器契约 + Ego 登录态”做搜索、作者追踪和全文核验，其他确需交互的原文再按需用 Ego 补查。Twitter、Reddit、V2EX 与 GitHub 只负责发现线索。
4. 从尚未覆盖的层级选择至少两个渠道继续搜索，不得只重复同一组网页关键词。
5. GitHub 只负责局部补充，每批最多 1 条；文章、博客、公众号或完整音视频材料至少要有 4 条。
6. 找到线索后先读取完整正文、字幕或逐字稿，确认没有登录墙、关注墙和正文截断，再写入 `.local/source_inbox.json`。
7. 重新抓取、硬门槛筛选和历史去重。
8. 人工检查所有候选，拦截提问帖、通稿、SEO 内容、AI 模板文、标题党、泛泛观点和过深实现细节。
9. 仍不足目标数量，或非 GitHub 高质量材料不足 4 条，则回到第 3 步，直到满足 `SKILL.md` 的完成契约或停止条件；满足停止条件时交付缺口报告，不用弱题补位。

最终候选仍必须同时满足：材料完整、切口具体、有事实或案例、能形成因果链、对普通读者有价值，并具有长期回看意义。
