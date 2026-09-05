from __future__ import annotations

import concurrent.futures
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from add_source import append_source
from curator import canonical_url, deduplicate, rank_candidates, score_item
import import_feedback as feedback_module
from report import generate_report
from scrape_aihot import clean_transcript, decode_html, delivery_mix_ready, embedded_original_date, fetch_web_index, hydrate, inbox_item, is_historical_content_duplicate, select_report_candidates


class CuratorTest(unittest.TestCase):
    def test_similar_series_titles_require_matching_full_content(self):
        first = {"title": "教你用WorkBuddy搞定公司日常行政工作", "link": "https://example.com/admin", "content_status": "fulltext", "content": "行政公文会议纪要用品领用登记" * 100}
        second = {"title": "教你用WorkBuddy搞定公司日常财务工作", "link": "https://example.com/finance", "content_status": "fulltext", "content": "银行流水发票金额应收应付对账" * 100}
        repost = {**first, "link": "https://example.com/repost"}
        self.assertEqual(len(deduplicate([first, second, repost])), 2)

    def test_document_format_list_is_not_multiple_news_events(self):
        base = {**self.items[0], "content": "公开完整实测，展示办公资料转成可下载文件的工作方法。" * 150, "summary": "普通办公文件输出实测"}
        article = score_item({**base, "title": "Notebook Agent 實測：直接產出 Word、Excel、PPT！"}, self.profile, now=self.now)
        roundup = score_item({**base, "title": "OpenAI发布模型、Google上线产品、腾讯完成融资"}, self.profile, now=self.now)
        self.assertNotIn("标题包含多个事件", article["penalty"])
        self.assertIn("标题包含多个事件", roundup["penalty"])

    def test_routine_update_in_summary_is_not_release_news(self):
        base = {**self.items[0], "published": "2026-08-01", "content": "使用公开表格完成日常办公任务，并核对处理前后的数据。" * 150, "summary": "台账更新、文档整理与年度资料维护"}
        article = score_item({**base, "title": "教你用WorkBuddy处理日常办公表格"}, self.profile, now=self.now)
        release = score_item({**base, "title": "腾讯发布办公产品新版"}, self.profile, now=self.now)
        self.assertNotIn("事件新闻已超过时效窗口", article["penalty"])
        self.assertIn("事件新闻已超过时效窗口", release["penalty"])

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

    def test_saturated_xiaohongshu_layout_is_rejected_despite_complete_material(self) -> None:
        item = {"title": "小红书图文自动排版 Skill 实战", "summary": "亲自实测，有完整过程与明确结果", "content": "作者解释了版式选择和调整过程。" * 250, "published": "2026-09-05", "source_name": "中文创作者", "source_priority": 5, "source_type": "web", "source_role": "candidate", "language": "zh", "maturity": "secondary", "content_form": "article", "content_status": "fulltext", "link": "https://example.com/layout"}
        result = score_item(item, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("小红书图文排版 Skill 已饱和", result["penalty"])

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
        result = rank_candidates([item], self.profile, now=datetime(2026, 9, 2, tzinfo=timezone.utc))[0]
        self.assertTrue(result["recommended"])
        self.assertNotIn("缺少明确 AI 对象", result["penalty"])

    def test_latest_feedback_rejects_questions_locks_and_thin_diaries(self) -> None:
        common = {
            "published": "2026-09-02T08:00:00Z",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "Codex多Agent工作流为什么只开会不干活",
                "summary": "社区讨论",
                "content": "我搭了一套多Agent流程，就想问问，到底是我这流程本身有病，还是额度不够？" * 50,
                "source_name": "作者 / V2EX社区讨论",
                "link": "https://example.com/question",
            },
            {
                **common,
                "title": "Kimi Work一个月使用复盘",
                "summary": "真实任务中的坑和红利",
                "content": "真香场景 Top 5，翻车场景 Top 5。点击解锁完整内容，关注后自动获取验证码。" * 50,
                "source_name": "中文博客",
                "link": "https://example.com/locked",
            },
            {
                **common,
                "title": "度假三周后，我意识到自己被AI工具奴役了",
                "summary": "个人反思",
                "content": "我没有想念它。它成了习惯性的拐杖，让我变笨了，也让我有点抑郁。效率的衔尾蛇让我仍然谨慎乐观。" * 50,
                "source_name": "个人博客",
                "link": "https://example.com/diary",
            },
        ]
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=now)}
        self.assertIn("社区提问求助帖", lookup["https://example.com/question"]["penalty"])
        self.assertIn("材料不完整", lookup["https://example.com/locked"]["penalty"])
        self.assertIn("只有个人感受与情绪", lookup["https://example.com/diary"]["penalty"])
        self.assertTrue(all(not item["recommended"] for item in lookup.values()))

    def test_ai_official_packaging_tone_is_rejected(self) -> None:
        item = {
            "title": "Agent 重塑软件商业的底层运行逻辑",
            "summary": "一个极具穿透力、精准击中痛点的判断",
            "content": ("这场变化正在彻底重写行业，形成自然的闭环，并释放有力的信号。" * 120),
            "published": "2026-08-19",
            "source_name": "二手整理站",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/official-ai-tone",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("AI 式官方包装语言过重", result["penalty"])

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
        self.assertNotIn("以 Benchmark", result["penalty"])

    def test_permission_governance_talk_is_too_distant_for_readers(self) -> None:
        item = {
            "title": "Agent 真正需要的是能撤销、限速和追责的行动预算",
            "summary": "Anthropic CI 团队的权限治理与工作负载事故",
            "content": "代理层身份、速率限制、撤销测试和聚合监控。" * 220,
            "published": "2026-08-22",
            "source_name": "Anthropic CI 团队",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/agent-budget",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("距离目标读者过远", result["penalty"])

    def test_formulaic_ai_headings_are_rejected_without_disclosure(self) -> None:
        item = {
            "title": "你的 AI 额度为什么总是不够用",
            "summary": "从 Context 管理出发的实用建议",
            "content": ("一句话结论。三个动作。第一招：丢掉。第二招：缩小。第三招：打折。记住两句自问。" * 90),
            "published": "2026-08-25",
            "source_name": "中文整理站",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/formulaic-ai-headings",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("AI 批量加工结构", result["penalty"])

    def test_author_discussing_ai_summaries_is_not_an_ai_summary_page(self) -> None:
        item = {
            "title": "前文字记者公开 Writing DNA Skill",
            "summary": "用语言学分层沉淀写作风格",
            "content": ("作者解释为什么 AI 总结往往只学会口头禅，以及怎样用原始语料修正。" * 160),
            "published": "2026-09-04",
            "source_name": "前文字记者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/writing-dna",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertNotIn("AI 总结或机器翻译感明显", result["penalty"])

    def test_deeply_nested_large_checklist_is_rejected(self) -> None:
        item = {
            "title": "我与 AI 协作的 19 条实战经验",
            "summary": "从需求到交付的完整方法",
            "content": ("12.1 文件安全。12.2 完整阅读。12.3 反编造。17.1 多会话。17.2 子代理。" * 80),
            "published": "2026-09-04",
            "source_name": "个人作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/nested-checklist",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("嵌套多级编号", result["penalty"])

    def test_model_versions_and_decimal_metrics_are_not_nested_headings(self) -> None:
        item = {
            "title": "去 AI 味不能只改词，真正暴露模型的是叙事架构",
            "summary": "研究覆盖六万多篇文本并给出三层修订方法",
            "content": ("Claude Fable 5.1、Opus 4.8 与 GPT-5.6 都有不同特征。"
                        "分类器达到 93.2% macro-F1，表层修改后从 95.5% 变成 93.9%。" * 80),
            "published": "2026-09-04",
            "source_name": "开源研究型 Skill",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/model-version-decimals",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertNotIn("嵌套多级编号", result["penalty"])

    def test_humanizer_tools_are_rejected_as_saturated_topic(self) -> None:
        item = {
            "title": "去 AI 味不能只改词：一个新的 Humanizer Skill",
            "summary": "通过叙事结构修复降低 AI 痕迹",
            "content": ("项目提供完整研究、规则、案例和测试。" * 220),
            "published": "2026-09-04",
            "source_name": "开源项目作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/another-humanizer",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("高度同质化", result["penalty"])

    def test_delivery_threshold_is_five(self) -> None:
        self.assertEqual(self.profile["minimum_delivery_count"], 5)
        self.assertEqual(self.profile["minimum_non_github_candidates"], 4)
        self.assertEqual(self.profile["maximum_github_candidates"], 1)

    def test_delivery_mix_cannot_be_all_github(self) -> None:
        github_items = [{"link": f"https://github.com/example/repo-{index}"} for index in range(5)]
        github_heavy = github_items[:4] + [{"link": "https://example.com/original-article"}]
        article_first = github_items[:1] + [{"link": f"https://example.com/article-{index}"} for index in range(4)]
        self.assertFalse(delivery_mix_ready(github_items, minimum_count=5, minimum_non_github=4, maximum_github=1))
        self.assertFalse(delivery_mix_ready(github_heavy, minimum_count=5, minimum_non_github=4, maximum_github=1))
        self.assertTrue(delivery_mix_ready(article_first, minimum_count=5, minimum_non_github=4, maximum_github=1))

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

    def test_coding_agent_instruction_maintenance_is_too_deep(self) -> None:
        item = {
            "title": "审计 AGENTS.md 和 CLAUDE.md 中过期的 Skill 规则",
            "summary": "检查常驻说明与 instruction file",
            "content": ("工具扫描深层配置并生成修复建议。" * 180),
            "published": "2026-09-04",
            "source_name": "中文工具作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/instruction-maintenance",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("普通读者无法使用", result["penalty"])

    def test_dense_quotes_and_em_dashes_are_rejected_as_ai_style(self) -> None:
        item = {
            "title": "一个 Agent 稳定性复盘",
            "summary": "作者记录真实项目经验",
            "content": ("模型说”完成了”——团队又问”真的完成了吗”——于是补充一轮”验证”——" * 90),
            "published": "2026-09-04",
            "source_name": "中文原创作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/punctuation-heavy",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("破折号与引号密度异常高", result["penalty"])

    def test_narrow_avatar_short_drama_and_obsolete_vision_workarounds_are_rejected(self) -> None:
        common = {
            "content": "作者提供完整中文说明、案例与验证结果。" * 180,
            "published": "2026-09-04",
            "source_name": "中文作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
        }
        items = [
            {**common, "title": "数字人视频如何完成口型同步", "summary": "自媒体制作", "link": "https://example.com/avatar"},
            {**common, "title": "AI 短剧制作工作流", "summary": "角色设定集与分镜", "link": "https://example.com/drama"},
            {**common, "title": "给纯文本 Agent 装上眼睛", "summary": "Vision Toolkit 外挂视觉", "link": "https://example.com/vision"},
            {**common, "title": "DeepSeek Harness 桌面工作台", "summary": "技术预览版后续可能破坏性更新", "link": "https://example.com/preview"},
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=datetime(2026, 9, 5, tzinfo=timezone.utc))}
        self.assertIn("过于垂直", lookup["https://example.com/avatar"]["penalty"])
        self.assertIn("过于垂直", lookup["https://example.com/drama"]["penalty"])
        self.assertIn("绕路方案", lookup["https://example.com/vision"]["penalty"])
        self.assertIn("技术预览", lookup["https://example.com/preview"]["penalty"])

    def test_personal_project_journey_is_rejected_even_with_methods(self) -> None:
        item = {
            "title": "我的 AI 原生开发方法",
            "summary": "包含可复用方法和操作规则",
            "content": ("我的 App 先改设置页。我在原型上反复调整。我的注意力放在界面上。"
                        "接着处理我的项目，这是我的路径，也是我的答案。" * 90),
            "published": "2026-09-04",
            "source_name": "个人作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/personal-project-journey",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("难以脱离作者经历", result["penalty"])

    def test_vendor_supplied_robotics_article_is_rejected(self) -> None:
        item = {
            "title": "机器人不能停下来等模型：在线强化学习进入真实部署",
            "summary": "VLA 通过 action chunk 提高投掷成功率",
            "content": ("World-Action Model 采用在线强化学习。本文由星尘智能提供，获授权转载，观点归原作者所有。" * 100),
            "published": "2026-09-04",
            "source_name": "中文科技媒体",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/vendor-robotics",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("普通读者难以使用", result["penalty"])
        self.assertIn("厂商供稿或授权转载", result["penalty"])

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
        self.assertFalse(result["recommended"])
        self.assertIn("AI 批量内容站或商业导流站", result["penalty"])

    def test_legal_authorship_controversy_is_not_long_term_practical_content(self) -> None:
        item = {
            "title": "AI 写完全文后，署名者还能算作者吗",
            "summary": "讨论作者身份、版权归属与责任归属",
            "content": ("文章结合版权局、法院案例和人工智能生成合成内容标识办法，讨论社会争议与 AI 参与声明。" * 100),
            "published": "2026-09-04",
            "source_name": "中文原创作者",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/ai-authorship-law",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("不符合长期干货调性", result["penalty"])

    def test_enterprise_recruiting_agent_case_study_is_rejected(self) -> None:
        item = {
            "title": "人力资源巨头用 AI Agent 完成百万次候选人对话，交付周期缩短一半",
            "summary": "大型企业招聘自动化案例",
            "content": ("企业通过招聘 Agent 扩大候选人沟通规模并优化交付。" * 180),
            "published": "2026-09-04",
            "source_name": "中文案例整理站",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/recruiting-agent-case",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("通稿式表述", result["penalty"])

    def test_scientific_discovery_tree_search_is_too_vertical(self) -> None:
        item = {
            "title": "树搜索驱动科学发现，小时级写出通用积分器",
            "summary": "低成本找出物理科学规律",
            "content": ("系统通过树搜索驱动科研工作流，发现新的物理科学规律。" * 180),
            "published": "2026-09-04",
            "source_name": "中文科技媒体",
            "source_priority": 5,
            "source_type": "web",
            "source_role": "candidate",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
            "link": "https://example.com/science-discovery-tree-search",
        }
        result = score_item(item, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
        self.assertFalse(result["recommended"])
        self.assertIn("大众切口偏弱", result["penalty"])

    def test_report_contains_review_controls(self) -> None:
        ranked = rank_candidates(self.items, self.profile, now=self.now)[:5]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            generate_report(ranked, path, "2026-08-25-120000")
            report = path.read_text()
            self.assertIn("应该入选", report)
            self.assertIn("不应入选", report)
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

    def test_latest_feedback_rejects_short_engineering_and_commercial_noise(self) -> None:
        common = {
            "summary": "中文完整材料",
            "content": "这是中文正文，包含真实数字和产品案例。" * 160,
            "published": "2026-09-03",
            "source_name": "中文媒体",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        rows = [
            {**common, "title": "腾讯WorkBuddy联名硬件来了", "link": "https://example.com/hardware"},
            {**common, "title": "智谱和 MiniMax，把大模型做成了两种生意", "link": "https://example.com/business"},
            {**common, "title": "AI 如何重构广告定向", "link": "https://example.com/ads"},
            {**common, "title": "MiniMax打开了AI视频的实时商业化路径", "link": "https://example.com/commercial"},
            {**common, "title": "成立不到一年连融三轮，这个睡眠 AI 产品火了", "link": "https://example.com/funding"},
            {**common, "title": "一个模型场景通吃，它的泛化能力有点狠", "link": "https://example.com/hype"},
        ]
        lookup = {item["link"]: item for item in rank_candidates(rows, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))}
        self.assertTrue(all(not item["recommended"] for item in lookup.values()))

        short_engineering = score_item(
            {
                **common,
                "title": "GitHub 用 AI Agent 优化工作流",
                "link": "https://example.com/short-engineering",
                "content": ("持续集成中的 MCP Schema 与 Pull Request Diff。" * 30),
            },
            self.profile,
            now=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertFalse(short_engineering["recommended"])
        self.assertIn("文章偏短且技术术语密集", short_engineering["penalty"])

    def test_latest_feedback_rejects_feature_lists_official_tone_and_education(self) -> None:
        common = {
            "published": "2026-08-31",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "ChatGPT Work 到底是什么？一份功能与风险拆解",
                "link": "https://example.com/features",
                "source_name": "中文科技站",
                "summary": "逐项介绍产品能力",
                "content": "联网执行、浏览器、共享工作区、子 Agent 和定时任务。" * 200,
            },
            {
                **common,
                "title": "AI 进入职场，真正要面对的可能不是机器",
                "link": "https://example.com/official",
                "source_name": "央视网",
                "summary": "公众调查",
                "content": "调查报告分析公众认知、受访者态度与就业治理，并提出公共政策建议。" * 180,
            },
            {
                **common,
                "title": "千名学生实验：ChatGPT 与课堂批判性思维训练",
                "link": "https://example.com/education",
                "source_name": "研究机构",
                "summary": "学生作业实验",
                "content": "大学生在学校课堂中使用 AI 完成作业。" * 50,
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=datetime(2026, 9, 4, tzinfo=timezone.utc))}
        self.assertIn("产品功能说明", lookup["https://example.com/features"]["penalty"])
        self.assertIn("官方调查与治理表达", lookup["https://example.com/official"]["penalty"])
        self.assertIn("教育方向", lookup["https://example.com/education"]["penalty"])
        self.assertIn("正文偏短", lookup["https://example.com/education"]["penalty"])
        self.assertTrue(all(not item["recommended"] for item in lookup.values()))

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

    def test_news_feature_is_not_a_writing_candidate(self) -> None:
        result = score_item(
            {
                "title": "AI 内容行业谁在赚钱、谁在出局",
                "link": "https://example.com/news-feature",
                "summary": "记者采访多位行业从业者",
                "content": "科创板日报记者采访，多位从业者表示行业正在变化，责编完成审校。" * 180,
                "published": "2026-08-18",
                "source_name": "科创板日报",
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
        self.assertFalse(result["recommended"])
        self.assertIn("记者采访和行业报道", result["penalty"])

    def test_personal_story_needs_a_transferable_artifact(self) -> None:
        common = {
            "content": "作者记录半年项目、真实体感、收入和具体过程。" * 300,
            "published": "2026-08-27",
            "source_name": "个人作者",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_form": "article",
            "content_status": "fulltext",
        }
        personal = score_item(
            {
                **common,
                "title": "付费用户过百之后，我为什么仍停掉 AI 社交产品",
                "summary": "个人创业项目的留存、收入与体感",
                "link": "https://example.com/personal-project",
            },
            self.profile,
            now=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        transferable = score_item(
            {
                **common,
                "title": "我写了个 AI 写作 Skill，第一次改稿就翻车了",
                "summary": "包含对照实验、语料测试和可复用方法",
                "link": "https://example.com/transferable",
            },
            self.profile,
            now=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertFalse(personal["recommended"])
        self.assertIn("作者本人项目经历", personal["penalty"])
        self.assertNotIn("作者本人项目经历", transferable["penalty"])

    def test_utf8_page_ignores_misleading_latin1_header(self) -> None:
        raw = "用 AI 让我们变笨了吗？认知债务与长期记忆".encode("utf-8")
        decoded = decode_html(raw, "ISO-8859-1")
        self.assertEqual(decoded, "用 AI 让我们变笨了吗？认知债务与长期记忆")

    def test_feedback_patterns_downrank_hype_broad_and_niche_topics(self) -> None:
        common = {
            "summary": "一篇已经完成中文整合的 AI 长文。",
            "content": "文章包含完整的事件、判断和案例。" * 250,
            "published": "2026-08-24T08:00:00Z",
            "source_name": "中文媒体",
            "source_priority": 4,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {**common, "title": "硅谷押注的下一个 Harness，是整个桌面操作系统", "link": "https://example.com/harness"},
            {**common, "title": "阿里视频大模型 Wan3.0 正式上线", "link": "https://example.com/wan"},
            {**common, "title": "匿名模型被扒出智谱血缘，也有人怀疑 Cursor", "link": "https://example.com/gossip"},
            {**common, "title": "AI 重塑商业，信任决定未来商业能走多远", "link": "https://example.com/broad"},
            {**common, "title": "一篇论文改写 AI 科研评价规则", "link": "https://example.com/science"},
            {**common, "title": "阿里达摩院推出肝癌 AI 模型", "link": "https://example.com/medical"},
        ]
        ranked = rank_candidates(items, self.profile, now=self.now)
        lookup = {item["link"]: item for item in ranked}
        self.assertTrue(lookup["https://example.com/harness"]["recommended"])
        self.assertTrue(lookup["https://example.com/wan"]["recommended"])
        self.assertIn("炒作或猎奇", lookup["https://example.com/gossip"]["penalty"])
        self.assertIn("缺少具体切口", lookup["https://example.com/broad"]["penalty"])
        self.assertIn("大众切口偏弱", lookup["https://example.com/science"]["penalty"])
        self.assertIn("大众切口偏弱", lookup["https://example.com/medical"]["penalty"])

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
            payload = {"exported_at": "2026-09-05T04:00:00Z", "reviews": {"x": {"status": "pending", "note": "待定"}}}
            feedback.write_text(json.dumps(payload))
            with patch.object(feedback_module, "ROOT", root), patch("builtins.print"):
                with patch("sys.argv", ["import_feedback.py", str(feedback), "--keep-source"]):
                    feedback_module.main()
                self.assertTrue(feedback.exists())
                with patch("sys.argv", ["import_feedback.py", str(feedback)]):
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

    def test_second_feedback_batch_prefers_authoritative_interview(self) -> None:
        common = {
            "content": "已完成中文整理的长文材料。" * 250,
            "published": "2026-08-25T08:00:00Z",
            "source_name": "中文媒体",
            "source_priority": 4,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "赛博义父 Tibo 最新访谈",
                "summary": "下一代 Agent 将走向云端",
                "content": "OpenAI Codex 负责人核心观点，以下是对话全文。" + common["content"],
                "link": "https://example.com/interview",
            },
            {
                **common,
                "title": "开源国产 8B 模型，比肩闭源 Image 2",
                "summary": "SenseNova U1.5 Lite",
                "link": "https://example.com/unnamed-model",
            },
            {
                **common,
                "title": "WAIC CONNECT 带你拿下马来西亚 AI 采购需求",
                "summary": "活动将在吉隆坡盛大开启",
                "link": "https://example.com/event",
            },
            {
                **common,
                "title": "出版社与小猿达成合作，学习智能体首落 AI 学习机",
                "summary": "双方签署合作协议",
                "link": "https://example.com/partnership",
            },
            {
                **common,
                "title": "前 TikTok 产品经理创业，AI 视频平台获千万美元融资",
                "summary": "融资与投资方信息",
                "link": "https://example.com/product-manager-funding",
            },
            {
                **common,
                "title": "具身创业里的香港教授们",
                "summary": "AI 创业者群像",
                "link": "https://example.com/people",
            },
        ]
        ranked = rank_candidates(items, self.profile, now=self.now)
        lookup = {item["link"]: item for item in ranked}
        self.assertTrue(lookup["https://example.com/interview"]["recommended"])
        self.assertIn("权威人物访谈", lookup["https://example.com/interview"]["reason"])
        self.assertIn("事件级别不足", lookup["https://example.com/unnamed-model"]["penalty"])
        self.assertIn("活动、采购或合作宣传稿", lookup["https://example.com/event"]["penalty"])
        self.assertIn("活动、采购或合作宣传稿", lookup["https://example.com/partnership"]["penalty"])
        self.assertIn("只有资本事件", lookup["https://example.com/product-manager-funding"]["penalty"])
        self.assertIn("纯人物群像", lookup["https://example.com/people"]["penalty"])

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
        self.assertNotIn("事件级别不足", lookup["https://example.com/agent-cost"]["penalty"])

    def test_headline_noise_is_rejected_without_body_keyword_accidents(self) -> None:
        common = {
            "summary": "AI 行业长文",
            "content": "一篇完整的中文文章。" * 120,
            "published": "2026-08-24T08:00:00Z",
            "source_name": "中文媒体",
            "source_priority": 4,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        titles = [
            "WRC 2026｜原生全模态世界模型：从模拟世界到交互世界",
            "有头有脸的大模型公司，集体搞起匿名公测",
            "MiniMax 做视频领域 Claude Code 的野心已经藏不住了",
            "从单点突破到全数 SOTA，阿里打响模型团战第一枪",
            "AI 音乐走到该怎么做，中国大模型为啥选最难的路",
            "字节 AI 产品向豆包集结，Agent 时代第一场巨头战役打响",
            "Gen1.5 模型带来重要进展：物理 AI 正在接近 GPT3 时刻",
            "OpenAI 辣椒芯干翻英伟达，老黄股价不跌反涨",
            "腾讯重金投入 AI 之后，混元 Hy4 preview 交出了什么答卷",
            "OpenAI 买几万台 Mac 搞强化训练，英伟达的活被苹果抢了",
            "VC 疯了，200 万现金冠军奖，又花 4000 万造了一座 AI 创业乌托邦",
            "世界模型突破三大瓶颈，让虚拟世界成为机器人训练场",
            "Coding 自由之后，人开始成为最大的瓶颈",
            "高德发布首个无长程依赖的万帧级流式 3D 重建模型 ABot-Recon",
            "范式与华为达成重磅算力战略合作，成为首批拥抱国产高端算力底座的 AI 企业",
            "32GB 大显存加持，英特尔锐炫 Pro B70 搞定 AI 漫剧创作",
            "AQuA：让量化研究 Agent 持续进化",
            "OpenAI 芯片实测跑分揭晓，为模型造芯片时代来了",
            "造物 100：AI 为爱做鸭、PLAUD 推新作、字节 TRAE 造了数字工牌",
        ]
        items = [{**common, "title": title, "link": f"https://example.com/noise-{index}"} for index, title in enumerate(titles)]
        ranked = rank_candidates(items, self.profile, now=self.now)
        self.assertTrue(all(not item["recommended"] for item in ranked))

    def test_event_recency_and_reader_distance_follow_latest_feedback(self) -> None:
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
        self.assertIn("距离目标读者过远", lookup["https://example.com/enterprise-cost"]["penalty"])
        self.assertIn("超过时效窗口", lookup["https://example.com/stale-outage"]["penalty"])

    def test_source_quality_and_generic_comparison_gate(self) -> None:
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
        self.assertIn("AI 批量内容站", lookup["https://kylinlabai.github.io/knowledge/review.html"]["penalty"])
        self.assertIn("商业导流站", lookup["https://claudemax.shop/blog/comparison"]["penalty"])
        self.assertIn("泛化工具清单或横评", lookup["https://trusted.example.com/generic-list"]["penalty"])
        self.assertTrue(lookup["https://trusted.example.com/controlled-test"]["recommended"])

    def test_reader_usability_and_long_term_value_gate(self) -> None:
        common = {
            "content": "一篇完整的中文深度文章。" * 250,
            "published": "2026-08-31T08:00:00Z",
            "source_name": "可信中文媒体",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "AI 本地部署不如官方版的元凶找到了：734 个依赖包",
                "summary": "深入 CUDA 核函数、logit 和 KV 缓存量化",
                "link": "https://example.com/too-technical",
            },
            {
                **common,
                "title": "OpenAI 内部，AI 建立了三代「文明」",
                "summary": "一次多 Agent 异常事件",
                "link": "https://example.com/one-off-story",
            },
            {
                **common,
                "title": "编辑部来了 AI 实习生：千问入职 20 天实习小结",
                "summary": "定时任务、选题评分系统与真实复盘",
                "link": "https://example.com/long-practice",
            },
            {
                **common,
                "title": "Claude 发布连接硬件的 MHS 标准",
                "summary": "统一设备描述与 Agent 调用边界",
                "link": "https://example.com/mhs-standard",
            },
        ]
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=self.now)}
        self.assertIn("目标读者难以理解或使用", lookup["https://example.com/too-technical"]["penalty"])
        self.assertIn("缺少长期回看价值", lookup["https://example.com/one-off-story"]["penalty"])
        self.assertTrue(lookup["https://example.com/long-practice"]["recommended"])
        self.assertIn("持续实践复盘", lookup["https://example.com/long-practice"]["reason"])
        self.assertTrue(lookup["https://example.com/mhs-standard"]["recommended"])

    def test_latest_feedback_separates_deep_frameworks_from_dense_implementation(self) -> None:
        common = {
            "content": "一篇已经完成中文整理的完整深度文章。" * 160,
            "published": "2026-08-28T08:00:00Z",
            "source_priority": 5,
            "source_type": "web",
            "language": "zh",
            "maturity": "secondary",
            "content_status": "fulltext",
        }
        items = [
            {
                **common,
                "title": "吴恩达访谈：AI最大的机遇并不在你想象的地方",
                "summary": "吴恩达讨论岗位任务、人类判断与年轻人的时代机会，以下是对话全文",
                "source_name": "信鸽中文",
                "link": "https://example.com/broad-interview",
            },
            {
                **common,
                "title": "AI写代码飞快，为何交付没有变快？小红书Muse的Agentic架构实践",
                "summary": "围绕业务本体、Agent Team、分层评测与失败分类的实践",
                "source_name": "InfoQ",
                "link": "https://example.com/implementation-heavy",
            },
            {
                **common,
                "title": "Agent评测漫谈：美团两年实践如何从结果、轨迹和组件分层评测",
                "summary": "解释结果正确不等于过程合格，以及如何构建真实评测体系",
                "source_name": "美团技术团队",
                "link": "https://example.com/long-horizon-framework",
            },
            {
                **common,
                "title": "Claude Code额度回落：Agent正在制造新的祖传代码屎山？",
                "summary": "解释Agent Loop、上下文压缩与设计理由丢失如何让局部合理补丁不断累积",
                "source_name": "雷锋网",
                "link": "https://example.com/codebase-debt",
            },
        ]
        now = datetime(2026, 9, 2, tzinfo=timezone.utc)
        lookup = {item["link"]: item for item in rank_candidates(items, self.profile, now=now)}
        self.assertFalse(lookup["https://example.com/broad-interview"]["recommended"])
        self.assertIn("访谈角度过宽", lookup["https://example.com/broad-interview"]["penalty"])
        self.assertFalse(lookup["https://example.com/implementation-heavy"]["recommended"])
        self.assertIn("系统实现概念过密", lookup["https://example.com/implementation-heavy"]["penalty"])
        self.assertTrue(lookup["https://example.com/long-horizon-framework"]["recommended"])
        self.assertIn("长期实践沉淀", lookup["https://example.com/long-horizon-framework"]["reason"])
        self.assertFalse(lookup["https://example.com/codebase-debt"]["recommended"])
        self.assertIn("系统实现概念过密", lookup["https://example.com/codebase-debt"]["penalty"])

    def test_next_batch_blocks_hype_updates_and_personnel_pr(self) -> None:
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
        self.assertTrue(all(not lookup[title]["recommended"] for title in rejected_titles))
        self.assertTrue(lookup["李飞飞发布：全球首个多模态世界模型"]["recommended"])

    def test_latest_feedback_requires_adaptable_and_information_dense_material(self) -> None:
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
        self.assertIn("工程门槛过高", lookup["https://example.com/code-heavy"]["penalty"])
        self.assertIn("理论或商业评论过多", lookup["https://example.com/abstract-business"]["penalty"])
        self.assertIn("播客缺少逐字稿", lookup["https://example.com/podcast-shownotes"]["penalty"])
        self.assertIn("框架化表达多于扎实证据", lookup["https://example.com/formulaic"]["penalty"])
        self.assertTrue(all(not item["recommended"] for item in lookup.values()))

    def test_latest_feedback_blocks_benchmarks_collages_translations_and_creator(self) -> None:
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
        self.assertIn("人物引语堆叠", lookup["https://example.com/citation-collage"]["penalty"])
        self.assertIn("个人 IP 已被明确排除", lookup["https://example.com/blocked-creator"]["penalty"])
        self.assertIn("机器翻译感明显", lookup["https://aipodcast.jasonlin.tech/example"]["penalty"])
        self.assertIn("Benchmark", lookup["https://example.com/benchmark"]["penalty"])
        self.assertTrue(all(not item["recommended"] for item in lookup.values()))


if __name__ == "__main__":
    unittest.main()
