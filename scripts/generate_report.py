import os
import datetime

def create_report():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    base_dir = os.path.join(os.getcwd(), "topics", f"{today}_Topic_Report")
    os.makedirs(base_dir, exist_ok=True)
    
    topics = [
        {
            "id": 1,
            "title": "Skild AI: 机器人通用大脑的 140 亿豪赌",
            "titles": [
                "估值140亿美金！Skild AI打造机器人通用大脑，软银贝佐斯疯抢",
                "机器人界的GPT时刻？Skild AI如何用一个模型控制所有机器人",
                "只要能动就能控：Skild AI 获14亿美元融资，通往物理世界AGI的关键一步"
            ],
            "content": "Skild AI 完成14亿美元C轮融资，估值达140亿美元。由软银领投，英伟达、贝佐斯跟投。核心产品是'Skild Brain'，一种'全形态'（omni-bodied）基础模型，能控制任何形态的机器人（人型、四足、机械臂等）。它通过学习互联网视频和模拟数据训练，克服了机器人数据匮乏的难题，旨在成为物理AI领域的'皮卡丘'（通吃）。",
            "why": "这是一个巨大的技术突破承诺（通用机器人大脑），融资额巨大，大佬云集，代表了AI从数字世界走向物理世界的关键趋势（Physical AI）。",
            "structure": "钩子（140亿估值/贝佐斯入局） -> 问题（机器人太笨/专用性强/数据少） -> 解决方案（Skild Brain/通用模型/视频训练） -> 收获（物理AI的未来/AGI拼图）。",
            "raw_notes": """# Skild AI 深度研究笔记

## 核心事实
- **融资**: Series C, $1.4 Billion (14亿美元)。
- **估值**: > $14 Billion (140亿美元)。
- **投资方**: SoftBank (领投), NVentures (NVIDIA), Jeff Bezos, Macquarie Capital, Sequoia, etc.
- **CEO**: Deepak Pathak (CMU教授背景)。
- **总部**: Pittsburgh, PA。

## 核心技术：Skild Brain
- **概念**: "Omni-bodied" foundation model (全形态基础模型)。
- **能力**: 
    - 可以控制任何形态的机器人：四足 (quadrupeds), 人形 (humanoids), 机械臂 (manipulators), 轮式 (mobile)。
    - "If there is a machine that can move, the omni-bodied Skild Brain will operate it."
    - 零样本适应 (Zero-shot adaptation)：适应不同环境、不同身体结构，甚至肢体损坏、轮胎被卡等突发情况。
- **训练方法**:
    - **数据痛点**: 机器人领域缺乏像互联网文本那样的大规模数据集 ("no internet of robotics")。
    - **解决方案**: 
        1. **Internet Videos**: 学习数十亿人类行为视频，理解物体物理属性和操作逻辑。
        2. **Simulation**: 在物理模拟中进行大量试错训练。
- **类比**: 就像 GPT 是语言的基础模型，Skild Brain 是物理控制的基础模型。

## 商业化与应用
- **目标**: 成为机器人的"通用大脑"，类似于 Windows/Android 之于电脑/手机。
- **应用场景**: 家庭服务 (做家务、拿东西), 工业制造, 仓储物流, 恶劣环境作业。
- **现状**: 机器人硬件成本在下降，但软件（智能）是瓶颈。Skild AI 试图解决这一瓶颈。

## 观点与评价
- **SoftBank**: Masayoshi Son 认为这是通向 AGI 的关键一步（Physical AI）。
- **行业影响**: 可能会终结目前机器人领域"从头造轮子"（为每个机器人单独写控制算法）的时代。
- **挑战**: 模拟到现实（Sim2Real）的差距，以及通用模型在特定任务上的精度问题。

## 参考链接
- https://www.skild.ai/blogs/series-c
- https://techcrunch.com/2026/01/14/robotic-software-maker-skild-ai-hits-14b-valuation/
"""
        },
        {
            "id": 2,
            "title": "美联航数字化转型：传统企业的科技翻身仗",
            "titles": [
                "传统企业如何数字化转型？美联航CEO：把技术写进基因里",
                "为什么美联航的App比互联网公司做的还好？Scott Kirby的科技长期主义",
                "不卷价格卷体验：美联航靠技术翻身的启示"
            ],
            "content": "Stratechery 专访美联航 CEO Scott Kirby。他通过重建技术栈彻底改造了这家老牌航司。美联航的 App 被公认为行业最佳（甚至好于第三方 App Flighty）。Kirby 认为技术不仅是工具，更是建立情感连接、提供差异化服务的核心。这是一个传统行业通过'硬核技术投入'实现逆袭的经典案例。",
            "why": "对所有非科技行业的'数字化转型'极具参考价值。打破了'传统企业做不好软件'的刻板印象。",
            "structure": "钩子（最烂航司变最好？） -> 核心（CEO的科技背景/重写代码） -> 案例（App体验/延误透明化） -> 总结（长期主义投入/差异化竞争）。",
            "raw_notes": """# 美联航 (United Airlines) 数字化转型笔记

## 来源
- Stratechery Interview with Scott Kirby (Jan 2026).

## 核心人物：Scott Kirby
- **背景**: 曾任职五角大楼，有科技行业背景，并非典型航空高管。
- **理念**: 坚信技术是差异化的核心驱动力。

## 转型关键点
1.  **重建技术栈 (Tech Stack Rebuild)**:
    - 没有在旧系统上修修补补，而是从底层重建。
    - 允许实现实时数据流，而非批处理。
2.  **App 体验**:
    - **评价**: 被第三方应用 Flighty 的创始人评价为"遥遥领先" (by far the best)。
    - **功能**: 
        - **Live Activities**: 实时登机口、倒计时。
        - **透明化**: 当航班延误时，通过 App 告诉乘客 *真实原因* (比如"机组超时"、"天气原因")，而不是含糊其辞。
        - **自助服务**: 改签、赔偿直接在 App 完成，无需排队。
3.  **差异化竞争**:
    - 过去航司只卷价格 (Commodity)。
    - 现在通过技术提供更好体验 (Product Differentiation)。
    - 例子：Starlink WiFi 合作，机上高速上网。

## 商业逻辑
- **信任**: 通过透明化建立信任。即使延误，告诉乘客真相能降低焦虑。
- **效率**: 技术不仅服务乘客，也优化了内部运营（排班、维护）。
- **长期主义**: 技术投入初期看不见回报，需要 CEO 坚定支持。

## 金句
- "We fight battles from the high ground." (我们从高地作战——指不卷低价，卷价值)。
- "Technology is the only way to progress generally."

## 启示
- 即使是百年传统行业，核心竞争力也可以是软件。
- 数字化转型一把手工程的重要性。
"""
        },
        {
            "id": 3,
            "title": "Flock Safety Nova：当监控摄像头学会人肉搜索",
            "titles": [
                "你的车牌正在出卖你：Flock Safety 如何打造全美监控网",
                "无需搜查令！AI监控'Nova'让隐私无处遁形",
                "当摄像头学会'人肉搜索'：404 Media 揭秘 Flock 的监控帝国"
            ],
            "content": "404 Media 曝光 Flock Safety 正在开发名为'Nova'的产品，结合车牌识别（LPR）、数据经纪商数据和泄露数据，实现从'车牌'到'个人'的直接关联。这意味着警方无需搜查令即可追踪特定人的行踪及社交关系。此外，其系统存在严重安全漏洞，甚至被用于错误的移民执法（ICE）。",
            "why": "极具争议性，触及大众对隐私的敏感神经。AI 技术被用于监控的负面典型，引发对'技术向善'的反思。",
            "structure": "钩子（开车出门就被盯上？） -> 揭秘（Nova系统/数据关联） -> 危害（无需搜查令/错误识别） -> 反思（安全与隐私的边界）。",
            "raw_notes": """# Flock Safety & Nova 监控争议笔记

## 来源
- 404 Media Investigation (Jan 2026).

## 核心事件
- **Flock Safety**: 美国最大的车牌识别 (ALPR) 公司，覆盖5000+社区。
- **新产品 Nova**:
    - **功能**: "Jump from LPR to person" (从车牌跳转到人)。
    - **数据源**: 结合 LPR 数据 + 数据经纪商 (Data Brokers) + 信用局数据 + 甚至黑客泄露数据 (Breached Data)。
    - **能力**: 只要有车牌，就能查到车主姓名、住址、关联人、社交网络。
    - **图谱**: 建立"关联图谱"，如果你经常和某人一起开车，或者车停在一起，系统会判定你们有关系。

## 争议点
1.  **无需搜查令 (Warrantless)**: 警方可以随意查询，无需法院批准。
2.  **大规模监控 (Mass Surveillance)**: 不仅仅是抓罪犯，而是对所有人的行踪进行记录。
3.  **错误识别 (Misidentification)**: 
    - ICE 使用相关应用 (如 "Elite") 曾错误识别目标，导致无辜者被骚扰。
    - 算法并非 100% 准确，但警方往往盲信。
4.  **安全漏洞**:
    - 404 Media 发现 Flock 的摄像头曾暴露在公网上，任何人都能看直播。
    - 审计日志 (Audit Logs) 被故意模糊，公众无法监督警方到底查了谁。

## 影响
- **移民执法**: ICE 利用地方警局的 Flock 网络抓捕非法移民（通过"Side door"访问）。
- **堕胎追踪**: 担心该技术被用于追踪去外州堕胎的女性。
- **反噬**: 华盛顿州等立法机构开始考虑立法限制 ALPR 数据的使用和保存期限。

## 思考
- AI 让监控成本几乎为零。
- 隐私在便利和安全面前的溃败。
"""
        },
        {
            "id": 4,
            "title": "AI 能源危机：OpenAI 与软银的 10 亿美元基建战",
            "titles": [
                "AI 的尽头是能源：OpenAI 联手软银 10 亿美元押注电力",
                "为了喂饱 GPT-6，Sam Altman 开始造发电厂了",
                "算力不够，电力来凑：Stargate 计划背后的能源野心"
            ],
            "content": "OpenAI 和软银各出资 5 亿美元投资 SB Energy，用于建设为 AI 数据中心供电的基础设施。这是 5000 亿美元 'Stargate' 计划的一部分。AI 发展面临的最大瓶颈已从芯片转向电力。Meta 也在搞核电。",
            "why": "揭示了 AI 发展的硬约束（物理世界资源）。不仅是科技新闻，更是能源/基建新闻。",
            "structure": "钩子（AI抢电） -> 事件（10亿投资/Stargate） -> 背景（数据中心能耗/电网压力） -> 未来（科技巨头变身能源巨头）。",
            "raw_notes": """# OpenAI & SoftBank Energy 投资笔记

## 核心事实
- **投资**: OpenAI 和 SoftBank Group 各投 $500 Million (合计 $1 Billion) 给 SB Energy。
- **SB Energy**: 软银旗下的能源公司，原主营可再生能源（太阳能），现转型做数据中心 + 能源一体化开发。
- **Stargate 计划**: OpenAI 提出的 $500 Billion (5000亿) 基础设施计划，旨在建立巨型数据中心集群。
- **项目**: 德克萨斯州 (Milam County) 的 1.2 GW 数据中心项目。
    - 1 GW (吉瓦) = 10亿瓦。足够供电 75万个家庭。
    - 单个数据中心达到这个规模是前所未有的。

## 背景：AI 的能源墙
- **算力需求**: AI 模型越大，训练和推理越费电。
- **瓶颈转移**: 以前缺 GPU (Nvidia)，现在缺 Power (电力)。
- **竞争格局**:
    - **Amazon**: 买核电站 (Talen Energy)。
    - **Microsoft**: 重启三里岛核电站。
    - **Google**: 投资地热能和核聚变。
    - **Meta**: 签署核电协议。
    - **OpenAI**: 此次投资 SB Energy。

## 意义
- **Vertical Integration**: AI 公司开始涉足最底层的物理基础设施。
- **国家竞争力**: "Secure America's AI future"。能源保障成为 AI 霸权的前提。
- **绿色与现实**: 虽然名为 Green Energy，但为了赶进度，可能会混合使用天然气等化石能源。

## 关键词
- Stargate (星际之门计划)
- Gigawatt scale (吉瓦级)
- Infrastructure constraint (基建约束)
"""
        },
        {
            "id": 5,
            "title": "Stratechery 周报：Vision Pro 的尴尬与媒体的黄昏",
            "titles": [
                "苹果 Vision Pro 遇冷，传统媒体大乱斗：本周科技圈盘点",
                "Stratechery 观察：Vision Pro 的内容困境与媒体的黄昏",
                "当科技不再'神奇'：从 Vision Pro 到传统媒体的挣扎"
            ],
            "content": "Stratechery 本周综述。重点提及 Apple Vision Pro 内容匮乏（虽然看 NBA 体验还行但整体失望），以及传统媒体（CBS News）在数字化转型中的混乱与挣扎。",
            "why": "提供了对 Apple 空间计算现状的冷思考，以及对媒体行业的观察。",
            "structure": "钩子（Vision Pro 吃灰了吗？） -> Apple 困境（有硬件没内容） -> 媒体困境（旧瓶装新酒的失败） -> 观点（技术应服务于体验）。",
            "raw_notes": """# Stratechery Technology Doings 笔记

## 来源
- Stratechery Weekly Update (Jan 2026).

## 关键话题
1.  **Apple Vision Pro**:
    - **体验**: Ben Thompson 观看了 NBA 直播（沉浸式）。
    - **评价**: "Incredibly disappointing" (极度失望)。
    - **原因**: 内容太少，体验虽好但不足以支撑设备的高价和佩戴的不适。它是"Dream content" but "Disappointing experience"。
    - **启示**: 硬件再好，没有生态和杀手级内容也是徒劳。
2.  **Legacy Media (传统媒体)**:
    - **CBS News**: Bari Weiss 试图重塑 CBS News 引发混乱。
    - **观点**: 传统媒体试图通过"明星化"或"政治化"来自救，但忽视了媒介本身的变化（互联网分发 vs 电视广播）。
    - **对比**: 像 United 这样拥抱技术的公司赢了，像 CBS 这样还在旧模式里挣扎的输了。

## 综合思考
- 技术是放大器。
- 对于 Apple，技术（显示技术）已经很强，但应用场景（内容）没跟上。
- 对于 Media，技术（分发渠道）变了，但组织结构没变。
"""
        }
    ]

    # Write Report.md
    report_path = os.path.join(base_dir, "Report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 自媒体热门选题深度研究报告\n\n")
        f.write(f"**日期**: {today}\n")
        f.write("**生成**: Hot Content Curator Skill\n\n")
        
        f.write("## 选题排名\n\n")
        
        for topic in topics:
            f.write(f"### {topic['id']}. {topic['title']}\n")
            f.write(f"**标题创意**:\n")
            for t in topic['titles']:
                f.write(f"- {t}\n")
            f.write(f"\n**核心内容**: {topic['content']}\n\n")
            f.write(f"**推荐理由**: {topic['why']}\n\n")
            f.write(f"**写作伪代码**: {topic['structure']}\n\n")
            f.write(f"**原始资料**: [点击查看](./topic_{topic['id']}_notes.md)\n\n")
            f.write("---\n\n")
            
    # Write Note Files
    for topic in topics:
        note_path = os.path.join(base_dir, f"topic_{topic['id']}_notes.md")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(topic['raw_notes'])
            
    print(f"Report and notes generated at: {base_dir}")

if __name__ == "__main__":
    create_report()
