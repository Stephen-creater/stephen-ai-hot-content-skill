"""回归测试集、能力测试集、逐题一致率、稳定性、上线前检查和评测报告。

测试用例就是 Stephen 审过的每一条候选（基准集 .local/eval/benchmark-v*.jsonl）。这个脚本在它上面做四件事：

  unmapped     列出带理由、但还没对应到具体题目的拒稿，交给 Agent 归类后用 map-reasons 写回
  map-reasons  把归类结果（哪条拒稿对应哪几道题）并进 .local/eval/suite/reason_map.json
  export       导出某个测试集的盲评材料（不带 Stephen 的结论），交给 AI 评审逐题回答
  record       把一个或几个评审的答案记成一次评测运行，结论由代码按题目规则算，不听评审自己说
  build-suites 用一次评测运行把测试用例分进回归测试集和能力测试集（回归测试集只加不减）
  retire       Stephen 口味变了时，把某条从回归测试集退役，必须写原因
  gate         上线前检查：规则改了就必须重跑回归测试集和负向用例并且全部通过，否则不许提交
  sources      信息源三项：你写的文章系统见过没有（广度）、每个源的通过率（质量）、每个源漏抓多少（吃干抹净）
  report       生成一页 HTML 评测报告

负向用例（suite 名 negative_batch）：从回归测试集里挑 10 条 Stephen 拒过的稿子凑成一批，告诉评审这批要交 10 条。
同一版规则不施压时判不推、施压时判推的，就是在凑数，上线前检查拦下。2026-09-22 a 批就是凑数放行的。

回归测试集：写成文章的候选，加上当前规则判对了、而且 Stephen 给了能对上题目的理由的用例。每个版本通过率不低于口味档案的
regression_pass_rate_min（95%），写成文章的必须全对，同一条不能连续两次判错。
能力测试集：其余有理由的用例，通过率只许涨不许跌。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_replay  # noqa: E402
from editorial_judgment import QUESTION_SET, QUESTIONS, SELF_VETO_PATTERNS, question_number, vetoes  # noqa: E402

ROOT = eval_replay.ROOT
SUITE_DIR = eval_replay.EVAL_DIR / "suite"
REASON_MAP = SUITE_DIR / "reason_map.json"
SUITES = SUITE_DIR / "suites.json"
RUNS = SUITE_DIR / "runs"
REPORT = SUITE_DIR / "report.html"
# 改了这些文件，AI 评审的判断就可能变，回归测试集要重跑。
RULE_FILES = (
    "SKILL.md", "references/editorial-judgment.md", "references/editorial-calibration-cases.md",
    "resources/review_questions.json", "resources/editorial_profile.json",
    "scripts/editorial_judgment.py", "scripts/curator.py",
)
# 写成文章的对应关系，这几种算确定，进回归测试集；probable 只进能力测试集。
SURE_ADOPTION = {"sure", "certain", "already_written"}
CHECK_IDS = [q["id"] for q in QUESTIONS] + [c["id"] for c in QUESTION_SET["script_checks"]]
NEGATIVE_BATCH_SIZE = 10
ARTICLE_TRACE = SUITE_DIR / "article_trace.json"


def rules_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in RULE_FILES:
        path = root / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b"")
    return digest.hexdigest()[:16]


def reason_to_checks() -> dict[str, list[str]]:
    """审核页原因按钮 → 它对应的题目和脚本检查。"""
    mapping: dict[str, list[str]] = defaultdict(list)
    for entry in [*QUESTIONS, *QUESTION_SET["script_checks"]]:
        for reason in entry.get("reasons", []):
            mapping[reason].append(entry["id"])
    return dict(mapping)


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def expected_groups(item: dict, reason_map: dict[str, dict]) -> list[list[str]]:
    """Stephen 这条拒稿说的是哪几件事，每件事对应一组题目。一组里评审只要否决了一道，就算和他一致。"""
    buttons = reason_to_checks()
    groups = [buttons[tag] for tag in item.get("reasons") or [] if tag in buttons]
    mapped = reason_map.get(item["id"])
    if mapped and mapped.get("kind") == "mapped" and mapped.get("ids"):
        groups.append([check for check in mapped["ids"] if check in CHECK_IDS])
    return [group for group in groups if group]


def case_kind(item: dict, reason_map: dict[str, dict], adoptions: dict[str, dict]) -> str:
    """adopted / selected / rejected_mapped / rejected_unmapped / weak"""
    if item["id"] in adoptions:
        return "adopted" if str(adoptions[item["id"]].get("confidence", "sure")) in SURE_ADOPTION else "adopted_probable"
    if item["label"] == "selected":
        return "selected"
    if item["label_strength"] == "weak":
        return "weak"
    kind = (reason_map.get(item["id"]) or {}).get("kind")
    if expected_groups(item, reason_map):
        return "rejected_mapped"
    return "weak" if kind in {"batch_level", "unclear"} else "rejected_unmapped"


def load_cases() -> tuple[str, list[dict], dict[str, dict], dict[str, dict]]:
    path, items = eval_replay.load_benchmark()
    return path.name, items, load_json(REASON_MAP, {}), eval_replay.load_adoptions()


def unmapped(items: list[dict], reason_map: dict[str, dict]) -> list[dict]:
    return [
        {"id": item["id"], "title": item["candidate"].get("title"), "tags": item["reasons"], "note": item["note"]}
        for item in items
        if item["label"] == "rejected" and item["label_strength"] == "strong" and item["id"] not in reason_map
        and not expected_groups(item, reason_map)
    ]


def merge_reasons(rows: list[dict], reason_map: dict[str, dict]) -> dict[str, dict]:
    for row in rows:
        kind = row.get("kind")
        if kind not in {"mapped", "unmapped", "batch_level", "unclear"}:
            raise SystemExit(f"{row.get('id')} 的 kind 必须是 mapped、unmapped、batch_level 或 unclear")
        unknown = [check for check in row.get("ids", []) if check not in CHECK_IDS]
        if unknown:
            raise SystemExit(f"{row['id']} 用了不存在的题目：{unknown}")
        reason_map[str(row["id"])] = {"kind": kind, "ids": row.get("ids", []), "gap": row.get("gap", "")}
    return reason_map


def negative_batch_ids(items: list[dict], suites: dict, profile: dict) -> set[str]:
    """回归测试集里 Stephen 拒过、脚本拦不住、必须靠评审读全文的稿子，按规则指纹轮换着挑 10 条。"""
    by_id = {item["id"]: item for item in items}
    pool = [by_id[i] for i in suites.get("regression", []) if i in by_id and by_id[i]["label"] == "rejected" and by_id[i]["judgeable"]]
    pool = [item for item in pool if not script_blocked(item, profile)]
    seed = rules_fingerprint()
    pool.sort(key=lambda item: hashlib.sha256((seed + item["id"]).encode()).hexdigest())
    return {item["id"] for item in pool[:NEGATIVE_BATCH_SIZE]}


# ---------- 评测运行 ----------

def script_blocked(item: dict, profile: dict) -> bool:
    return eval_replay.gate_blocked(item, profile)


def verdict_for(item: dict, result: dict | None, profile: dict) -> dict:
    """结论由代码按规则算：脚本检查拦下、任何一题答到否决答案或说不清、疑点里写了否决理由，都算不推荐。"""
    if script_blocked(item, profile):
        return {"verdict": "reject", "by": ["script"], "answers": {}}
    if not result:
        return {"verdict": "missing", "by": [], "answers": {}}
    answers = result.get("answers") or {}
    hits = vetoes(answers)
    notes = " ".join(str((answers.get(q["id"]) or {}).get("note", "")) for q in QUESTIONS)
    doubt = str(result.get("counterargument", ""))
    for pattern, label in SELF_VETO_PATTERNS:
        if re.search(pattern, doubt if label.startswith("疑点") else f"{notes} {doubt}"):
            hits.append("self_veto")
    return {"verdict": "reject" if hits else "recommend", "by": hits, "answers": answers}


def expected_verdict(item: dict) -> str:
    return "recommend" if item["label"] == "selected" else "reject"


def export_cases(items: list[dict], ids: set[str], profile: dict) -> tuple[list[dict], list[str]]:
    """盲评材料：不带 Stephen 的结论。脚本已经拦下的不用 AI 读，单独列出来。"""
    adoptions = eval_replay.load_adoptions()
    articles = eval_replay.published_articles()
    rows, skipped = [], []
    for item in items:
        if item["id"] not in ids:
            continue
        if script_blocked(item, profile):
            skipped.append(item["id"])
            continue
        exclude = {str(adoptions.get(item["id"], {}).get("article", ""))} if item["id"] in adoptions else set()
        candidate = item["candidate"]
        rows.append({
            "id": item["id"],
            "title": candidate.get("source_title") or candidate.get("title"),
            "link": candidate.get("link"),
            "source_name": candidate.get("source_name"),
            "published": candidate.get("published"),
            "image_count": candidate.get("image_count"),
            "video_count": candidate.get("video_count"),
            "review_date": eval_replay.review_day(item),
            "written_before_review": eval_replay.written_before(eval_replay.review_day(item), exclude, articles),
            "content": candidate.get("content"),
        })
    return rows, skipped


def record_run(items: list[dict], ids: set[str], suite: str, judge_files: list[Path], model: str, profile: dict, benchmark: str, rules_root: Path = ROOT) -> dict:
    by_id = {item["id"]: item for item in items if item["id"] in ids}
    trials = []
    for path in judge_files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        results = {str(row.get("id")): row for row in raw if isinstance(row, dict)}
        trials.append({"judge": path.name, "results": {item_id: verdict_for(item, results.get(item_id), profile) for item_id, item in by_id.items()}})
    return {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + suite,
        "at": datetime.now(timezone.utc).isoformat(), "commit": eval_replay.git_head(), "fingerprint": rules_fingerprint(rules_root),
        "model": model, "suite": suite, "benchmark": benchmark, "case_ids": sorted(ids), "trials": trials,
    }


def save_run(run: dict) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{run['run_id']}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_runs() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RUNS.glob("*.json"))] if RUNS.exists() else []


# ---------- 打分 ----------

def score_run(run: dict, items: list[dict], reason_map: dict[str, dict]) -> dict:
    by_id = {item["id"]: item for item in items}
    per_case = {}
    for item_id in run["case_ids"]:
        item = by_id.get(item_id)
        if not item:
            continue
        results = [trial["results"].get(item_id) for trial in run["trials"]]
        results = [r for r in results if r and r["verdict"] != "missing"]
        passes = [r["verdict"] == expected_verdict(item) for r in results]
        per_case[item_id] = {"expected": expected_verdict(item), "trials": len(results), "passed": sum(passes),
                             "all_pass": bool(results) and all(passes), "any_pass": any(passes),
                             "verdicts": [r["verdict"] for r in results], "by": [r["by"] for r in results]}
    judged = [c for c in per_case.values() if c["trials"]]
    # 逐题一致率：Stephen 拒稿时点名的那组题，评审至少否决一道算一致；Stephen 选中的，评审没有否决这道题算一致。
    agree: dict[str, Counter] = {check: Counter() for check in CHECK_IDS}
    for item_id, case in per_case.items():
        item = by_id[item_id]
        for trial in run["trials"]:
            result = trial["results"].get(item_id)
            if not result or result["verdict"] == "missing":
                continue
            vetoed = set(result["by"])
            if "script" in vetoed:
                vetoed |= {c["id"] for c in QUESTION_SET["script_checks"]}
            answers = result.get("answers") or {}
            for question in QUESTIONS:
                if (answers.get(question["id"]) or {}).get("answer") == "unsure":
                    agree[question["id"]]["unsure"] += 1
            if item["label"] == "selected":
                for question in QUESTIONS:
                    if question["id"] in answers:
                        agree[question["id"]]["total"] += 1
                        agree[question["id"]]["agree"] += question["id"] not in vetoed
            else:
                for group in expected_groups(item, reason_map):
                    hit = bool(set(group) & vetoed)
                    for check in group:
                        agree[check]["total"] += 1
                        agree[check]["agree"] += hit
    per_question = {
        check: {"total": c["total"], "agree_rate": round(c["agree"] / c["total"], 3) if c["total"] else None, "unsure": c["unsure"]}
        for check, c in agree.items()
    }
    # 两个以上评审时的人人一致率（按结论算）。
    inter = None
    if len(run["trials"]) >= 2:
        pairs = [len(set(c["verdicts"])) == 1 for c in judged if c["trials"] >= 2]
        inter = {"cases": len(pairs), "rate": round(sum(pairs) / len(pairs), 3) if pairs else None}
    return {
        "cases": len(judged),
        "pass_at_1": round(sum(c["passed"] / c["trials"] for c in judged) / len(judged), 3) if judged else None,
        "pass_all_trials": round(sum(c["all_pass"] for c in judged) / len(judged), 3) if judged else None,
        "failed": sorted(item_id for item_id, c in per_case.items() if c["trials"] and not c["all_pass"]),
        "flipping": sorted(item_id for item_id, c in per_case.items() if c["trials"] >= 2 and 0 < c["passed"] < c["trials"]),
        "per_question": per_question, "inter_rater": inter, "per_case": per_case,
    }


# ---------- 回归测试集和能力测试集 ----------

def build_suites(run: dict, items: list[dict], reason_map: dict[str, dict], previous: dict | None) -> dict:
    adoptions = eval_replay.load_adoptions()
    score = score_run(run, items, reason_map)
    previous = previous or {"regression": [], "capability": [], "retired": {}}
    retired = previous.get("retired", {})
    regression = set(previous.get("regression", [])) - set(retired)
    capability = set(previous.get("capability", []))
    for item in items:
        if item["id"] in retired or not item["judgeable"]:
            continue
        kind = case_kind(item, reason_map, adoptions)
        if kind == "weak":
            continue
        case = score["per_case"].get(item["id"])
        if kind == "adopted" or (kind in {"selected", "rejected_mapped"} and case and case["all_pass"]):
            regression.add(item["id"])  # 只加不减
            capability.discard(item["id"])
        elif item["id"] not in regression:
            capability.add(item["id"])
    return {"built_from": run["run_id"], "at": datetime.now(timezone.utc).isoformat(),
            "regression": sorted(regression), "capability": sorted(capability), "retired": retired}


# ---------- 上线前检查 ----------

def gate(items: list[dict], suites: dict, runs: list[dict], reason_map: dict[str, dict], profile: dict) -> list[str]:
    problems = []
    if not suites.get("regression"):
        return ["还没有回归测试集，先跑一次全量评测再 build-suites"]
    by_id = {item["id"]: item for item in items}
    # 1. 脚本层：回归测试集里的好稿不能被脚本误拦。
    for item_id in suites["regression"]:
        item = by_id.get(item_id)
        if item and item["label"] == "selected" and script_blocked(item, profile):
            problems.append(f"脚本检查误拦了回归测试集里的好稿：{item['candidate'].get('title')}")
    # 2. 规则改了，就必须用现在的规则重跑回归测试集，而且全部通过。
    fingerprint = rules_fingerprint()
    covering = [run for run in runs if run["suite"] != "negative_batch" and run["fingerprint"] == fingerprint and set(suites["regression"]) <= set(run["case_ids"])]
    if not covering:
        problems.append("规则文件改过了，还没有用现在的规则重跑回归测试集（export --suite regression，评审答完后 record）")
    else:
        # AI 评审每次答案有波动（同一条跑三次约九成结论一致），所以不要求 100%：按 Anthropic 对非确定性任务的建议，
        # 通过率不低于口味档案的 regression_pass_rate_min；写成文章的必须全对；同一条连续两次回归都判错，算真退步。
        regression = set(suites["regression"])
        score = score_run(covering[-1], items, reason_map)
        failed = [item_id for item_id in score["failed"] if item_id in regression]
        judged = [item_id for item_id in regression if score["per_case"].get(item_id, {}).get("trials")]
        rate = 1 - len(failed) / len(judged) if judged else 0
        minimum = float(profile.get("regression_pass_rate_min", 0.95))
        if rate < minimum:
            problems.append(f"回归测试集通过率 {rate:.1%}，低于 {minimum:.0%}")
        adoptions = eval_replay.load_adoptions()
        previous = [run for run in runs if run is not covering[-1] and regression & set(run["case_ids"]) and run["run_id"] < covering[-1]["run_id"]]
        failed_before = set(score_run(previous[-1], items, reason_map)["failed"]) if previous else set()
        for item_id in failed:
            item = by_id.get(item_id, {})
            title = (item.get("candidate") or {}).get("title")
            if item_id in adoptions:
                problems.append(f"写成文章的候选判错了：{title}")
            elif item_id in failed_before:
                problems.append(f"回归测试集连续两次判错：{title}（Stephen 的结论是 {expected_verdict(item)}）")
    # 3. 负向用例：一批全是拒稿，还告诉评审要交 10 条。拦的是压力下放水：同一版规则不施压时判不推、施压时判推。
    # 两边都推的是回归测试集里的普通判错（评审本身约一成的波动），已经由通过率和“连续两次判错”管，这里只列出来。
    # 2026-09-23 第一次上线前检查时，负向用例推了一条“泛泛而谈”的边界稿，它在不施压的四轮里也是推、不推交替，改成现在这样。
    negative = [run for run in runs if run["suite"] == "negative_batch" and run["fingerprint"] == fingerprint]
    if not negative:
        problems.append("规则文件改过了，还没有用现在的规则跑负向用例（export --suite negative_batch）")
    else:
        calm = covering[-1]["trials"][0]["results"] if covering and covering[-1]["trials"] else {}
        pushed = sorted({item_id for trial in negative[-1]["trials"] for item_id, result in trial["results"].items() if result["verdict"] == "recommend"})
        for item_id in pushed:
            title = (by_id.get(item_id, {}).get("candidate") or {}).get("title")
            if (calm.get(item_id) or {}).get("verdict") != "recommend":
                problems.append(f"负向用例里，不施压时判不推、一说要凑 10 条就推了，是在凑数：{title}")
            else:
                print(f"提示：负向用例推了 {title}，不施压时也推，算回归测试集里的普通判错")
    # 4. 能力测试集不许比上一版低。
    capability_runs = [run for run in runs if set(suites.get("capability", [])) & set(run["case_ids"])]
    if len(capability_runs) >= 2 and capability_runs[-1]["fingerprint"] == fingerprint:
        now = score_run(capability_runs[-1], items, reason_map)
        before = next((score_run(run, items, reason_map) for run in reversed(capability_runs[:-1]) if run["fingerprint"] != fingerprint), None)
        if before and now["pass_at_1"] is not None and before["pass_at_1"] is not None and now["pass_at_1"] < before["pass_at_1"] - 0.02:
            problems.append(f"能力测试集通过率从 {before['pass_at_1']} 降到 {now['pass_at_1']}")
    return problems


# ---------- 信息源 ----------

def source_sections(root: Path = ROOT) -> str:
    """广度、质量、吃干抹净三张表，拼进评测报告。"""
    import source_yield
    esc = html.escape
    parts = []
    trace = load_json(ARTICLE_TRACE, [])
    articles = [row for row in trace if row.get("kind") == "article"]
    if articles:
        # 系统第一批选题是 8.25 跑的，之前写的文章不算漏抓；Stephen 自己原创的也不指望系统找到。
        def before_system(row: dict) -> bool:
            match = re.match(r"(\d{1,2})\.(\d{1,2})\b", str(row.get("article", "")))
            return bool(match) and (int(match.group(1)), int(match.group(2))) < (8, 25)
        early = [row for row in articles if before_system(row)]
        original = [row for row in articles if not before_system(row) and "原创" in str(row.get("channel", ""))]
        counted = [row for row in articles if row not in early and row not in original]
        counts = Counter(row.get("status") for row in counted)
        channels = Counter(re.split(r"[：:（(]", str(row.get("channel") or "不明"))[0] for row in counted if row.get("status") == "not_seen")
        parts.append(f"<h3>广度：你写的文章，系统事先见过几篇</h3><p>正式文章 {len(articles)} 篇，其中系统上线（8.25）前写的 {len(early)} 篇、你自己原创的 {len(original)} 篇不算。"
                     f"剩下 {len(counted)} 篇：推给过你 {counts['recommended']} 篇，抓到了但没推 {counts['seen_not_recommended']} 篇，根本没抓到 {counts['not_seen']} 篇。</p>")
        parts.append("<table><tr><th>没抓到的文章，你大概从哪看到的</th><th>篇数</th></tr>" + "".join(f"<tr><td>{esc(str(k))}</td><td>{v}</td></tr>" for k, v in channels.most_common(12)) + "</table>")
        missed = [row for row in articles if row.get("status") != "recommended"]
        parts.append("<details><summary>逐篇明细</summary><table><tr><th>文章</th><th>情况</th><th>渠道</th><th>依据</th></tr>" + "".join(
            f"<tr><td>{esc(str(r['article']))}</td><td>{esc({'recommended': '推过', 'seen_not_recommended': '抓到没推', 'not_seen': '没抓到'}.get(r['status'], str(r['status'])))}</td><td>{esc(str(r.get('channel', '')))}</td><td>{esc(str(r.get('evidence', '')))}</td></tr>" for r in missed) + "</table></details>")
    feedback = root / ".local" / "editorial_feedback.jsonl"
    if feedback.exists():
        rows = [row for row in source_yield.source_yield(feedback) if row["decided"] >= 3]
        parts.append("<h3>质量：每个源推上来的，你通过几条（至少审过 3 条的源）</h3><table><tr><th>来源</th><th>审过</th><th>通过</th></tr>" + "".join(
            f"<tr><td>{esc(r['source'])}</td><td>{r['decided']}</td><td>{r['selected']}</td></tr>" for r in rows[:15]) + "</table>")
        zero = [r for r in source_yield.source_yield(feedback) if r["decided"] >= 5 and r["selected"] == 0]
        if zero:
            parts.append("<p>审过 5 条以上、一条没通过的源：" + esc("、".join(f"{r['source']}（{r['decided']}）" for r in zero)) + "</p>")
    runs = sorted(p for p in (root / ".local" / "work").glob("*/*/run.json") if p.parent.parent.name != "fixture")
    latest = next((json.loads(p.read_text(encoding="utf-8")) for p in reversed(runs) if "source_funnel" in p.read_text(encoding="utf-8")), None)
    if latest:
        leaky = [row for row in latest["source_funnel"] if row["listed"] > row["fulltext"]][:15]
        parts.append(f"<h3>吃干抹净：最近一轮抓取（{esc(latest['generated_at'][:16])}）列出来却没拿到全文的</h3><table><tr><th>来源</th><th>列出</th><th>拿到全文</th><th>没拿到的原因</th></tr>" + "".join(
            f"<tr><td>{esc(r['source'])}</td><td>{r['listed']}</td><td>{r['fulltext']}</td><td>{esc('；'.join(f'{k} {v}' for k, v in r['missing_text'].items()))}</td></tr>" for r in leaky) + "</table>")
    else:
        parts.append("<h3>吃干抹净</h3><p>2026-09-22 起抓取才按源记录列出和拿到全文的条数，下一批跑完这里才有数。</p>")
    return "".join(parts)


# ---------- 报告 ----------

def label_of(check: str) -> str:
    """题目 id 换成“第 N 题”，脚本检查和放行说辞换成中文。"""
    if check in {q["id"] for q in QUESTIONS}:
        return f"第 {question_number(check)} 题"
    return {"script": "脚本检查", "self_veto": "疑点里有放行说辞"}.get(check, check)


def pct(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def render_report(items: list[dict], suites: dict, runs: list[dict], reason_map: dict[str, dict], profile: dict, extra: dict | None = None) -> str:
    by_id = {item["id"]: item for item in items}
    fingerprint = rules_fingerprint()
    problems = gate(items, suites, runs, reason_map, profile)
    regression_ids, capability_ids = set(suites.get("regression", [])), set(suites.get("capability", []))

    def latest(ids: set[str]) -> tuple[dict | None, dict | None]:
        for run in reversed(runs):
            if ids and ids <= set(run["case_ids"]) | set():
                return run, score_run(run, items, reason_map)
        for run in reversed(runs):
            if ids & set(run["case_ids"]):
                return run, score_run(run, items, reason_map)
        return None, None

    reg_run, reg = latest(regression_ids)
    cap_run, cap = latest(capability_ids)
    stability = next((score_run(run, items, reason_map) for run in reversed(runs) if len(run["trials"]) >= 3), None)
    forward_rows = [json.loads(line) for line in eval_replay.FORWARD.read_text(encoding="utf-8").splitlines() if line.strip()] if eval_replay.FORWARD.exists() else []
    forward = eval_replay.forward_report(forward_rows)
    esc = html.escape

    def subset_rate(score: dict | None, ids: set[str]) -> str:
        if not score:
            return "—"
        cases = [c for item_id, c in score["per_case"].items() if item_id in ids and c["trials"]]
        return f"{sum(c['all_pass'] for c in cases)}/{len(cases)}" if cases else "—"

    rows = []
    source = reg or cap
    for question in QUESTIONS:
        stat = (source or {}).get("per_question", {}).get(question["id"], {})
        rate = stat.get("agree_rate")
        flag = "low" if rate is not None and rate < 0.85 else ""
        rows.append(f"<tr class='{flag}'><td>{question_number(question['id'])}</td><td>{esc(question['text'])}</td><td>{esc('、'.join(question.get('reasons', [])))}</td><td>{stat.get('total', 0)}</td><td>{pct(rate)}</td><td>{stat.get('unsure', 0)}</td></tr>")
    failures = []
    if reg:
        for item_id in reg["failed"]:
            if item_id in regression_ids:
                item = by_id.get(item_id, {})
                case = reg["per_case"][item_id]
                verdict = "推" if case["verdicts"] and case["verdicts"][-1] == "recommend" else "不推"
                vetoed = "、".join(label_of(check) for check in (case["by"][-1] if case["by"] else [])) or "没有否决"
                failures.append(f"<li><b>{esc(str((item.get('candidate') or {}).get('title')))}</b>：Stephen {'选了' if case['expected'] == 'recommend' else '拒了'}，评审判{verdict}（{esc(vetoed)}）</li>")
    flipping = [by_id[i]["candidate"].get("title") for i in (stability or {}).get("flipping", []) if i in by_id]
    extra = extra or {}
    sections = "".join(f"<h2>{esc(title)}</h2>{body}" for title, body in extra.items())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>选题 Skill 评测报告</title>
<style>body{{font-family:"PingFang SC",sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1d1d1f;line-height:1.7}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}.tile{{border:1px solid #ddd;border-radius:8px;padding:10px 12px}}
.tile b{{display:block;font-size:22px}}.bad{{background:#fdecea;border-color:#e6a19a}}.good{{background:#eaf6ee;border-color:#9ccfae}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #ddd;padding:5px 7px;text-align:left;vertical-align:top}}th{{background:#f4f4f6}}
tr.low td{{background:#fff4e5}}.muted{{color:#666;font-size:13px}}</style></head><body>
<h1>选题 Skill 评测报告</h1>
<p class="muted">生成于 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · 规则指纹 {fingerprint} · 提交 {eval_replay.git_head()}</p>
<div class="tiles">
<div class="tile {'bad' if problems else 'good'}">上线前检查<b>{'不通过' if problems else '通过'}</b></div>
<div class="tile">回归测试集<b>{subset_rate(reg, regression_ids)}</b><span class="muted">至少 95%，写成文章的全对</span></div>
<div class="tile">能力测试集<b>{subset_rate(cap, capability_ids)}</b><span class="muted">只许涨</span></div>
<div class="tile">时间外测试<b>{forward.get('judge_hits', 0)}/{forward.get('judge_recommended', 0)}</b><span class="muted">评审推荐的里 Stephen 选了几条，共 {forward.get('batches', 0)} 批</span></div>
<div class="tile">人人一致率<b>{pct(((reg or cap or {}).get('inter_rater') or {}).get('rate'))}</b><span class="muted">两个评审结论一样的比例</span></div>
<div class="tile">稳定性<b>{pct((stability or {}).get('pass_all_trials'))}</b><span class="muted">同一条跑 3 次都判对的比例</span></div>
</div>
{'<h2>上线前检查没过的原因</h2><ul>' + ''.join(f'<li>{esc(p)}</li>' for p in problems) + '</ul>' if problems else ''}
{'<h2>回归测试集里判错的</h2><ul>' + ''.join(failures) + '</ul>' if failures else ''}
<h2>每道题和 Stephen 一致的比例</h2>
<p class="muted">Stephen 拒稿时点名的题，评审也否决了算一致；Stephen 选中的稿，评审没有否决这道题算一致。低于 85% 的行标黄，要么题目写得不清楚，要么缺例子。</p>
<table><tr><th>题</th><th>问题</th><th>对应原因按钮</th><th>样本</th><th>一致率</th><th>说不清</th></tr>{''.join(rows)}</table>
{'<h2>三次判得不一样的稿子</h2><ul>' + ''.join(f'<li>{esc(str(t))}</li>' for t in flipping) + '</ul>' if flipping else ''}
{sections}
<p class="muted">回归测试集 {len(regression_ids)} 条，能力测试集 {len(capability_ids)} 条，退役 {len(suites.get('retired', {}))} 条。数据在 .local/eval/suite/。</p>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("unmapped")
    mp = sub.add_parser("map-reasons")
    mp.add_argument("file", type=Path)
    ex = sub.add_parser("export")
    ex.add_argument("--suite", required=True, help="regression、capability、all（全部有理由的用例）、validation、test，或者批次 ID")
    ex.add_argument("--output", type=Path, required=True)
    ex.add_argument("--chunks", type=int, default=1, help="拆成几份，给几个评审并行读")
    rec = sub.add_parser("record")
    rec.add_argument("--suite", required=True)
    rec.add_argument("--model", required=True)
    rec.add_argument("--judges", type=Path, nargs="+", required=True, help="每个文件是一个评审（一次试验）对这个测试集的全部答案；同一评审拆成几份的先合并")
    rec.add_argument("--rules-root", type=Path, default=ROOT, help="评审读的是哪份规则（快照目录），用它算规则指纹")
    bs = sub.add_parser("build-suites")
    bs.add_argument("--run", required=True)
    rt = sub.add_parser("retire")
    rt.add_argument("id")
    rt.add_argument("--why", required=True)
    sub.add_parser("gate")
    sub.add_parser("sources")
    sub.add_parser("report")
    args = parser.parse_args()
    profile = json.loads(eval_replay.PROFILE.read_text(encoding="utf-8"))
    benchmark, items, reason_map, adoptions = load_cases()
    suites = load_json(SUITES, {"regression": [], "capability": [], "retired": {}})

    def suite_ids(name: str) -> set[str]:
        judgeable = {item["id"] for item in items if item["judgeable"]}
        if name in {"regression", "capability"}:
            return set(suites.get(name, [])) & judgeable
        if name == "negative_batch":
            return negative_batch_ids(items, suites, profile)
        if name == "all":
            return {item["id"] for item in items if item["judgeable"] and case_kind(item, reason_map, adoptions) != "weak"}
        if name in eval_replay.SPLITS:
            return {item["id"] for item in items if item["judgeable"] and item["split"] == name and case_kind(item, reason_map, adoptions) != "weak"}
        return {item["id"] for item in items if item["batch"] == name}

    if args.command == "unmapped":
        print(json.dumps(unmapped(items, reason_map), ensure_ascii=False, indent=1))
    elif args.command == "map-reasons":
        SUITE_DIR.mkdir(parents=True, exist_ok=True)
        merged = merge_reasons(json.loads(args.file.read_text(encoding="utf-8")), reason_map)
        REASON_MAP.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写入 {len(merged)} 条拒稿理由的归类：{REASON_MAP}")
    elif args.command == "export":
        rows, skipped = export_cases(items, suite_ids(args.suite), profile)
        chunks = max(1, args.chunks)
        for index in range(chunks):
            part = rows[index::chunks]
            path = args.output if chunks == 1 else args.output.with_name(f"{args.output.stem}-{index + 1}{args.output.suffix}")
            path.write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{path}：{len(part)} 条")
        print(f"脚本检查已拦下、不用 AI 读的：{len(skipped)} 条")
    elif args.command == "record":
        run = record_run(items, suite_ids(args.suite), args.suite, args.judges, args.model, profile, benchmark, args.rules_root)
        path = save_run(run)
        score = score_run(run, items, reason_map)
        print(json.dumps({k: v for k, v in score.items() if k != "per_case"}, ensure_ascii=False, indent=1))
        print(f"已记录：{path}")
    elif args.command == "build-suites":
        run = next((r for r in load_runs() if r["run_id"] == args.run), None)
        if not run:
            raise SystemExit(f"找不到评测运行 {args.run}")
        built = build_suites(run, items, reason_map, suites if suites.get("regression") else None)
        SUITE_DIR.mkdir(parents=True, exist_ok=True)
        SUITES.write_text(json.dumps(built, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"回归测试集 {len(built['regression'])} 条，能力测试集 {len(built['capability'])} 条")
    elif args.command == "retire":
        if args.id not in suites.get("regression", []):
            raise SystemExit("这条不在回归测试集里")
        suites["regression"].remove(args.id)
        suites.setdefault("retired", {})[args.id] = {"why": args.why, "at": datetime.now(timezone.utc).isoformat()}
        SUITES.write_text(json.dumps(suites, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已退役")
    elif args.command == "gate":
        problems = gate(items, suites, load_runs(), reason_map, profile)
        for problem in problems:
            print(f"不通过：{problem}")
        if not problems:
            runs = [run for run in load_runs() if run["suite"] != "negative_batch" and run["fingerprint"] == rules_fingerprint()]
            failed = [i for i in score_run(runs[-1], items, reason_map)["failed"] if i in set(suites["regression"])] if runs else []
            print(f"上线前检查通过：回归测试集 {len(suites['regression'])} 条判错 {len(failed)} 条（通过率 {1 - len(failed) / len(suites['regression']):.1%}），写成文章的全对，负向用例没有凑数，规则指纹 {rules_fingerprint()}")
        sys.exit(1 if problems else 0)
    elif args.command == "sources":
        SUITE_DIR.mkdir(parents=True, exist_ok=True)
        path = SUITE_DIR / "sources.html"
        path.write_text(f"<!doctype html><meta charset='utf-8'><title>信息源</title>{source_sections()}", encoding="utf-8")
        print(f"信息源：{path}")
    elif args.command == "report":
        SUITE_DIR.mkdir(parents=True, exist_ok=True)
        import batch_trace
        extra = {"信息源": source_sections()}
        batches = sorted({item["batch"] for item in items if re.match(r"\d{4}-\d{2}-\d{2}-main", item["batch"])})
        if batches:
            extra["最近一批的执行轨迹"] = "<pre>" + html.escape(batch_trace.render_markdown(batch_trace.trace(batches[-1]))) + "</pre>"
        REPORT.write_text(render_report(items, suites, load_runs(), reason_map, profile, extra), encoding="utf-8")
        print(f"报告：{REPORT}")


if __name__ == "__main__":
    main()
