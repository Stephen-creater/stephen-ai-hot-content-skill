from __future__ import annotations

import concurrent.futures
import json
import requests
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from add_source import append_source
from curator import canonical_url, deduplicate, rank_candidates, redact_untrusted_secrets, score_item
import import_feedback as feedback_module
from report import generate_report
from scrape_aihot import discovery_digest, render_discovery_markdown, clean_transcript, decode_html, embedded_original_date, fetch_web_index, fetch_wechat_index, fetch_bestblogs, http_get, fetch_follow_builders, fetch_rss, fetch_source, fetch_learnprompt_radar, hydrate, inbox_item, is_historical_content_duplicate, select_report_candidates


class CuratorTest(unittest.TestCase):
    def test_public_community_credentials_are_redacted_before_candidate_storage(self):
        leaked = "试用凭据：sk-" + "A" * 40
        self.assertNotIn("sk-", redact_untrusted_secrets(leaked))
        item = score_item({
            **self.items[0], "title": "AI 社区安全讨论", "summary": "公开帖子",
            "content": leaked + "\n" + ("作者解释公开社区内容需要先脱敏。" * 180),
        }, self.profile, now=self.now)
        self.assertNotIn("sk-", item["content"])
        self.assertIn("[REDACTED_CREDENTIAL]", item["content"])

    def test_covered_topic_is_blocked(self):
        base = {**self.items[0], "published": "2026-09-03", "summary": "",
                "content": "HTTP、GPU 缓存、node_modules、pnpm、包管理缓存与依赖路径。" * 120}
        covered = score_item({**base, "title": "Computer History 使用体验"}, self.profile)
        self.assertIn("主题已写过", covered["penalty"])

    def test_personal_activity_recall_is_not_third_party_surveillance(self):
        base = {**self.items[0], "summary": "", "published": "2026-09-01",
                "content": "Computer History 默认是关闭的，本人主动开启，可以暂停。找回工作状态。" + "完整中文实践与限制说明。" * 300}
        own = score_item({**base, "title": "ChatGPT 能监控电脑了：一次个人工作回忆实测"}, self.profile)
        self.assertNotIn("命中排除词监控", own["penalty"])
        for title in ("AI 监控员工的工作状态", "AI 监控伴侣电脑", "AI 监视他人：监控电脑教程"):
            result = score_item({**base, "title": title}, self.profile)
            self.assertIn("命中排除词监控", result["penalty"])
        no_controls = score_item({**base, "title": "AI 监控电脑工作状态", "content": "Computer History 找回工作状态。" * 300}, self.profile)
        self.assertIn("命中排除词监控", no_controls["penalty"])

    def test_main_141814_feedback_topic_and_freshness_boundaries(self):
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        base = {**self.items[0], "summary": "", "content": "公开来源的完整中文材料。" * 400, "published": "2026-09-01"}
        def check(title, published="2026-09-01", content=None):
            return score_item({**base, "title": title, "published": published, **({"content": content} if content else {})}, self.profile, now=now)
        self.assertIn("主题已写过", check("Anthropic 文本水印机制")['penalty'])
        self.assertIn("主题已写过", check("DHH 复盘 Basecamp 架构")['penalty'])
        self.assertNotIn("主题已写过", check("DHH 谈 AI 搜索架构的新实践")['penalty'])
        self.assertIn("用户当前不认可", check("WorkBuddy 与 Z-Code 协作")['penalty'])
        self.assertNotIn("用户当前不认可", check("Claude 文档阅读实践", content="偶尔提到 Z-Code。" + base['content'])['penalty'])
        self.assertNotIn("事件新闻已超过", check("Claude 新功能上线")['penalty'])
        self.assertIn("事件新闻已超过", check("Claude 新功能上线", "2026-08-31")['penalty'])
        self.assertNotIn("事件新闻已超过", check("访谈：Anthropic 产品负责人谈发布取舍", "2026-08-15")['penalty'])

    def test_disfavored_product_subject_not_incidental_mention(self):
        base = {**self.items[0], "summary": "完整中文实测", "content": "公开工作流程和使用边界。" * 300}
        for title in ("实测扣子桌面端", "Coze Desktop 文件同步实测", "扣子客户端使用介绍"):
            result = score_item({**base, "title": title}, self.profile, now=self.now)
            self.assertFalse(result["recommended"])
            self.assertIn("用户当前不认可该产品", result["penalty"])
        result = score_item({**base, "title": "跨设备文件校对的实践", "content": base["content"] + "之前试过扣子桌面端。"}, self.profile, now=self.now)
        self.assertNotIn("用户当前不认可该产品", result["penalty"])

    def test_main2_184610_retires_node_workflow_platforms_without_blocking_agent_methods(self):
        base = {**self.items[0], "summary": "完整中文实测", "content": "公开任务、失败、回读和验收证据。" * 300}
        for title in (
            "Dify + 飞书搭建 AI 视频审核工作流",
            "n8n 自动化节点实战",
            "Coze Workflow 插件搭建指南",
            "用可视化节点工作流搭建 AI 助手",
        ):
            result = score_item({**base, "title": title}, self.profile, now=self.now)
            self.assertFalse(result["recommended"])
            self.assertIn("传统节点式 Workflow 平台已被用户明确淘汰", result["penalty"])
            self.assertEqual(result["editorial_decision"]["eligibility"]["status"], "failed")
        modern = score_item(
            {
                **base,
                "title": "AI Agent 长任务怎样隔离失败并回读真实结果",
                "content": base["content"] + "团队过去试过 Dify，如今主线是 Agent 的验收与状态回读。",
            },
            self.profile,
            now=self.now,
        )
        self.assertNotIn("传统节点式 Workflow 平台已被用户明确淘汰", modern["penalty"])

    def test_main2_161405_marks_only_the_warp_self_improvement_topic_as_covered(self):
        base = {**self.items[0], "summary": "完整中文实践", "content": "公开反馈、失败案例和验证过程。" * 300}
        for title in (
            "Warp 如何让 Agent 自我进化",
            "Warp 怎样让 Skill 从反馈中持续改进",
        ):
            result = score_item({**base, "title": title}, self.profile, now=self.now)
            self.assertIn("主题已写过", result["penalty"])
            self.assertEqual(result["editorial_decision"]["eligibility"]["status"], "failed")
        reusable_method = score_item(
            {**base, "title": "内容团队怎样让写作 Skill 根据人工反馈改进"},
            self.profile,
            now=self.now,
        )
        self.assertNotIn("主题已写过", reusable_method["penalty"])

    def test_internal_source_tracking_parameters_never_create_a_new_candidate(self):
        plain = "https://example.com/article"
        self.assertEqual(canonical_url(plain), canonical_url(plain + "?from=main2-fulltext"))
        self.assertEqual(canonical_url(plain), canonical_url(plain + "?main2=2"))
        self.assertNotEqual(
            canonical_url("https://example.com/article?newId=1"),
            canonical_url("https://example.com/article?newId=2"),
        )

    def test_radar_preserves_original_source_and_stays_discovery(self):
        source = {"name":"Radar", "category":"aggregate", "priority":4, "type":"learnprompt_radar", "url":"https://news.learnprompt.pro/classic/", "data_url":"https://news.learnprompt.pro/data/latest-24h-all.json"}
        row = {"url":"https://example.com/original", "title":"中文译题", "title_original":"Original English title", "source":"Original author", "first_seen_at":"2026-09-05", "summary":"AI generated summary", "ai_score":1}
        with patch('scrape_aihot.requests.get') as get:
            get.return_value.json.return_value = {"generated_at":"2026-09-05", "items_all":[row, row, {"title":"invalid","url":"javascript:alert(1)"}, None]}
            items = fetch_learnprompt_radar(source, {"request_timeout_seconds":5})
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['title'],'Original English title')
        self.assertEqual(items[0]['source_name'],'Original author')
        self.assertEqual(items[0]['published'],'')
        self.assertEqual(items[0]['language'],'unknown')
        self.assertEqual(items[0]['source_role'],'discovery')
        with patch('scrape_aihot.requests.get') as get:
            self.assertEqual(hydrate(items[0], {}),items[0])
            get.assert_not_called()
        result = score_item({**items[0], "content":"完整中文正文和真实实测方法。"*300,"content_status":"fulltext","language":"zh","maturity":"secondary"}, self.profile, now=self.now)
        self.assertFalse(result['recommended'])
        with patch('scrape_aihot.requests.get') as get:
            get.return_value.json.return_value = {"changed_schema":[]}
            items, error = fetch_source(source, {"request_timeout_seconds":5})
            self.assertEqual(items,[])
            self.assertIn('items_all',error)

    def test_latest_editorial_boundaries_are_enforced(self):
        base = {**self.items[0], "content_status": "fulltext", "content": "这里是完整的中文实践材料，讲清真实问题和可复用的方法。" * 150, "summary": "", "published": "2026-08-24"}
        cases = [
            ({**base, "title": "个人知识库的另一种搭法", "summary": "根据 LLM Wiki 方法整理资料"}, "主题已写过"),
            ({**base, "title": "看完 Karpathy 的分享重做知识库"}, "主题已写过"),
            ({**base, "title": "Ego Lite 浏览器实测：AI 可以不抢窗口了"}, "主题已写过"),
            ({**base, "title": "用WorkBuddy搞定公司日常行政工作"}, "基础应用暂缓"),
            ({**base, "title": "知識管理實作", "content": "這個實作讓讀者學會處理資料，從檔案轉換到實際應用。" * 150}, "繁体中文"),
        ]
        for item, reason in cases:
            result = score_item(item, self.profile, now=self.now)
            self.assertFalse(result['recommended'])
            self.assertIn(reason, result['penalty'])
        simplified = score_item({**base, "title": "一次具体任务的简体中文实测", "content": base['content'] + "引文：這是參考資料。"}, self.profile, now=self.now)
        self.assertNotIn("繁体中文", simplified['penalty'])

    def test_similar_series_titles_require_matching_full_content(self):
        first = {"title": "教你用WorkBuddy搞定公司日常行政工作", "link": "https://example.com/admin", "content_status": "fulltext", "content": "行政公文会议纪要用品领用登记" * 100}
        second = {"title": "教你用WorkBuddy搞定公司日常财务工作", "link": "https://example.com/finance", "content_status": "fulltext", "content": "银行流水发票金额应收应付对账" * 100}
        repost = {**first, "link": "https://example.com/repost"}
        self.assertEqual(len(deduplicate([first, second, repost])), 2)

    def test_short_article_is_blocked_whatever_the_title(self):
        base = {**self.items[0], "content": "公开完整实测，展示办公资料转成可下载文件的工作方法。" * 150, "summary": "AI 真实办公任务实测"}
        short = score_item({**base, "title": "AI实测，谁最快、最准、最便宜？", "content": "只有简短介绍。"}, self.profile, now=self.now)
        self.assertFalse(short["recommended"])
        self.assertIn("文章正文偏短", short["penalty"])

    def test_routine_update_in_summary_is_not_release_news(self):
        base = {**self.items[0], "published": "2026-08-01", "content": "使用公开表格完成日常办公任务，并核对处理前后的数据。" * 150, "summary": "台账更新、文档整理与年度资料维护"}
        article = score_item({**base, "title": "教你用WorkBuddy处理日常办公表格"}, self.profile, now=self.now)
        release = score_item({**base, "title": "腾讯发布办公产品新版"}, self.profile, now=self.now)
        self.assertNotIn("事件新闻已超过时效窗口", article["penalty"])
        self.assertIn("事件新闻已超过时效窗口", release["penalty"])

    def test_editor_undo_is_not_a_stale_product_withdrawal(self):
        base = {
            **self.items[0],
            "published": "2026-08-01",
            "content": "记录智能体与人类的编辑边界，检查差异并保护其他协作者的内容。" * 150,
            "summary": "让用户可以撤回 Agent 的当轮编辑，不误伤人类新写的段落",
        }
        article = score_item({**base, "title": "协同文档 Agent 的可对比与可撤回编辑"}, self.profile, now=self.now)
        renamed = score_item({**base, "title": "智能体修改后如何一键回滚"}, self.profile, now=self.now)
        withdrawal = score_item({**base, "title": "OpenAI 撤回旧模型版本发布"}, self.profile, now=self.now)
        self.assertNotIn("事件新闻已超过时效窗口", article["penalty"])
        self.assertNotIn("事件新闻已超过时效窗口", renamed["penalty"])
        self.assertIn("事件新闻已超过时效窗口", withdrawal["penalty"])

    def test_html_and_reply_links_keep_identical_input_order(self):
        import html
        import re
        candidates = [
            {"id": "z", "title": "后字母但第一张", "link": "https://example.com/watch?v=z", "score": 10},
            {"id": "a", "title": "高分但第二张", "link": "https://example.com/watch?v=a", "score": 99},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "index.html"
            generate_report(candidates, output, "test")
            rendered = output.read_text(encoding="utf-8")
            links = output.with_name("links.md").read_text(encoding="utf-8").splitlines()
            headings = re.findall(r'<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>', rendered)
        self.assertEqual([html.unescape(url) for url, _ in headings], [x["link"] for x in candidates])
        self.assertEqual([html.unescape(title) for _, title in headings], [f'{i}. {x["title"]}' for i, x in enumerate(candidates, 1)])
        self.assertEqual(links, [f'{i}. [{x["title"]}]({x["link"]})' for i, x in enumerate(candidates, 1)])

    def test_distinct_youtube_episodes_survive_deduplication(self):
        first = {"title": "内容工程师如何定义好的模型回复", "link": "https://www.youtube.com/watch?v=first", "content_status": "transcript", "content": "原始字幕"}
        second = {"title": "开放权重与蒸馏的技术边界", "link": "https://www.youtube.com/watch?v=second", "content_status": "transcript", "content": "另一期字幕"}
        same_first = {**first, "link": "https://www.youtube.com/watch?v=first&t=60&utm_source=test"}
        self.assertEqual(len(deduplicate([first, second, same_first])), 2)
        self.assertNotEqual(canonical_url("https://example.com/article?newId=1"), canonical_url("https://example.com/article?newId=2"))

    def test_deep_interview_uses_general_age_window_not_release_news_window(self):
        item = {"title": "Anthropic 专家访谈：模型发布后，如何理解蒸馏能力", "summary": "用公共研究解释模型学习的边界", "content": "模型学习的能力需要区分训练方法和实际证据。" * 200, "published": "2026-08-01", "source_name": "中文访谈", "source_priority": 5, "source_type": "web", "source_role": "candidate", "language": "zh", "maturity": "secondary", "content_form": "article", "content_status": "fulltext", "link": "https://example.com/interview"}
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        interview = score_item(item, self.profile, now=now)
        news = score_item({**item, "title": "Anthropic 发布新模型"}, self.profile, now=now)
        self.assertNotIn("事件新闻已超过时效窗口", interview["penalty"])
        self.assertIn("事件新闻已超过时效窗口", news["penalty"])

    def test_english_original_is_rejected_and_code_heavy_body_too(self):
        item = {"title": "Introducing GPT-6", "summary": "OpenAI releases GPT-6 for ChatGPT and the API.", "content": "GPT-6 is our new model for agentic coding and long tasks. " * 60,
                "published": "2026-09-04", "source_name": "OpenAI News", "source_priority": 5, "source_type": "rss", "source_role": "candidate",
                "language": "en", "maturity": "primary", "content_form": "article", "content_status": "fulltext", "link": "https://openai.com/index/gpt-6", "official_release": True}
        fresh = score_item(item, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        blog = score_item({**item, "official_release": False, "source_name": "Simon Willison"}, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        # 2026-09-22：七条英文候选全被拒，Grok 4.7 官方稿标“改写成本高”。英文只当线索，要找中文整理稿再推。
        # OpenAI 的官方发布稿是例外；xAI 的官方稿和非官方英文长文都否决。
        self.assertEqual(fresh["editorial_decision"]["eligibility"]["status"], "passed", fresh["penalty"])
        self.assertEqual(blog["editorial_decision"]["eligibility"]["status"], "failed")
        self.assertIn("英文原文", str(blog["editorial_decision"]["eligibility"]["failures"]))
        grok = score_item({**item, "link": "https://x.ai/news/grok-4-7", "source_name": "SpaceXAI"}, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        self.assertEqual(grok["editorial_decision"]["eligibility"]["status"], "failed")
        code = "\n".join(["const db = new DatabaseSync(path);", "const rows = db.prepare(sql).all(since);", "console.table(report);", "}", "return rows;", "import fs from 'node:fs';"])
        chinese = {**item, "language": "zh", "official_release": False, "source_name": "掘金", "title": "我删掉了 23 个 Skill",
                   "content": "这是一篇中文复盘，讲作者怎么清理自己的技能库。" * 40}
        self.assertEqual(score_item(chinese, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))["editorial_decision"]["eligibility"]["status"], "passed")
        heavy = score_item({**chinese, "content": chinese["content"] + "\n" + code}, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        self.assertIn("行代码", str(heavy["editorial_decision"]["eligibility"]["failures"]))

    def test_official_site_that_refuses_scripts_is_read_through_web_reader(self):
        item = {"title": "Introducing GPT-6", "link": "https://openai.com/index/gpt-6", "source_role": "candidate", "reader_fallback": True, "content_status": "summary"}
        page = ("Title: Introducing GPT-6\n\nMarkdown Content:\n" + "GPT-6 is our new model. " * 40).encode()
        with patch("scrape_aihot.hydrate_direct", side_effect=lambda row, settings: {**row, "fetch_error": "403"}), \
             patch("scrape_aihot.requests.get", return_value=type("R", (), {"content": page, "status_code": 200, "raise_for_status": lambda self: None})()):
            hydrated = hydrate(item, {"request_timeout_seconds": 10})
        self.assertEqual(hydrated["content_origin"], "web_reader")
        self.assertTrue(hydrated["content"].startswith("GPT-6 is our new model."))
        self.assertNotIn("fetch_error", hydrated)

    def test_manually_registered_official_release_keeps_its_flag(self):
        row = inbox_item({"url": "https://x.com/OpenAI/status/1", "platform": "web", "language": "en", "official_release": True, "title": "GPT-6"}, {})
        self.assertTrue(row["official_release"])
        self.assertEqual(row["language"], "en")

    def test_article_length_gate_is_800_chars(self):
        base = {"title": "我用 Codex 重写了团队的发布脚本", "summary": "一次 AI 编程实践复盘", "published": "2026-09-01", "source_name": "博客",
                "source_priority": 4, "source_type": "rss", "source_role": "candidate", "language": "zh", "maturity": "secondary",
                "content_form": "article", "content_status": "fulltext", "link": "https://example.com/len"}
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        self.assertEqual(self.profile["minimum_article_chars"], 800)
        short = score_item({**base, "content": "甲" * 799}, self.profile, now=now)
        enough = score_item({**base, "content": "甲" * 800}, self.profile, now=now)
        self.assertIn("文章正文偏短", short["penalty"])
        self.assertNotIn("文章正文偏短", enough["penalty"])

    def test_body_lead_stands_in_for_missing_summary_when_judging_ai_subject(self):
        base = {"title": "14 天，110 次上线", "summary": "", "published": "2026-09-01", "source_name": "公众号", "source_priority": 4,
                "source_type": "rss", "source_role": "candidate", "language": "zh", "maturity": "secondary", "content_form": "article",
                "content_status": "fulltext", "link": "https://example.com/a"}
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        ai_body = "这两周我让 Agent 接管了发布流程，模型负责写代码，我负责验收。" + "每次上线前智能体先跑测试，再由我检查上下文。" * 80
        passing_mention = "这两周我们重写了发布流程，顺带一提有同事用 AI 查过资料。" + "每次上线前先跑测试，再人工检查配置。" * 80
        database = "这次把缓存层重写了，模型字段和训练数据表都迁到新集群。" + "上下文切换减少以后，推理查询的延迟下降了一半，缓存命中率也更稳定。" * 80
        self.assertNotIn("标题与摘要缺少明确 AI 对象", score_item({**base, "content": ai_body}, self.profile, now=now)["penalty"])
        self.assertIn("标题与摘要缺少明确 AI 对象", score_item({**base, "content": passing_mention}, self.profile, now=now)["penalty"])
        self.assertIn("标题与摘要缺少明确 AI 对象", score_item({**base, "content": database}, self.profile, now=now)["penalty"])
        # 摘要没提 AI、正文开头提到并且反复出现的，也算 AI 材料：官方博客的摘要常常只写产品名（2026-09-23 GPT-6 Sol 发布稿被误拦）。
        self.assertNotIn("标题与摘要缺少明确 AI 对象", score_item({**base, "summary": "一篇关于团队发布节奏和配置检查的复盘文章，讲清楚怎么把一周一次发布改成一天多次发布的过程与代价，以及中间踩过的坑、团队怎么分工、最后保留下来的检查清单和每次发布前必须确认的三件事情。", "content": ai_body}, self.profile, now=now)["penalty"])
        release = {**base, "title": "Introducing GPT-6 Sol and Luna", "summary": "Two new frontier models that balance capability and cost for everyday work, with lower API prices than the previous generation and new options for developers.", "content": ai_body}
        self.assertNotIn("标题与摘要缺少明确 AI 对象", score_item(release, self.profile, now=now)["penalty"])

    def test_long_founder_interview_is_not_expired_event_news(self):
        item = {"title": "对谈快看创始人：漫画编辑怎样和 AI 一起做分镜", "summary": "创始人讲团队怎样发布 AI 功能并调整流程", "content": "我们先让编辑用 AI 做分镜，再看读者反馈调整流程。" * 120, "published": "2026-08-10", "source_name": "中文访谈", "source_priority": 4, "source_type": "rss", "source_role": "candidate", "language": "zh", "maturity": "secondary", "content_form": "article", "content_status": "fulltext", "link": "https://example.com/founder"}
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        interview = score_item(item, self.profile, now=now)
        short = score_item({**item, "content": "上线了 AI 功能。" * 20}, self.profile, now=now)
        launch = score_item({**item, "title": "专访：快看 AI 创作工具正式上线"}, self.profile, now=now)
        self.assertNotIn("事件新闻已超过时效窗口", interview["penalty"])
        self.assertIn("事件新闻已超过时效窗口", short["penalty"])
        self.assertIn("事件新闻已超过时效窗口", launch["penalty"])

    def test_local_podcast_transcript_keeps_ending_and_renders_in_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "podcast.txt"
            body = "主持人：这是一段完整的对话。\n\n" * 1600 + "嘉宾：最后的限制条件也必须保留。"
            path.write_text(body, encoding="utf-8")
            item = inbox_item({"url": "https://example.com/podcast", "platform": "podcast", "content_file": str(path)}, {})
            self.assertEqual(item["content_status"], "transcript")
            self.assertEqual(item["content"], body)
            item = rank_candidates([item], self.profile)[0]
            self.assertEqual(item["content"], body)
            output = Path(directory) / "index.html"
            generate_report([item], output, "test")
            rendered = output.read_text(encoding="utf-8")
            self.assertIn('class="transcript"', rendered)
            self.assertIn("最后的限制条件也必须保留", rendered)

    def test_browser_article_preserves_full_body_and_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "article.txt"
            body = "真实文章段落。\n\n" * 1000 + "文末限制条件必须保留。"
            path.write_text(body, encoding="utf-8")
            with patch("scrape_aihot.requests.get", side_effect=AssertionError("must not refetch")):
                item = inbox_item({"url": "https://example.com/article", "content_file": str(path)}, {})
                result = hydrate(item, {})
            self.assertEqual(result["content"], body)
            self.assertEqual(result["content_status"], "fulltext")
            self.assertEqual(result["content_form"], "article")

    def setUp(self) -> None:
        self.profile = json.loads((ROOT / "resources" / "editorial_profile.json").read_text())
        self.items = json.loads((ROOT / "tests" / "fixtures" / "sample_items.json").read_text())
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def test_source_inbox_concurrent_appends_remain_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory) / "source_inbox.json"
            rows = [
                {"url": f"https://example.com/{index}", "title": f"source {index}"}
                for index in range(8)
            ]
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(lambda row: append_source(inbox, row), rows))
            saved = json.loads(inbox.read_text(encoding="utf-8"))
            self.assertEqual({row["url"] for row in saved}, {row["url"] for row in rows})

    def test_title_duplicate_prefers_complete_transcript(self) -> None:
        summary = {
            "title": "四个工作 Agent 同题实测：好看的报告不等于可信交付",
            "link": "https://example.com/article",
            "content_status": "summary",
            "content": "简介",
        }
        transcript = {
            **summary,
            "link": "https://youtube.com/watch?v=example",
            "content_status": "transcript",
            "content": "完整逐字稿" * 1000,
        }
        self.assertEqual(deduplicate([summary, transcript]), [transcript])

    def test_vtt_transcript_removes_timestamps_and_repeated_cues(self) -> None:
        raw = """WEBVTT
Kind: captions
Language: zh

00:00:00.000 --> 00:00:01.000
第一句话

00:00:01.000 --> 00:00:02.000
第一句话

00:00:02.000 --> 00:00:03.000
""" + "\n\n".join(
            f"00:00:{index:02d}.000 --> 00:00:{index + 1:02d}.000\n这是第{index}段需要整理的字幕内容它没有标点但应该被自动分句"
            for index in range(2, 14)
        )
        cleaned = clean_transcript(raw)
        self.assertNotIn("-->", cleaned)
        self.assertNotIn("WEBVTT", cleaned)
        self.assertEqual(cleaned.count("第一句话"), 1)
        self.assertIn("\n\n", cleaned)
        self.assertIn("。", cleaned)

    def test_aggregator_uses_original_publication_date_not_refresh_date(self) -> None:
        text = "更新时间：2026-09-04\n原文信息\n发布于 2026 年 7 月 24 日，时长 75 分钟。"
        self.assertEqual(embedded_original_date(text), "2026-07-24")

    def test_wechat_index_keeps_interviews_and_skips_news_flashes(self) -> None:
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        def article(title, account="某科技号", day="20260916"):
            return {"title": title, "account_name": account, "url": f"http://mp.weixin.qq.com/s?t={title}",
                    "article_key": f"{day}#wechat#{title}", "lead": "导语"}

        index = {"articles": [
            article("深度｜对话某产品负责人：为什么要先删功能"),
            article("两个月百余个真实任务后：Codex 不是数字员工"),
            article("【AI 晚报｜9 月 16 日】国产大模型密集迭代"),
            article("对话某公司 CEO：完成亿元融资"),
            article("刚刚，某模型发布"),
            article("深度｜对话优先账号的产品负责人", account="Z Finance", day="20260915"),
            article("优先账号的普通资讯", account="Z Finance"),
            {**article("图文帖子"), "title": "第一段正文\n第二段正文"},
            None,
        ]}
        source = {
            "name": "公众号访谈与实录", "category": "中文产品访谈", "priority": 4, "url": "https://index.example/articles",
            "content_url_template": "https://index.example/articles/{key}", "items_limit": 10,
            "preferred_accounts": ["Z Finance"],
            "title_include_pattern": "^深度｜|对话|(\\d+|两)(天|个月).{0,10}(实测|实践|后)",
            "title_exclude_pattern": "晚报|融资",
        }

        def fake_get(url, **kwargs):
            if url == source["url"]:
                return Response(index)
            if "%E5%88%9A%E5%88%9A" in url:
                raise TimeoutError("cache timeout")
            return Response({"article": {"content": "完整正文" * 800}})

        with patch("scrape_aihot.requests.get", side_effect=fake_get):
            rows = fetch_wechat_index(source, {"request_timeout_seconds": 1, "hydrate_workers": 2})
        titles = [row["title"] for row in rows]
        self.assertEqual(titles[0], "深度｜对话优先账号的产品负责人")
        self.assertEqual(set(titles), {"深度｜对话优先账号的产品负责人", "深度｜对话某产品负责人：为什么要先删功能", "两个月百余个真实任务后：Codex 不是数字员工"})
        self.assertTrue(all(row["link"].startswith("https://") for row in rows))
        self.assertTrue(all(row["content_origin"] == "public_index_cache" and row["content_status"] == "fulltext" for row in rows))
        self.assertEqual(rows[0]["published"], "2026-09-15")
        with patch("scrape_aihot.requests.get") as get:
            self.assertEqual(hydrate(rows[1], {"request_timeout_seconds": 1}), rows[1])
            get.assert_not_called()
        with patch("scrape_aihot.requests.get", return_value=Response({"changed": []})):
            items, error = fetch_source({**source, "type": "wechat_index"}, {"request_timeout_seconds": 1})
        self.assertEqual(items, [])
        self.assertIn("articles", error)

    def test_bestblogs_recovers_original_url_body_and_readable_transcript(self) -> None:
        feed = """<rss><channel><title>BestBlogs</title>
          <item><title>文章</title><link>https://www.bestblogs.dev/article/a1?utm_source=rss</link><description>摘要</description></item>
          <item><title>推文</title><link>https://www.bestblogs.dev/status/123?utm_source=rss</link></item>
          <item><title>播客</title><link>https://www.bestblogs.dev/podcast/p1?utm_source=rss</link></item>
          <item><title>坏条目</title><link>https://www.bestblogs.dev/article/broken</link></item>
        </channel></rss>""".encode("utf-8")
        payloads = {
            "a1": {"data": {"metaData": {"title": "一线复盘", "url": "https://mp.weixin.qq.com/s/abc", "sourceName": "某作者",
                                        "score": 92, "publishTimeStamp": 1789621260000},
                           "contentData": {"displayDocument": "<p>第一段真实经历。</p><script>x()</script><p>" + "第二段方法细节。" * 40 + "</p>"}}},
            "p1": {"data": {"metaData": {"title": "访谈", "url": "https://www.xiaoyuzhoufm.com/episode/e1", "sourceName": "某播客"},
                           "podCastContentData": {"transcriptionSegments": [
                               {"speakerId": "1", "speakerName": "发言人1", "text": "你好。"},
                               {"speakerId": "1", "speakerName": "发言人1", "text": "今天聊产品。"},
                               {"speakerId": "2", "speakerName": "发言人2", "text": "先说失败。"}]}}},
        }

        class Response:
            def __init__(self, content=b"", payload=None):
                self.content, self.payload = content, payload

            def raise_for_status(self):
                return None

            def json(self):
                if self.payload is None:
                    raise ValueError("not json")
                return self.payload

        def fake_get(url, **kwargs):
            if "feeds" in url:
                return Response(feed)
            resource = url.rsplit("/", 1)[-1].split("?")[0]
            if resource == "broken":
                raise TimeoutError("api timeout")
            return Response(payload=payloads[resource])

        source = {"name": "BestBlogs", "category": "中文AI精选", "priority": 5, "url": "https://www.bestblogs.dev/zh/feeds/rss?category=ai",
                  "api_url_template": "https://www.bestblogs.dev/api/proxy/resources/{id}?language=zh"}
        with patch("scrape_aihot.requests.get", side_effect=fake_get):
            rows = fetch_bestblogs(source, {"request_timeout_seconds": 1, "hydrate_workers": 2})
        by_link = {row["link"]: row for row in rows}
        self.assertEqual(set(by_link), {"https://mp.weixin.qq.com/s/abc", "https://www.xiaoyuzhoufm.com/episode/e1"})
        article = by_link["https://mp.weixin.qq.com/s/abc"]
        self.assertEqual((article["source_name"], article["bestblogs_score"], article["published"]), ("某作者", 92, "2026-09-17"))
        self.assertEqual(article["content_origin"], "bestblogs_api")
        self.assertTrue(article["content"].startswith("第一段真实经历。\n"))
        self.assertNotIn("x()", article["content"])
        podcast = by_link["https://www.xiaoyuzhoufm.com/episode/e1"]
        self.assertEqual(podcast["content_status"], "transcript")
        self.assertEqual(podcast["content"], "发言人1：你好。今天聊产品。\n\n发言人2：先说失败。")
        with patch("scrape_aihot.requests.get") as get:
            self.assertEqual(hydrate(article, {"request_timeout_seconds": 1}), article)
            get.assert_not_called()

    def test_follow_builders_is_discovery_radar_only(self) -> None:
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"x": [{"name": "Boris", "handle": "bcherny", "bio": "Claude Code", "tweets": [
                    {"text": "低热度", "url": "https://x.com/bcherny/status/1", "createdAt": "2026-09-16T16:28:29Z", "likes": 3},
                    {"text": "高热度", "url": "https://x.com/bcherny/status/2", "createdAt": "2026-09-16T17:00:00Z", "likes": 900},
                    {"text": "无链接", "url": "javascript:alert(1)"}]}, None]}

        source = {"name": "follow-builders", "category": "英文一手雷达", "priority": 4, "url": "https://raw.example/feed-x.json"}
        with patch("scrape_aihot.requests.get", return_value=Response()):
            rows = fetch_follow_builders(source, {"request_timeout_seconds": 1})
        self.assertEqual([row["title"] for row in rows], ["高热度", "低热度"])
        self.assertTrue(all(row["source_role"] == "discovery" and row["language"] == "en" for row in rows))
        self.assertEqual(rows[0]["published"], "2026-09-16")

    def test_rss_feed_content_and_generic_title_exclusion(self) -> None:
        feed = """<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>号</title>
          <item><title>对话某产品负责人</title><link>https://mp.weixin.qq.com/s/a</link>
            <content:encoded><![CDATA[<p>""" + "完整访谈正文。" * 60 + """</p>]]></content:encoded></item>
          <item><title>线下活动报名开启</title><link>https://mp.weixin.qq.com/s/b</link>
            <content:encoded><![CDATA[<p>""" + "报名信息。" * 60 + """</p>]]></content:encoded></item>
          <item><title>短帖</title><link>https://mp.weixin.qq.com/s/c</link><content:encoded><![CDATA[<p>很短</p>]]></content:encoded></item>
        </channel></rss>"""

        class Response:
            content = feed.encode("utf-8")

            def raise_for_status(self):
                return None

        source = {"name": "访谈号", "category": "公众号访谈", "priority": 4, "type": "rss", "url": "https://feed.example/a.xml",
                  "items_limit": 5, "use_feed_content": True, "title_exclude_pattern": "报名"}
        with patch("scrape_aihot.requests.get", return_value=Response()):
            rows, error = fetch_source(source, {"request_timeout_seconds": 1, "rss_items_per_source": 1})
        self.assertIsNone(error)
        self.assertEqual([row["title"] for row in rows], ["对话某产品负责人", "短帖"])
        self.assertEqual(rows[0]["content_origin"], "feed_fulltext")
        self.assertNotIn("content", rows[1])
        with patch("scrape_aihot.requests.get", return_value=Response()):
            self.assertEqual(len(fetch_rss({**source, "use_feed_content": False}, {"request_timeout_seconds": 1, "rss_items_per_source": 1})), 3)

    def test_discovery_digest_keeps_recent_leads_newest_first_without_bodies(self) -> None:
        now = datetime(2026, 9, 18, tzinfo=timezone.utc)
        items = [
            {"title": "旧", "link": "https://a/1", "published": "2026-08-01", "source_name": "甲", "source_category": "播客", "content": "长正文"},
            {"title": "新", "link": "https://a/2", "published": "2026-09-17", "source_name": "乙", "source_category": "播客", "content": "长正文", "summary": "摘要" * 200},
            {"title": "次新", "link": "https://a/3", "published": "2026-09-10", "source_name": "丙", "source_category": "X"},
            {"title": "无日期", "link": "https://a/4", "source_name": "丁", "source_category": "X"},
        ]
        rows = discovery_digest(items, now, 14)
        self.assertEqual([r["title"] for r in rows], ["新", "次新", "无日期"])
        self.assertNotIn("content", rows[0])
        self.assertEqual(len(rows[0]["summary"]), 200)
        markdown = render_discovery_markdown(rows)
        self.assertIn("## 播客（1）", markdown)
        self.assertIn("- 2026-09-17 [新](https://a/2) · 乙", markdown)
        self.assertIn("- 日期未知 [无日期](https://a/4) · 丁", markdown)

    def test_rss_falls_back_to_mirror_host_with_same_path(self) -> None:
        import requests

        class Response:
            content = "<rss version='2.0'><channel><item><title>单集</title><link>https://x/1</link></item></channel></rss>".encode("utf-8")

            def raise_for_status(self):
                return None

        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            if url.startswith("https://rsshub.primary"):
                raise requests.ConnectionError("down")
            if url.startswith("https://rsshub.empty"):
                empty = Response()
                empty.content = b"<html>Welcome to RSSHub!</html>"
                return empty
            return Response()

        source = {"name": "播客", "category": "播客", "priority": 4, "type": "rss",
                  "url": "https://rsshub.primary/xiaoyuzhou/podcast/abc?limit=5", "mirror_hosts": ["https://rsshub.mirror"]}
        with patch("scrape_aihot.requests.get", side_effect=fake_get):
            rows = fetch_rss(source, {"request_timeout_seconds": 1, "rss_items_per_source": 5})
        self.assertEqual([row["title"] for row in rows], ["单集"])
        self.assertEqual(calls, ["https://rsshub.primary/xiaoyuzhou/podcast/abc?limit=5", "https://rsshub.mirror/xiaoyuzhou/podcast/abc?limit=5"])
        calls.clear()
        with patch("scrape_aihot.requests.get", side_effect=fake_get):
            rows = fetch_rss({**source, "url": "https://rsshub.empty/xiaoyuzhou/podcast/abc?limit=5"}, {"request_timeout_seconds": 1, "rss_items_per_source": 5})
        self.assertEqual([row["title"] for row in rows], ["单集"])
        self.assertEqual(calls[-1], "https://rsshub.mirror/xiaoyuzhou/podcast/abc?limit=5")

    def test_scrape_records_one_ledger_row_per_family_source(self) -> None:
        import scrape_aihot
        attempts = [
            {"source": "访谈号", "url": "https://feed.example/a", "family": "wechat", "role": "candidate", "result_count": 3, "error": None},
            {"source": "坏源", "url": "https://feed.example/b", "family": "chinese_longform_web", "role": "candidate", "result_count": 0, "error": "timeout"},
            {"source": "无族来源", "url": "https://feed.example/c", "family": None, "role": "candidate", "result_count": 5, "error": None},
        ]
        passed = {"eligibility": {"status": "passed"}}
        items = [{"collected_by": "访谈号", "content_status": "fulltext"}, {"collected_by": "访谈号", "content_status": "summary"},
                 {"collected_by": "访谈号", "content_status": "transcript"}]
        ranked = [{"collected_by": "访谈号", "link": "https://mp.weixin.qq.com/s/a", "content_status": "fulltext", "editorial_decision": passed},
                  {"collected_by": "访谈号", "content_status": "summary", "editorial_decision": passed}]

        class Args:
            batch, owner, round = "2026-09-17-x", "主力", 2

        with tempfile.TemporaryDirectory() as tmp, patch("discovery_ledger.DEFAULT_LEDGER", Path(tmp) / "ledger.jsonl"):
            errors: list[str] = []
            scrape_aihot.record_source_attempts(attempts, items, ranked, Args, 45, errors)
            rows = [json.loads(line) for line in (Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(errors, [])
        self.assertEqual([(r["query"], r["status"], r["fulltext_count"], r["eligible_count"]) for r in rows],
                         [("访谈号", "success", 2, 1), ("坏源", "failed", 0, 0)])
        self.assertEqual(len(rows[0]["eligible_keys"]), 1)
        self.assertTrue(all(r["round"] == 2 and r["max_age_days"] == 45 and r["batch"] == "2026-09-17-x" for r in rows))

    def test_retired_platform_migration_stays_reviewable(self) -> None:
        base = {**self.items[0], "published": "2026-09-10", "summary": "", "content_status": "fulltext",
                "content": "作者复盘真实迁移过程、失败和验收方法。" * 160}
        tutorial = score_item({**base, "title": "n8n 搭建自动化工作流保姆级教程"}, self.profile, now=self.now)
        migration = score_item({**base, "title": "把 n8n 流程迁移成 Agent 执行闭环"}, self.profile, now=self.now)
        product_swap = score_item({**base, "title": "从扣子桌面换到本地 Agent 之后"}, self.profile, now=self.now)
        self.assertIn("传统节点式 Workflow 平台已被用户明确淘汰", tutorial["penalty"])
        self.assertEqual(tutorial["editorial_decision"]["eligibility"]["status"], "failed")
        for item in (migration, product_swap):
            self.assertNotIn("已被用户明确淘汰", item["penalty"])
            self.assertNotIn("用户当前不认可该产品", item["penalty"])
            self.assertNotEqual(item["editorial_decision"]["eligibility"]["status"], "failed")

    def test_http_cache_is_shared_until_ttl_and_off_by_default(self) -> None:
        class Response:
            content, encoding = b'{"ok": 1}', "utf-8"

            def raise_for_status(self):
                return None

            def json(self):
                return json.loads(self.content)

        with tempfile.TemporaryDirectory() as tmp:
            settings = {"request_timeout_seconds": 1, "cache_dir": tmp, "cache_ttl_seconds": 3600}
            with patch("scrape_aihot.requests.get", return_value=Response()) as get:
                self.assertEqual(http_get("https://feed.example/a", settings, params={"b": 2, "a": 1}).json(), {"ok": 1})
                self.assertEqual(http_get("https://feed.example/a", settings, params={"a": 1, "b": 2}).json(), {"ok": 1})
                self.assertEqual(get.call_count, 1)
                http_get("https://feed.example/a", settings, ttl=0)
                self.assertEqual(get.call_count, 2)
            with patch("scrape_aihot.requests.get", return_value=Response()) as get:
                http_get("https://feed.example/a", {"request_timeout_seconds": 1})
                http_get("https://feed.example/a", {"request_timeout_seconds": 1})
                self.assertEqual(get.call_count, 2)
            self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(tmp)))

        with tempfile.TemporaryDirectory() as tmp:
            settings = {"request_timeout_seconds": 1, "cache_dir": tmp, "failure_cache_ttl_seconds": 900}
            with patch("scrape_aihot.requests.get", side_effect=requests.ConnectionError("timed out")) as get:
                for _ in range(3):
                    with self.assertRaises(requests.RequestException):
                        http_get("https://dead.example/feed", settings)
                # 连接失败退避重试，之后由失败缓存挡住，不会每轮都去撞同一个死链接。
                self.assertEqual(get.call_count, 2)

    def test_review_pool_skips_articles_too_short_to_publish(self) -> None:
        shortlisted = {"machine_disposition": "shortlist"}
        ranked = [
            {"link": "https://a.example/1", "content_status": "fulltext", "content": "短" * 100, "editorial_decision": shortlisted},
            {"link": "https://a.example/2", "content_status": "fulltext", "content": "长" * 3000, "editorial_decision": shortlisted},
            {"link": "https://a.example/3", "content_status": "summary", "content": "", "editorial_decision": shortlisted},
        ]
        links = [row["link"] for row in select_report_candidates(ranked, 10, maximum_github=1, min_article_chars=2500)]
        self.assertEqual(links, ["https://a.example/2", "https://a.example/3"])

    def test_paged_web_index_walks_pages_and_dedupes(self) -> None:
        pages = {
            "https://lib.example/ai/articles/": "<main><a href='/ai/articles/a/'><h3>第一篇中文 AI 实战长文标题</h3></a><a href='/ai/articles/b/'><h3>第二篇中文 AI 实战长文标题</h3></a></main>",
            "https://lib.example/ai/articles/2/": "<main><a href='/ai/articles/b/'><h3>第二篇中文 AI 实战长文标题</h3></a><a href='/ai/articles/c/'><h3>第三篇中文 AI 实战长文标题</h3></a><a href='/ai/articles/d/'><h3>BestBlogs早报·09-13｜汇总不进入</h3></a></main>",
        }

        class Response:
            encoding = "utf-8"

            def __init__(self, url):
                self.content = pages[url].encode("utf-8")

            def raise_for_status(self):
                return None

        source = {"name": "觉醒AI", "category": "中文AI实战知识库", "priority": 5, "type": "paged_web",
                  "url": "https://lib.example/ai/articles/", "page_url_template": "https://lib.example/ai/articles/{page}/",
                  "pages": 2, "items_limit": 10, "include_path_prefix": "/ai/articles/", "title_exclude_pattern": "早报"}
        with patch("scrape_aihot.requests.get", side_effect=lambda url, **kwargs: Response(url)):
            rows, error = fetch_source(source, {"request_timeout_seconds": 1, "web_links_per_source": 1})
        self.assertIsNone(error)
        self.assertEqual([row["link"].rsplit("/", 2)[-2] for row in rows], ["a", "b", "c"])

    def test_library_uses_structured_publication_date_over_list_refresh_date(self) -> None:
        html = ('<html><head><script type="application/ld+json">{"datePublished":"2026-01-27","dateModified":"2026-09-17"}</script></head>'
                "<body><article><h1>一家五岁初创的全员 AI 改造</h1>" + "<p>非工程师成了智能体最大用户，服务迁移从四个月缩到一周。</p>" * 40 + "</article></body></html>")

        class Response:
            encoding = "utf-8"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                return None

            def iter_content(self, size):
                yield html.encode("utf-8")

        item = {"link": "https://www.jxxy.net/ai/articles/craft/", "title": "一家五岁初创的全员 AI 改造", "published": "2026-09-17", "source_role": "candidate"}
        with patch("scrape_aihot.requests.get", return_value=Response()):
            result = hydrate(item, {"request_timeout_seconds": 1, "max_article_bytes": 1_000_000})
        self.assertEqual(result["published"], "2026-01-27")

    def test_web_index_decodes_utf8_and_respects_article_prefix(self) -> None:
        class Response:
            encoding = "ISO-8859-1"
            content = """<main>
              <article><a href='/ai/articles/one/'><h2>中文 AI 实战长文标题</h2><p>有真实细节</p></a></article>
              <article><a href='/ai/ai-daily/today/'><h2>每日汇总不应进入</h2></a></article>
            </main>""".encode("utf-8")

            def raise_for_status(self):
                return None

        source = {
            "name": "觉醒AI",
            "url": "https://www.jxxy.net/ai/",
            "category": "中文AI实战知识库",
            "priority": 5,
            "include_path_prefix": "/ai/articles/",
        }
        with patch("scrape_aihot.requests.get", return_value=Response()):
            rows = fetch_web_index(source, {"request_timeout_seconds": 1, "web_links_per_source": 10})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "中文 AI 实战长文标题")

    def test_personalized_ranking_and_exclusions(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)
        titles = [item["title"] for item in ranked]
        self.assertEqual(sum("Codex Harness" in title for title in titles), 1)
        self.assertTrue(any("Codex Harness" in item["title"] for item in ranked[:3]))
        self.assertIn("中文内容", ranked[0]["reason"])
        self.assertTrue(any("已有逐字稿" in item["reason"] for item in ranked[:3]))
        excluded = {item["title"]: item for item in ranked if item["penalty"]}
        self.assertIn("Weekly roundup of 25 AI benchmark leaderboard updates", excluded)
        self.assertIn("Election surveillance platform adds AI weapon detection", excluded)
        self.assertFalse(excluded["Election surveillance platform adds AI weapon detection"]["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "v2.1.241")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "Windows 11 arm64 image generally available")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "llm-anthropic 0.27")["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"].startswith("DeepSeek上线多模态；"))["recommended"])
        self.assertFalse(next(item for item in ranked if item["title"] == "130亿美元，Hugging Face要卖了")["recommended"])

    def test_named_ai_products_count_as_explicit_ai_objects(self) -> None:
        item = {
            "title": "Kimi Work一个月使用复盘：120个真实任务中的坑和红利",
            "summary": "记录多文件汇总、表格分析、网页抓取与人工校验",
            "content": "一个月完成120个任务，逐项记录有效场景、翻车场景、Token消耗和人工检查。" * 80,
            "published": "2026-08-10T08:00:00Z",
            "source_name": "中文独立博客",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
            "link": "https://example.com/kimi-work-month-review",
        }
        for title in (item["title"], "ChatGPT 对话导出实测", "Chatbox 工作模式复盘"):
            result = rank_candidates([{**item, "title": title, "link": f"https://example.com/{title}"}], self.profile, now=datetime(2026, 9, 2, tzinfo=timezone.utc))[0]
            self.assertNotIn("缺少明确 AI 对象", result["penalty"])

    def test_self_disclosed_ai_generated_article_is_rejected(self) -> None:
        item = {
            "title": "AI 内容生产线的六个工位",
            "summary": "从材料到发布的完整方法",
            "content": "本篇内容由豆包和 Codex 以及作者知识库组合完成。" + ("真实案例和方法说明。" * 300),
            "published": "2026-08-23",
            "source_name": "中文内容站",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/ai-authored",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("文章主动披露由 AI 生成", result["penalty"])

    def test_authoritative_talk_can_use_benchmark_as_supporting_evidence(self) -> None:
        item = {
            "title": "Anthropic 长时程 Agent 完整工作坊",
            "summary": "完整演讲整理，主体是脑手分离、独立验证器和记忆纠错架构",
            "content": ("讲者拆解长任务架构、会话日志与记忆纠错。" * 220) + "Parameter Golf benchmark 和基准测试只用作一组局部证据。",
            "published": "2026-07-22",
            "source_name": "Anthropic 团队演讲",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/anthropic-talk",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertTrue(result["recommended"])

    def test_default_batch_is_ten_topics_without_composition_quota(self) -> None:
        self.assertEqual(self.profile["default_topic_count"], 10)
        self.assertEqual(self.profile["report_candidate_count"], 30)
        for retired in ("minimum_delivery_count", "minimum_non_github_candidates", "maximum_github_candidates", "selection_count"):
            self.assertNotIn(retired, self.profile)

    def test_report_selection_caps_github_at_one(self) -> None:
        ranked = [
            {"id": "gh-1", "recommended": True, "link": "https://github.com/example/one"},
            {"id": "gh-2", "recommended": True, "link": "https://github.com/example/two"},
            {"id": "web-1", "recommended": True, "link": "https://example.com/one"},
            {"id": "web-2", "recommended": True, "link": "https://example.com/two"},
        ]
        selected = select_report_candidates(ranked, 4, maximum_github=1)
        self.assertEqual([item["id"] for item in selected], ["gh-1", "web-1", "web-2"])

    def test_github_candidates_require_at_least_one_hundred_verified_stars(self) -> None:
        common = {
            "title": "把真实任务封装成一个可复用的中文 Skill",
            "summary": "包含完整案例、验证结果和可执行方法",
            "content": ("作者公开真实输入、失败过程、成品与自动测试。" * 180),
            "published": "2026-09-04",
            "source_name": "GitHub 项目作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
        }
        missing = score_item({**common, "link": "https://github.com/example/missing"}, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        low = score_item({**common, "link": "https://github.com/example/low", "github_stars": 99}, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        enough = score_item({**common, "link": "https://github.com/example/enough", "github_stars": 100}, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(missing["recommended"])
        self.assertIn("Star 数未核验", missing["penalty"])
        self.assertFalse(low["recommended"])
        self.assertIn("低于 100", low["penalty"])
        self.assertNotIn("Star", enough["penalty"])
        self.assertIn("GitHub 100 Star", enough["reason"])

    def test_stale_github_repo_is_blocked(self) -> None:
        common = {
            "published": "2026-09-05",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
        }
        stale_repo = score_item({**common, "title": "ChatGPT 长对话导出工具", "summary": "开源插件", "content": ("完整消息树与分页导出。" * 300), "source_name": "GitHub 作者", "published": "2026-08-25", "github_stars": 941, "link": "https://github.com/example/exporter"}, self.profile, now=datetime(2026, 9, 6, tzinfo=timezone.utc))
        self.assertIn("超过 7 天", stale_repo["penalty"])

    def test_translation_only_podcast_digest_domain_is_blocked(self) -> None:
        item = {
            "title": "OpenAI 产品负责人谈 AI 时代的知识工作",
            "summary": "海外播客中文问答整理",
            "content": ("主持人提问。嘉宾回答。编辑补充。" * 220),
            "published": "2026-09-04",
            "source_name": "海外科技播客中文整理",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://onepod.site/p/example/",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertTrue(result["penalty"])
        self.assertIn("来源域名已被明确排除", result["penalty"])

    def test_report_contains_review_controls(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)[:5]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report(ranked, path, "2026-08-25-120000")
            report = path.read_text()
            self.assertIn("要这个", report)
            self.assertIn("不要", report)
            self.assertIn("没点的都算", report)
            self.assertIn("data-reason=\"AI 味重\"", report)
            self.assertIn("implicit:true", report)
            self.assertIn("补充遗漏选题", report)
            self.assertIn("selection_feedback-2026-08-25-120000.json", report)
            self.assertIn("二创成熟度", report)
            self.assertIn("已自动保存到浏览器，尚未导出", report)
            self.assertIn("导出全部审核结果", report)
            self.assertIn("beforeunload", report)
            self.assertIn("review-counts", report)
            self.assertIn("state.dirty===undefined", report)

    def test_report_displays_verified_github_stars(self) -> None:
        candidate = {
            "id": "github-1",
            "title": "一个实用的中文 Skill",
            "link": "https://github.com/example/useful-skill",
            "summary": "完整说明",
            "source_name": "项目作者",
            "content_form": "article",
            "content_status": "fulltext",
            "adaptation_readiness": "高",
            "research_cost": "低",
            "github_stars": 128,
            "score": 100,
            "recommended": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report([candidate], path, "2026-09-04-120000")
            report = path.read_text()
        self.assertIn("GitHub 128 Star", report)

    def test_report_exposes_human_article_and_skill_source_links(self) -> None:
        candidate = {
            "id": "skill-with-article",
            "title": "daily-life-skill",
            "link": "https://example.com/human-review",
            "source_url": "https://github.com/example/daily-life-skill",
            "skill_url": "https://skills.sh/example/daily-life-skill",
            "article_zh": "这是一份可以直接阅读的中文文章解读，讲清真人为什么使用这项 Skill、具体减少了哪一步操作，以及什么情况下不值得安装。",
            "localization_review": {
                "status": "passed",
                "evidence": "使用本地文件和中文界面，不依赖海外专属服务，国内用户可以按原流程完成任务。",
            },
            "setup_cost_review": {
                "status": "passed",
                "evidence": "基础功能开源免费，只需一条本地安装命令，不需要购买订阅或申请额外 API Key。",
            },
            "security_review": {
                "status": "passed",
                "risk": "low",
                "evidence": "已检查 SKILL.md、执行脚本和仓库测试，核心流程不读取密钥，也不会自动发布内容。",
            },
            "summary": "一篇人类作者的真实使用复盘与对应公开 Skill。",
            "source_name": "作者博客 / GitHub",
            "content_form": "article",
            "content_status": "fulltext",
            "adaptation_readiness": "高",
            "research_cost": "低",
            "score": 100,
            "recommended": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report([candidate], path, "2026-09-09-120000")
            report = path.read_text()
        self.assertIn('aria-label="参考链接"', report)
        self.assertIn('href="https://example.com/human-review"', report)
        self.assertIn('href="https://github.com/example/daily-life-skill"', report)
        self.assertIn('href="https://skills.sh/example/daily-life-skill"', report)
        self.assertIn("人类文章", report)
        self.assertIn("GitHub / Skill 原文", report)
        self.assertIn("Skill 目录页", report)
        self.assertIn("中文文章解读", report)
        self.assertIn("中文用户适配", report)
        self.assertIn("不依赖海外专属服务", report)
        self.assertIn("配置与付费", report)
        self.assertIn("安全审查", report)
        self.assertIn("不需要购买订阅", report)

    def test_report_gate_does_not_fill_with_rejected_items(self) -> None:
        ranked = [
            {"id": "good", "recommended": True, "score": 100},
            {"id": "bad-1", "recommended": False, "score": 99},
            {"id": "bad-2", "recommended": False, "score": 98},
        ]
        self.assertEqual([item["id"] for item in select_report_candidates(ranked, 15)], ["good"])
        self.assertEqual(len(select_report_candidates(ranked, 15, include_rejected=True)), 3)

    def test_video_report_exposes_full_transcript(self) -> None:
        candidate = {
            "id": "video-1",
            "title": "AI 工作流真实复盘",
            "link": "https://www.youtube.com/watch?v=test",
            "summary": "有完整材料",
            "content": "这是审核时需要直接阅读的完整逐字稿。" * 30,
            "source_name": "测试频道",
            "content_form": "video",
            "content_status": "transcript",
            "adaptation_readiness": "高",
            "research_cost": "低",
            "score": 100,
            "recommended": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report([candidate], path, "2026-09-04-120000")
            report = path.read_text()
        self.assertIn("查看整理后的完整逐字稿", report)
        self.assertIn("原音视频核对", report)
        self.assertIn("这是审核时需要直接阅读的完整逐字稿", report)

    def test_empty_report_explains_that_nothing_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report([], path, "2026-08-25-120000")
            report = path.read_text()
            self.assertIn("本轮没有合格候选", report)
            self.assertIn("不用为了凑数", report)

    def test_local_transcript_becomes_ready_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / "transcript.txt"
            transcript.write_text("这是一份中文逐字稿。" * 100)
            item = inbox_item(
                {
                    "url": "https://www.bilibili.com/video/BVtest",
                    "platform": "bilibili",
                    "creator": "测试UP主",
                    "title": "Codex Agent 工作流深度复盘",
                    "published": "2026-08-24",
                    "transcript_path": str(transcript),
                },
                {"request_timeout_seconds": 1, "max_article_bytes": 1000},
            )
            self.assertEqual(item["content_status"], "transcript")
            self.assertEqual(item["language"], "zh")
            self.assertGreater(len(item["content"]), 500)

    def test_inbox_preserves_primary_source_maturity(self) -> None:
        with patch("scrape_aihot.hydrate", side_effect=lambda item, _settings: item):
            item = inbox_item(
                {
                    "url": "https://openai.com/example",
                    "platform": "web",
                    "creator": "OpenAI",
                    "title": "ChatGPT 研究",
                    "maturity": "primary",
                },
                {"request_timeout_seconds": 1, "max_article_bytes": 1000},
            )
        self.assertEqual(item["maturity"], "primary")

    def test_inbox_preserves_verified_github_stars(self) -> None:
        with patch("scrape_aihot.hydrate", side_effect=lambda item, _settings: item):
            item = inbox_item(
                {
                    "url": "https://github.com/example/useful-skill",
                    "platform": "web",
                    "creator": "项目作者",
                    "title": "实用中文 Skill",
                    "github_stars": 128,
                },
                {"request_timeout_seconds": 1, "max_article_bytes": 1000},
            )
        self.assertEqual(item["github_stars"], 128)

    @patch("scrape_aihot.requests.get")
    def test_inbox_can_fetch_original_content_separately_from_display_url(self, get) -> None:
        response = get.return_value
        response.content = ("一手复盘正文。" * 500).encode()
        response.encoding = "utf-8"
        response.raise_for_status.return_value = None
        item = inbox_item(
            {
                "url": "https://gist.github.com/example/source",
                "content_url": "https://gist.githubusercontent.com/example/source/raw/article.md",
                "platform": "web",
                "title": "AI 产品一线失败复盘",
            },
            {"request_timeout_seconds": 1, "max_article_bytes": 20000},
        )
        self.assertEqual(item["link"], "https://gist.github.com/example/source")
        self.assertEqual(item["content_status"], "fulltext")
        self.assertEqual(item["content_origin"], "explicit_content_url")
        self.assertGreater(len(item["content"]), 2500)

    @patch("scrape_aihot.requests.get")
    def test_inbox_can_select_article_from_public_javascript_map(self, get) -> None:
        response = get.return_value
        response.content = ('window.articleContent = ' + json.dumps({"target": "目标正文。" * 500}, ensure_ascii=False) + ';').encode()
        response.encoding = "utf-8"
        response.raise_for_status.return_value = None
        item = inbox_item(
            {
                "url": "https://example.com/article/target",
                "content_url": "https://example.com/article-data.js",
                "content_json_key": "target",
                "platform": "web",
                "title": "AI 写作实验",
            },
            {"request_timeout_seconds": 1, "max_article_bytes": 20000},
        )
        self.assertEqual(item["content_status"], "fulltext")
        self.assertTrue(item["content"].startswith("目标正文"))
        with patch("scrape_aihot.requests.get") as hydrate_get:
            hydrate(item, {"request_timeout_seconds": 1, "max_article_bytes": 20000})
        hydrate_get.assert_not_called()

    def test_blocked_creator_mention_does_not_block_another_author(self) -> None:
        result = score_item(
            {
                "title": "我写了个 AI 写作 Skill，第一次改稿就翻车了",
                "link": "https://example.com/writing-skill",
                "summary": "另一位作者的独立实验",
                "content": ("文中提到数字生命卡兹克的 human-writing，然后记录自己的语料筛选、对照测试和失败。" * 120),
                "published": "2026-08-12",
                "source_name": "黄晓黑",
                "source_priority": 5,
                "source_type": "web",
                "language": "zh",
                "maturity": "secondary",
                "content_form": "article",
                "content_status": "fulltext",
            },
            self.profile,
            now=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertNotIn("作者或个人 IP 已被明确排除", result["penalty"])

    @patch("scrape_aihot.fetch_youtube_transcript", return_value="AI Agent 工作流实测。" * 40)
    def test_youtube_uses_non_browser_transcript(self, fetch_transcript) -> None:
        item = inbox_item(
            {
                "url": "https://www.youtube.com/watch?v=test",
                "platform": "youtube",
                "creator": "测试频道",
                "title": "AI Agent 工作流复盘",
            },
            {"request_timeout_seconds": 1, "max_article_bytes": 1000},
        )
        self.assertEqual(item["content_form"], "video")
        self.assertEqual(item["content_status"], "transcript")
        self.assertGreater(len(item["content"]), 200)
        fetch_transcript.assert_called_once_with("https://www.youtube.com/watch?v=test")

    def test_hydrate_never_downgrades_a_transcript(self) -> None:
        item = {
            "link": "https://www.youtube.com/watch?v=test",
            "content": "完整字幕" * 200,
            "content_form": "video",
            "content_status": "transcript",
        }
        self.assertIs(hydrate(item, {"request_timeout_seconds": 1, "max_article_bytes": 1000}), item)
        self.assertEqual(item["content_status"], "transcript")

    @patch("scrape_aihot.requests.get", side_effect=RuntimeError("403"))
    def test_hydrate_does_not_fall_back_to_browser_bridge(self, _get) -> None:
        item = hydrate(
            {
                "link": "https://zhuanlan.zhihu.com/p/test",
                "content": "",
                "content_form": "article",
                "content_status": "summary",
            },
            {"request_timeout_seconds": 1, "max_article_bytes": 1000},
        )
        self.assertEqual(item["content_status"], "summary")
        self.assertIn("403", item["fetch_error"])

    def test_video_without_transcript_is_not_recommended(self) -> None:
        profile = json.loads((ROOT / "resources" / "editorial_profile.json").read_text())
        result = score_item(
            {
                "title": "AI Agent 工作流深度复盘",
                "link": "https://www.youtube.com/watch?v=missing",
                "summary": "创作者介绍自己的长期实践。",
                "content": "详细 Show Notes。" * 100,
                "published": "2026-08-24",
                "source_name": "中文频道",
                "source_priority": 5,
                "source_type": "youtube",
                "language": "zh",
                "maturity": "secondary",
                "content_form": "video",
                "content_status": "shownotes",
            },
            profile,
            now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        self.assertFalse(result["recommended"])
        self.assertIn("视频缺少逐字稿", result["penalty"])

    def test_old_first_person_failure_review_is_still_outdated(self) -> None:
        item = score_item(
            {
                "title": "一个 AI 产品从高峰到收缩：内部产品经理复盘",
                "link": "https://example.com/evergreen-review",
                "summary": "产品上线后，作者记录数月亲历、真实用户反馈、失败和调整过程",
                "content": "作者记录真实用户冲突、错误决策和后续调整。" * 300,
                "published": "2026-06-01",
                "source_name": "原作者",
                "source_priority": 5,
                "source_type": "web",
                "language": "zh",
                "maturity": "secondary",
                "content_form": "article",
                "content_status": "fulltext",
            },
            self.profile,
            now=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertFalse(item["recommended"])
        self.assertIn("超过时效范围", item["penalty"])
        self.assertIn("事件新闻已超过时效窗口", item["penalty"])

    def test_historical_duplicate_uses_body_not_title_or_url(self) -> None:
        body = "作者记录了真实需求、失败过程、用户反馈和三次调整。" * 180
        reviewed = [{"title": "旧标题", "link": "https://old.example.com/a", "content": body}]
        renamed = {"title": "完全不同的新标题", "link": "https://new.example.com/b", "content": body}
        unrelated = {"title": "另一个主题", "link": "https://new.example.com/c", "content": "另一篇独立正文。" * 400}
        self.assertTrue(is_historical_content_duplicate(renamed, reviewed))
        self.assertFalse(is_historical_content_duplicate(unrelated, reviewed))

    def test_utf8_page_ignores_misleading_latin1_header(self) -> None:
        raw = "用 AI 让我们变笨了吗？认知债务与长期记忆".encode("utf-8")
        decoded = decode_html(raw, "ISO-8859-1")
        self.assertEqual(decoded, "用 AI 让我们变笨了吗？认知债务与长期记忆")

    def test_feedback_import_can_delete_verified_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / "selection_feedback.json"
            feedback.write_text(json.dumps({"exported_at": "2026-08-25T06:20:39Z", "reviews": {"x": {"status": "rejected"}}}))
            with patch.object(feedback_module, "ROOT", root):
                target, duplicate = feedback_module.import_feedback(feedback, delete_source=False)
                self.assertFalse(duplicate)
                self.assertTrue(feedback.exists())
                _, duplicate = feedback_module.import_feedback(feedback, delete_source=True)
                self.assertTrue(duplicate)
                self.assertFalse(feedback.exists())
                self.assertEqual(len(target.read_text().splitlines()), 1)
                self.assertEqual(feedback_module.final_reviewed_ids(target), {"x"})
            reviewed = feedback_module.final_reviewed_candidates(target)
            self.assertEqual([item["id"] for item in reviewed], [])

    def test_parallel_feedback_import_is_locked_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {"exported_at": "2026-09-04T12:55:00Z", "reviews": {"x": {"status": "selected"}}}
            first = root / "selection_feedback-1.json"
            second = root / "selection_feedback-2.json"
            first.write_text(json.dumps(payload))
            second.write_text(json.dumps(payload))
            with patch.object(feedback_module, "ROOT", root):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(feedback_module.import_feedback, [first, second]))
            target = root / ".local" / "editorial_feedback.jsonl"
            self.assertEqual(len(target.read_text().splitlines()), 1)
            self.assertEqual(sorted(duplicate for _, duplicate in results), [False, True])

    def test_feedback_cli_deletes_by_default_and_can_keep_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / "selection_feedback.json"
            candidates = [{"id":"x", "title":"AI材料", "link":"https://example.com/source"}]
            batch = root / "topics" / "batch1"
            batch.mkdir(parents=True)
            (batch / "candidates.json").write_text(json.dumps(candidates))
            payload = {"generated_at":"batch1", "candidates":candidates, "exported_at": "2026-09-05T04:00:00Z", "reviews": {"x": {"status": "pending", "note": "待定"}}}
            feedback.write_text(json.dumps(payload))
            with patch.object(feedback_module, "ROOT", root), patch("builtins.print"):
                with patch("sys.argv", ["import_feedback.py", str(feedback), "--expected-batch", "batch1", "--owner", "主力", "--keep-source"]):
                    feedback_module.main()
                self.assertTrue(feedback.exists())
                with patch("sys.argv", ["import_feedback.py", str(feedback), "--expected-batch", "batch1", "--owner", "主力"]):
                    feedback_module.main()
                self.assertFalse(feedback.exists())
                target = root / ".local/editorial_feedback.jsonl"
                self.assertTrue(feedback_module.already_imported(target, payload["exported_at"], payload))
                self.assertEqual(len(target.read_text().splitlines()), 1)

    def test_feedback_same_timestamp_changed_content_is_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / "selection_feedback.json"
            payload = {"exported_at": "2026-09-05T04:00:00Z", "reviews": {"x": {"status": "selected"}}}
            with patch.object(feedback_module, "ROOT", root):
                feedback.write_text(json.dumps(payload))
                target, _ = feedback_module.import_feedback(feedback)
                payload["reviews"]["x"] = {"status": "rejected", "note": "修改后的完整反馈"}
                feedback.write_text(json.dumps(payload))
                _, duplicate = feedback_module.import_feedback(feedback)
                self.assertFalse(duplicate)
                self.assertFalse(feedback.exists())
                self.assertEqual(len(target.read_text().splitlines()), 2)
                self.assertTrue(feedback_module.already_imported(target, payload["exported_at"], payload))

    def test_feedback_readback_failure_keeps_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feedback = root / "selection_feedback.json"
            feedback.write_text(json.dumps({"exported_at": "2026-09-05T04:00:00Z", "reviews": {}}))
            with patch.object(feedback_module, "ROOT", root), patch.object(feedback_module, "already_imported", return_value=False):
                with self.assertRaises(RuntimeError):
                    feedback_module.import_feedback(feedback)
                self.assertTrue(feedback.exists())

    def test_pending_feedback_is_deferred_until_reclassified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "editorial_feedback.jsonl"
            target.write_text(json.dumps({"reviews": {"later": {"status": "pending"}}}) + "\n")
            self.assertEqual(feedback_module.final_reviewed_ids(target), {"later"})
            with target.open("a") as handle:
                handle.write(json.dumps({"reviews": {"later": {"status": "selected"}}}) + "\n")
            self.assertEqual(feedback_module.final_reviewed_ids(target), {"later"})

    def test_incidental_body_words_do_not_trigger_hard_exclusions(self) -> None:
        common = {
            "published": "2026-08-06T08:00:00Z",
            "source_name": "中文深度媒体",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "Agent 任务为什么越跑越慢：上下文如何影响响应速度",
                "summary": "用大白话拆解 Agent 上下文机制",
                "content": "文中会讨论不同模型和产品，但这不是一篇模型发布稿。" * 120,
                "link": "https://example.com/agent-cost",
            },
            {
                **common,
                "title": "耗时 41 分钟，千问办公押注了怎样的 Agent 未来",
                "summary": "千问办公、WorkBuddy、TRAE Work 使用同一任务实测",
                "content": "测试任务是制作行业周报，文中也提到榜单，但文章核心是三条 Agent 路线对比。" * 120,
                "link": "https://example.com/agent-comparison",
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=self.now)}
        self.assertTrue(lookup["https://example.com/agent-cost"]["recommended"])
        self.assertTrue(lookup["https://example.com/agent-comparison"]["recommended"])
        self.assertNotIn("命中排除词", lookup["https://example.com/agent-comparison"]["penalty"])

    def test_event_recency_exempts_core_team_interviews(self) -> None:
        common = {
            "content": "一篇具有完整中文正文的深度材料。" * 250,
            "source_name": "中文深度媒体",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "AI 时代，Claude Code 创始人谈一人军队",
                "summary": "Anthropic 权威访谈，以下是对话全文",
                "published": "2026-08-05T08:00:00Z",
                "link": "https://example.com/old-interview",
            },
            {
                **common,
                "title": "耗时 41 分钟，千问办公押注了怎样的 Agent 未来",
                "summary": "三款 Agent 使用同一任务实测",
                "published": "2026-08-06T08:00:00Z",
                "link": "https://example.com/old-comparison",
            },
            {
                **common,
                "title": "Agent 成本失控背后：上下文、人工审核与维护成本正在被低估",
                "summary": "讨论供应商锁定与企业治理框架",
                "published": "2026-07-31T08:00:00Z",
                "link": "https://example.com/enterprise-cost",
            },
            {
                **common,
                "title": "Codex 也断了：Agent 时代的宕机账单怎么算",
                "summary": "OpenAI 故障导致任务中断",
                "published": "2026-07-26T08:00:00Z",
                "link": "https://example.com/stale-outage",
            },
        ]
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=now)}
        self.assertTrue(lookup["https://example.com/old-interview"]["recommended"])
        self.assertTrue(lookup["https://example.com/old-comparison"]["recommended"])
        self.assertIn("超过时效窗口", lookup["https://example.com/stale-outage"]["penalty"])

    def test_blocked_domains_and_controlled_test(self) -> None:
        common = {
            "summary": "完整的中文深度文章",
            "content": "文章有足够长的正文材料。" * 250,
            "published": "2026-08-25T08:00:00Z",
            "source_name": "中文来源",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "独立开发者 AI 编程工具横测：6 组方案付费实测",
                "link": "https://kylinlabai.github.io/knowledge/review.html",
            },
            {
                **common,
                "title": "Codex vs Claude Code：真实偏好实测对比",
                "link": "https://claudemax.shop/blog/comparison",
            },
            {
                **common,
                "title": "2026 年 8 月主流 AI Agent 怎么选？五大场景逐一对比",
                "link": "https://trusted.example.com/generic-list",
            },
            {
                **common,
                "title": "耗时 41 分钟，三款 Agent 同题实测",
                "summary": "三款 Agent 使用同一任务，保留时间和结果差异",
                "link": "https://trusted.example.com/controlled-test",
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=self.now)}
        self.assertIn("来源域名已被明确排除", lookup["https://kylinlabai.github.io/knowledge/review.html"]["penalty"])
        self.assertIn("来源域名已被明确排除", lookup["https://claudemax.shop/blog/comparison"]["penalty"])
        self.assertTrue(lookup["https://trusted.example.com/controlled-test"]["recommended"])

    def test_major_release_stays_eligible(self) -> None:
        common = {
            "content": "一篇具有完整中文正文的 AI 文章。" * 160,
            "published": "2026-09-02T08:00:00Z",
            "source_name": "量子位",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        rejected_titles = [
            "GitHub最热架构图Agent，开发者故事看哭了",
            "阿里更新旗舰模型Qwen3.8-Max，前端编程能力跃居全球第一",
            "Claude最强Fable 5.1发布！8项屠榜，最高降价45%",
            "A社化身A割！Claude官宣永久提额25%，结果到手反而少17%",
            "前字节强化学习专家孙鹏博士加盟星尘智能，完善Physical AI全栈技术布局",
            "刚刚，GPT-6正式发布！OpenAI：欢迎来到AGI时代",
            "GPT-6 曝光，OpenAI 总裁说：AGI 来了",
            "AI 下一场竞争：谁能成为 Agent 的「上下文操作系统」",
            "企业级Agent落地样板间！百融硅基员工批量上岗，按结果领工资",
        ]
        items = [
            {**common, "title": title, "summary": "Agent、模型与产品动态", "link": f"https://example.com/noise-{index}"}
            for index, title in enumerate(rejected_titles)
        ]
        items.append(
            {
                **common,
                "title": "李飞飞发布：全球首个多模态世界模型",
                "summary": "一张图补全3D世界，并为机器人生成训练场，解释空间与时间建模能力",
                "link": "https://example.com/world-model",
            }
        )
        now = datetime(2026, 9, 2, tzinfo=timezone.utc)
        lookup = {item["title"]: item for item in rank_candidates(items, self.profile, now=now)}
        self.assertTrue(lookup["李飞飞发布：全球首个多模态世界模型"]["recommended"])

    def test_podcast_without_transcript_is_blocked(self) -> None:
        common = {
            "published": "2026-08-26T08:00:00Z",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "聊聊半年的 AI Agent 与 AI Coding 项目实战经验",
                "summary": "74 天一人一 Agent 正式项目复盘",
                "content": "Commit 数、代码量、测试用例、React 前端、容器化、daemon 线程、事件队列、向量索引、Docker 与反向代理。" * 40,
                "link": "https://example.com/code-heavy",
            },
            {
                **common,
                "title": "AI把创新效率拉满，为什么好想法却越来越少？",
                "summary": "生成式 AI 与创新的实证研究",
                "content": "创新流程、创新管理者、消费者洞察、市场学习、组织偏见、创意筛选与商业评论。" * 40,
                "link": "https://example.com/abstract-business",
            },
            {
                **common,
                "title": "用 AI 让我们变笨了吗？",
                "summary": "认知债务与学习方法",
                "content": "节目时间轴和核心观点。" * 80,
                "content_form": "podcast",
                "content_status": "shownotes",
                "link": "https://example.com/podcast-shownotes",
            },
            {
                **common,
                "title": "Agent 跑不起来，可能恰恰因为它太好做了",
                "summary": "业务门槛、工程门槛与五问自检清单",
                "content": "第一道门槛、第二道门槛、五问和自检清单。" * 80,
                "link": "https://example.com/formulaic",
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=datetime(2026, 9, 2, tzinfo=timezone.utc))}
        self.assertIn("播客缺少逐字稿", lookup["https://example.com/podcast-shownotes"]["penalty"])

    def test_blocked_creator_and_domain(self) -> None:
        common = {
            "published": "2026-08-30T08:00:00Z",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "AI辅助编程让资深工程师慢了19%",
                "summary": "结合多项研究解释效率错觉",
                "content": "Hacker News、METR、微软研究院、卡内基梅隆的研究显示，报告显示并调查了大量案例。" * 30,
                "source_name": "中文媒体",
                "link": "https://example.com/citation-collage",
            },
            {
                **common,
                "title": "Agent在真实工作场景的成功率很低",
                "summary": "真实任务评测",
                "content": "这套评测集包含107个任务，并对多个模型做Benchmark和基准测试。" * 40,
                "source_name": "数字生命卡兹克",
                "link": "https://example.com/blocked-creator",
            },
            {
                **common,
                "title": "DHH谈AI革命、模型实测与智能体编程",
                "summary": "AI总结与双语整理",
                "content": "打开互动全文版（中英对照 + 朗读 + 问答），以下是AI摘要。" * 50,
                "source_name": "AI Podcast 中文逐字稿",
                "link": "https://aipodcast.jasonlin.tech/example",
            },
            {
                **common,
                "title": "DeepSeek在8个Agent工具链上的表现",
                "summary": "成本与速度Benchmark",
                "content": "围绕评测集、跑分、排行榜和基准测试比较模型表现。" * 50,
                "source_name": "中文媒体",
                "link": "https://example.com/benchmark",
            },
        ]
        now = datetime(2026, 9, 2, tzinfo=timezone.utc)
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=now)}
        self.assertIn("个人 IP 已被明确排除", lookup["https://example.com/blocked-creator"]["penalty"])
        self.assertIn("来源域名已被明确排除", lookup["https://aipodcast.jasonlin.tech/example"]["penalty"])

    def test_old_event_news_is_blocked_but_task_story_stays(self) -> None:
        common = {
            "published": "2026-09-03T08:00:00Z", "source_priority": 5, "source_type": "web",
            "language": "zh", "maturity": "secondary", "content_status": "fulltext", "content_form": "article",
        }
        items = [
            {
                **common,
                "title": "千问办公产品负责人：Agent 如何把客户拜访 PPT 真正交出去",
                "summary": "现场演讲材料整理",
                "content": ("我们当时从明天下午拜访客户的真实任务出发，先找齐资料、历史沟通和最新进展。"
                            "生成客户拜访 PPT 后要核对事实，只需要改某一页时就局部修改，直到可以进入会议。") * 70,
                "source_name": "大会演讲整理", "link": "https://example.com/end-user-task",
            },
            {
                **common,
                "title": "小度 AI 硬件负责人复盘录音卡、儿童手表与摄像机",
                "summary": "智能硬件的成本与场景", "content": "录音卡、儿童手表、摄像机和智能音箱的产品取舍。" * 120,
                "source_name": "演讲整理", "link": "https://example.com/hardware-product",
            },
            {
                **common,
                "title": "AI 产品的边界、上限、退路",
                "summary": "专业产品治理检查", "content": ("用 WAF、权限层、状态机、熔断、风险分级、审批节点和服务端校验建立治理基线。"
                          "全文按边界、上限、退路的三层设计组织。") * 90,
                "source_name": "产品社区", "link": "https://example.com/pro-governance",
            },
            {
                **common,
                "published": "2026-08-13T08:00:00Z",
                "title": "Atlas 运行 292 天后停止服务",
                "summary": "AI 浏览器回收与落幕", "content": "OpenAI 关停 Atlas，回收早期产品投入。" * 130,
                "source_name": "中文媒体", "link": "https://example.com/old-closure",
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=datetime(2026, 9, 6, tzinfo=timezone.utc))}
        self.assertTrue(lookup["https://example.com/end-user-task"]["recommended"])
        self.assertIn("事件新闻已超过时效窗口", lookup["https://example.com/old-closure"]["penalty"])

    def test_main2_150320_feedback_blocks_partial_login_and_written_astra_prompt_topic(self) -> None:
        base = {
            "published": "2026-09-07T08:00:00Z", "source_priority": 5, "source_type": "web",
            "language": "zh", "maturity": "secondary", "content_status": "fulltext", "content_form": "article",
            "summary": "AI 的完整方法和案例", "source_name": "中文作者",
        }
        locked = score_item({**base, "title": "AI研究实习生完整报告", "link": "https://example.com/partial",
                             "content": ("公开正文提供研究方法和数据。" * 150) + "登录后查看剩余内容"}, self.profile)
        covered = score_item({**base, "title": "GPT-6 Astra 的隐形规则审计", "link": "https://example.com/astra-prompt",
                              "content": "让模型指出导致停顿的 Skill 与提示规则。" * 180}, self.profile)
        self.assertIn("材料不完整", locked["penalty"])
        self.assertIn("主题已写过", covered["penalty"])


if __name__ == "__main__":
    unittest.main()


class WayToAGITest(unittest.TestCase):
    def test_daily_picks_become_candidates_and_stubs_follow_the_original(self):
        home = '<a href="/zh/blog/news-20260919">知识库精选-2026年9月19日</a>'
        day = ('<nav><a href="https://waytoagi.feishu.cn/wiki/NAV">直达「 通往AGI之路 」飞书知识库 →</a></nav>'
               '<div><a href="https://waytoagi.feishu.cn/wiki/FULL">详解 Jev 模型</a>讲清楚了它的工作原理</div>'
               '<div><a href="https://waytoagi.feishu.cn/wiki/STUB">外网围观的十个玩法</a>作者整理了十个实测</div>')
        full = "<html><body><article><p>" + "这是知识库页自己写全的中文正文。" * 60 + "</p></article></body></html>"
        stub = '<html><body><article><p>导读一句话</p><a href="https://mp.weixin.qq.com/s/abc">原文链接</a></article></body></html>'
        pages = {"https://www.waytoagi.com/zh": home, "https://www.waytoagi.com/zh/blog/news-20260919": day,
                 "https://waytoagi.feishu.cn/wiki/FULL": full, "https://waytoagi.feishu.cn/wiki/STUB": stub}

        def fake_get(url, settings, params=None, ttl=None):
            return type("R", (), {"text": pages[url], "raise_for_status": lambda self: None})()

        source = {"name": "WayToAGI 知识库精选", "category": "中文AI精选主入口", "url": "https://www.waytoagi.com/zh",
                  "priority": 5, "role": "candidate", "days": 3}
        with patch("scrape_aihot.http_get", side_effect=fake_get):
            rows = __import__("scrape_aihot").fetch_waytoagi(source, {})
        self.assertEqual([row["title"] for row in rows], ["详解 Jev 模型", "外网围观的十个玩法"])
        self.assertEqual(rows[0]["content_status"], "fulltext")
        self.assertEqual(rows[1]["link"], "https://mp.weixin.qq.com/s/abc")
        self.assertEqual(rows[1]["wiki_link"], "https://waytoagi.feishu.cn/wiki/STUB")


class SitemapWatchTest(unittest.TestCase):
    def test_first_run_only_records_then_new_pages_become_candidates(self):
        import tempfile
        from unittest.mock import patch
        import scrape_aihot
        source = {"name": "Anthropic 官网新页面", "category": "官方发布", "type": "sitemap_watch", "url": "https://www.anthropic.com/sitemap.xml",
                  "path_exclude_pattern": "^/careers", "priority": 5, "role": "candidate", "official_release": True}
        page = lambda urls: type("R", (), {"text": "".join(f"<url><loc>{u}</loc></url>" for u in urls), "raise_for_status": lambda self: None})()
        old = ["https://www.anthropic.com/news/claude-opus-5", "https://www.anthropic.com/careers/x"]
        with tempfile.TemporaryDirectory() as tmp:
            settings = {"cache_dir": f"{tmp}/http"}
            with patch("scrape_aihot.http_get", return_value=page(old)):
                self.assertEqual(scrape_aihot.fetch_source(source, settings)[0], [])
            with patch("scrape_aihot.http_get", return_value=page([*old, "https://www.anthropic.com/claude-opus-5-5", "https://www.anthropic.com/careers/y"])):
                rows, error = scrape_aihot.fetch_source(source, settings)
        self.assertIsNone(error)
        self.assertEqual([row["link"] for row in rows], ["https://www.anthropic.com/claude-opus-5-5"])
        self.assertTrue(rows[0]["official_release"])
