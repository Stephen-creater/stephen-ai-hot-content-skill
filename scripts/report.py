from __future__ import annotations

import html
import json
from pathlib import Path

# One click per reason. Stephen's recurring notes (382 reviews) collapse into these;
# free text stays available for anything new.
REJECT_REASONS = ("题目没意思", "对读者没用", "太浅太泛", "AI 味重", "太依赖作者个人经历", "太技术", "太垂直小众", "过时或已写过", "改写成本高", "广告或新闻通稿")
SELECT_REASONS = ("读者痛点强", "干货足", "改一改就能发", "长期有用", "访谈或文字稿质量高")


def generate_report(candidates: list[dict], output_path: Path, generated_at: str, batch_owner: str = "") -> None:
    if batch_owner not in {"", "主力", "主力2"}:
        raise ValueError("未知批次归属")
    owner_json = json.dumps(batch_owner, ensure_ascii=False)
    export_name = f"selection_feedback-{batch_owner + '-' if batch_owner else ''}{generated_at}.json"
    payload = json.dumps(candidates, ensure_ascii=False).replace("</", "<\\/")
    cards = []
    for position, item in enumerate(candidates, start=1):
        display_title = item.get('source_title') or item['title']
        angle = item.get('editorial_angle') or item.get('title_zh')
        angle_html = f'<p class="editorial-angle">拟议切口（非原文标题）：{html.escape(angle)}</p>' if angle and angle != display_title else ''
        reference_links = []
        if item.get("link"):
            reference_links.append(
                f'<a href="{html.escape(item["link"])}" target="_blank" rel="noreferrer external">人类文章</a>'
            )
        if item.get("source_url") and item.get("source_url") != item.get("link"):
            reference_links.append(
                f'<a href="{html.escape(item["source_url"])}" target="_blank" rel="noreferrer external">GitHub / Skill 原文</a>'
            )
        if item.get("skill_url") and item.get("skill_url") not in {item.get("link"), item.get("source_url")}:
            reference_links.append(
                f'<a href="{html.escape(item["skill_url"])}" target="_blank" rel="noreferrer external">Skill 目录页</a>'
            )
        reference_links_html = (
            '<nav class="source-links" aria-label="参考链接">' + ' · '.join(reference_links) + '</nav>'
            if reference_links else ''
        )
        article_zh_html = ""
        if item.get("article_zh"):
            article_zh_html = (
                '<details class="article-zh" open><summary>中文文章解读</summary>'
                f'<div>{html.escape(item["article_zh"])}</div></details>'
            )
        localization_html = ""
        localization = item.get("localization_review")
        if isinstance(localization, dict) and localization.get("status") == "passed":
            localization_html = (
                '<p class="localization-note"><strong>中文用户适配：</strong>'
                f'{html.escape(str(localization.get("evidence", "")))}</p>'
            )
        practical_review_html = ""
        setup_cost = item.get("setup_cost_review")
        security = item.get("security_review")
        practical_lines = []
        if isinstance(setup_cost, dict) and setup_cost.get("status") == "passed":
            practical_lines.append(
                '<div><strong>配置与付费：</strong>'
                f'{html.escape(str(setup_cost.get("evidence", "")))}</div>'
            )
        if isinstance(security, dict) and security.get("status") == "passed":
            practical_lines.append(
                '<div><strong>安全审查：</strong>'
                f'{html.escape(str(security.get("evidence", "")))}</div>'
            )
        if practical_lines:
            practical_review_html = '<div class="practical-review">' + ''.join(practical_lines) + '</div>'
        github_stars = f" · GitHub {int(item['github_stars'])} Star" if item.get("github_stars") is not None else ""
        transcript = ""
        if item.get("content_form") in {"video", "podcast"} and item.get("content_status") == "transcript":
            transcript = f"""
  <details class="transcript"><summary>查看整理后的完整逐字稿</summary><div class="transcript-note">转写文本供阅读参考；专有名词、数字及正式引用请回到原音视频核对。</div><pre>{html.escape(item.get('content', ''))}</pre></details>"""
        # Reviewers see the human verdict in plain words, not internal scores or penalty codes.
        review = item.get("manual_editorial_review") if isinstance(item.get("manual_editorial_review"), dict) else {}
        cards.append(
            f"""
<article class="card" data-id="{html.escape(str(item['id']))}">
  <div class="meta"><span>{html.escape(item.get('source_name', '未知来源'))} · {html.escape(item.get('content_form', 'article'))}{github_stars}</span><span>{html.escape(str(item.get('published', ''))[:16])}</span></div>
  <h2><a href="{html.escape(item.get('link', '#'))}" target="_blank" rel="noreferrer">{position}. {html.escape(display_title)}</a></h2>
  {angle_html}
  {reference_links_html}
  {article_zh_html}
  {localization_html}
  {practical_review_html}
  <p>{html.escape(item.get('summary') or item.get('content', '')[:240])}</p>
  <p class="reason">{html.escape(review.get('reader_change') or item.get('reason', ''))}</p>
  <p class="penalty">{html.escape(('需要注意：' + review['counterargument']) if review.get('counterargument') else '')}</p>
  {('<p class="rewrite">改写成本：' + html.escape(str(review['rewrite_effort'])) + '</p>') if review.get('rewrite_effort') else ''}
  <p class="readiness">文字材料 {html.escape(item.get('content_status', 'unknown'))} · 二创成熟度 {html.escape(item.get('adaptation_readiness', '未知'))} · 研究成本 {html.escape(item.get('research_cost', '未知'))}</p>
  {transcript}
  <div class="review">
    <button data-status="selected">要这个</button>
    <button data-status="rejected">不要</button>
    <button data-status="pending">待定</button>
    <div class="reasons" data-for="selected">{''.join(f'<button class="chip" data-reason="{html.escape(r)}">{html.escape(r)}</button>' for r in SELECT_REASONS)}</div>
    <div class="reasons" data-for="rejected">{''.join(f'<button class="chip" data-reason="{html.escape(r)}">{html.escape(r)}</button>' for r in REJECT_REASONS)}</div>
    <details class="note"><summary>补充一句（可选）</summary><textarea placeholder="标签说不清时再写"></textarea></details>
    <div class="card-save-status" aria-live="polite">修改后会自动保存到当前浏览器</div>
  </div>
</article>"""
        )

    candidate_content = "".join(cards) if cards else """
<section class="empty-state">
  <h2>本轮没有合格候选</h2>
  <p>所有内容都已被历史反馈或硬门槛过滤。不用为了凑数审核低质量选题。</p>
</section>"""

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stephen AI 热点候选</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f1eb;color:#222;margin:0}}main{{max-width:900px;margin:auto;padding:24px 18px 80px}}header{{margin-bottom:20px}}h1{{font-size:30px;margin:0 0 8px}}.hint{{color:#666}}.toolbar{{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 22px;padding:12px 14px;background:rgba(244,241,235,.96);border:1px solid #d8cdbc;border-radius:12px;box-shadow:0 6px 18px rgba(70,55,35,.08);backdrop-filter:blur(10px)}}.toolbar-summary{{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:13px;color:#5c5144}}.export-state{{font-weight:600}}.export-state.dirty{{color:#a13f2c}}.export-state.clean{{color:#35633d}}.export-button{{flex:0 0 auto;background:#222;color:#fff;font-weight:600}}.card{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:20px;margin:16px 0}}.empty-state{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:32px 24px;margin:18px 0;color:#5c5144}}.empty-state h2{{color:#222}}.meta{{display:flex;justify-content:space-between;color:#806b51;font-size:13px}}h2{{font-size:21px;margin:10px 0}}a{{color:#222}}.source-links{{display:flex;flex-wrap:wrap;gap:8px 12px;margin:8px 0 14px;font-size:14px}}.source-links a{{display:inline-block;padding:7px 10px;border:1px solid #cbbda9;border-radius:8px;background:#f8f4ed;text-decoration:none;font-weight:600}}.source-links a:hover{{background:#eee7dc}}.article-zh{{margin:12px 0;border:1px solid #c8d8c8;border-radius:10px;padding:12px;background:#f5faf4}}.article-zh summary{{cursor:pointer;font-weight:700;color:#294f31}}.article-zh div{{margin-top:10px;white-space:pre-wrap;line-height:1.8}}.localization-note{{font-size:14px;color:#5b5145;background:#f8f4ed;padding:9px 10px;border-radius:8px}}.practical-review{{display:grid;gap:7px;margin:10px 0;padding:10px 12px;border:1px solid #d7c9e8;border-radius:8px;background:#faf7ff;color:#50445f;font-size:14px;line-height:1.65}}.reason{{color:#365b3b}}.penalty{{color:#9b3d2f}}.readiness{{font-size:13px;color:#6d5d49;background:#f8f4ed;padding:8px;border-radius:7px}}.transcript{{margin:12px 0;border:1px solid #ddd4c7;border-radius:8px;padding:12px;background:#fbfaf7}}.transcript summary{{cursor:pointer;font-weight:700}}.transcript-note{{margin:10px 0;color:#806b51;font-size:13px}}.transcript pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-height:620px;overflow:auto;margin:0;padding:16px 18px;border-radius:8px;background:#fff;font:16px/1.95 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:.01em}}.review{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.reasons{{grid-column:1/-1;display:none;flex-wrap:wrap;gap:6px}}.reasons.show{{display:flex}}.chip{{padding:5px 10px;font-size:13px;border-radius:999px}}.chip.on{{background:#35633d;color:#fff;border-color:#35633d}}.reasons[data-for=rejected] .chip.on{{background:#9b3d2f;border-color:#9b3d2f}}.note{{grid-column:1/-1}}.note summary{{cursor:pointer;color:#806b51;font-size:13px}}.rewrite{{color:#5b5145;font-size:14px}}.quick{{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:13px;color:#5c5144}}.batch-reasons{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:14px 18px;margin:0 0 18px}}.batch-reasons h2{{font-size:16px;margin:0 0 8px}}.batch-reasons .reasons{{display:flex}}button{{padding:9px;border:1px solid #cbbda9;background:#f8f4ed;border-radius:8px;cursor:pointer}}button.active{{background:#222;color:#fff}}textarea{{width:100%;box-sizing:border-box;min-height:52px;padding:8px;margin-top:6px}}.card-save-status{{grid-column:1/-1;color:#777;font-size:12px}}.card-save-status.saved{{color:#35633d}}.missed{{background:#fff8df;border:1px solid #e2ca77;padding:18px;border-radius:12px;margin-top:30px}}input{{width:100%;box-sizing:border-box;margin:5px 0;padding:9px}}#export-bottom{{margin-top:20px;background:#222;color:#fff}}@media(max-width:620px){{.toolbar{{align-items:stretch;flex-direction:column}}.export-button{{width:100%}}.transcript pre{{font-size:15px;line-height:1.9;padding:14px 12px}}}}
</style></head><body><main><header><h1>Stephen AI 热点候选</h1><div class="hint">{html.escape(generated_at)} · 只点你想要的那几条就行。原因用标签点一下，标签说不清时再写一句。标记会实时保存到当前浏览器。</div></header>
<section class="toolbar" aria-label="审核进度">
  <div class="toolbar-summary"><span id="review-counts"></span><span id="export-state" class="export-state"></span></div>
  <label class="quick"><input type="checkbox" id="unmarked-rejected" checked style="width:auto;margin:0">导出时，没点的都算“不要”</label>
  <button class="export-button" data-export>导出全部审核结果</button>
</section>
<section class="batch-reasons"><h2>这批整体的问题（可选，点一下）</h2><div class="reasons" id="batch-reasons" data-for="rejected">{''.join(f'<button class="chip" data-reason="{html.escape(r)}">{html.escape(r)}</button>' for r in REJECT_REASONS)}</div></section>
{candidate_content}
<section class="missed"><h2>补充遗漏选题</h2><input id="missed-title" placeholder="标题"><input id="missed-url" placeholder="链接"><input id="missed-reason" placeholder="为什么重要"><button id="add-missed">加入遗漏列表</button><ul id="missed-list"></ul></section>
<button id="export-bottom" data-export>导出全部审核结果</button>
</main><script>
const candidates={payload};
const key='stephen-topic-review:'+location.pathname;
let state;
try{{state=JSON.parse(localStorage.getItem(key)||'{{"reviews":{{}},"missed":[],"dirty":false}}')}}catch(error){{state={{reviews:{{}},missed:[],dirty:false}}}}
state.reviews=state.reviews||{{}};
state.batch_reasons=state.batch_reasons||[];
state.missed=state.missed||[];
state.dirty=state.dirty===undefined?Boolean(Object.keys(state.reviews).length||state.missed.length):Boolean(state.dirty);

function effectiveReview(candidate){{
  const review=state.reviews[String(candidate.id)]||{{status:'unmarked',note:''}};
  review.reasons=review.reasons||[];
  return review;
}}

function renderSummary(){{
  const counts={{selected:0,rejected:0,pending:0,unmarked:0}};
  candidates.forEach(candidate=>{{const status=effectiveReview(candidate).status||'unmarked';counts[status]=(counts[status]||0)+1}});
  document.querySelector('#review-counts').textContent=`要 ${{counts.selected}} · 不要 ${{counts.rejected}} · 待定 ${{counts.pending}} · 未标记 ${{counts.unmarked}} · 遗漏 ${{state.missed.length}}`;
  const exportState=document.querySelector('#export-state');
  exportState.textContent=state.dirty?'已自动保存到浏览器，尚未导出':(state.last_exported_at?'已导出，当前没有新改动':'当前没有待导出的改动');
  exportState.className='export-state '+(state.dirty?'dirty':'clean');
}}

function save(markDirty=true){{
  if(markDirty){{state.dirty=true;state.updated_at=new Date().toISOString()}}
  localStorage.setItem(key,JSON.stringify(state));
  renderSummary();
}}

function markCardSaved(card){{
  const status=card.querySelector('.card-save-status');
  status.textContent='已自动保存到当前浏览器 · 需导出后才能导入 Skill';
  status.classList.add('saved');
}}

document.querySelectorAll('.card').forEach(card=>{{
  const id=card.dataset.id;
  const candidate=candidates.find(item=>String(item.id)===id);
  const review=effectiveReview(candidate);
  const area=card.querySelector('textarea');
  area.value=review.note||'';
  if(review.note)card.querySelector('details.note').open=true;
  const current=()=>state.reviews[id]||{{status:'unmarked',note:'',reasons:[]}};
  const showReasons=status=>card.querySelectorAll('.reasons').forEach(box=>box.classList.toggle('show',box.dataset.for===status));
  showReasons(review.status);
  card.querySelectorAll('.chip').forEach(chip=>{{
    if(review.reasons.includes(chip.dataset.reason)&&chip.parentElement.dataset.for===review.status)chip.classList.add('on');
    chip.onclick=()=>{{
      const entry=current();
      const reasons=new Set(entry.reasons||[]);
      chip.classList.toggle('on')?reasons.add(chip.dataset.reason):reasons.delete(chip.dataset.reason);
      state.reviews[id]={{...entry,reasons:[...reasons]}};
      save();markCardSaved(card);
    }};
  }});
  card.querySelectorAll('button[data-status]').forEach(button=>{{
    if(button.dataset.status===review.status)button.classList.add('active');
    button.onclick=()=>{{
      card.querySelectorAll('button[data-status]').forEach(item=>item.classList.remove('active'));
      card.querySelectorAll('.chip').forEach(item=>item.classList.remove('on'));
      button.classList.add('active');
      state.reviews[id]={{status:button.dataset.status,note:area.value,reasons:[]}};
      showReasons(button.dataset.status);
      save();
      markCardSaved(card);
    }};
  }});
  area.oninput=()=>{{
    const entry=current();
    state.reviews[id]={{...entry,status:entry.status==='unmarked'?'pending':entry.status,note:area.value}};
    save();
    markCardSaved(card);
  }};
}});

function renderMissed(){{
  const list=document.querySelector('#missed-list');
  list.replaceChildren();
  state.missed.forEach((item,index)=>{{
    const row=document.createElement('li');
    row.append(document.createTextNode(item.title+' '));
    if(item.url){{const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noreferrer';link.textContent='链接';row.append(link,document.createTextNode(' '))}}
    if(item.reason)row.append(document.createTextNode(item.reason+' '));
    const remove=document.createElement('button');remove.textContent='删除';remove.onclick=()=>{{state.missed.splice(index,1);save();renderMissed()}};row.append(remove);
    list.append(row);
  }});
}}

document.querySelector('#add-missed').onclick=()=>{{
  const title=document.querySelector('#missed-title').value.trim();
  if(!title)return;
  state.missed.push({{title,url:document.querySelector('#missed-url').value.trim(),reason:document.querySelector('#missed-reason').value.trim()}});
  document.querySelectorAll('.missed input').forEach(input=>input.value='');
  save();
  renderMissed();
}};

document.querySelectorAll('#batch-reasons .chip').forEach(chip=>{{
  if(state.batch_reasons.includes(chip.dataset.reason))chip.classList.add('on');
  chip.onclick=()=>{{
    const reasons=new Set(state.batch_reasons);
    chip.classList.toggle('on')?reasons.add(chip.dataset.reason):reasons.delete(chip.dataset.reason);
    state.batch_reasons=[...reasons];save();
  }};
}});

function exportFeedback(){{
  const exportedAt=new Date().toISOString();
  const reviews={{}};
  const unmarkedRejected=document.querySelector('#unmarked-rejected').checked;
  candidates.forEach(candidate=>{{
    const id=String(candidate.id);
    const entry=state.reviews[id];
    if(entry&&entry.status!=='unmarked'){{reviews[id]={{status:entry.status,note:entry.note||'',reasons:entry.reasons||[]}}}}
    else if(unmarkedRejected){{reviews[id]={{status:'rejected',note:'',reasons:[],implicit:true}}}}
  }});
  const output={{generated_at:'{html.escape(generated_at)}',batch_owner:{owner_json},exported_at:exportedAt,reviews,batch_reasons:state.batch_reasons,missed:state.missed,candidates}};
  const blob=new Blob([JSON.stringify(output,null,2)],{{type:'application/json'}});
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download={json.dumps(export_name, ensure_ascii=False)};link.click();
  setTimeout(()=>URL.revokeObjectURL(url),0);
  state.dirty=false;state.last_exported_at=exportedAt;save(false);
}}

document.querySelectorAll('[data-export]').forEach(button=>button.onclick=exportFeedback);
window.addEventListener('beforeunload',event=>{{if(!state.dirty)return;event.preventDefault();event.returnValue=''}});
renderMissed();
renderSummary();
</script></body></html>"""
    if batch_owner:
        document = document.replace('<h1>Stephen AI 热点候选</h1>', f'<h1>Stephen AI 热点候选 · {html.escape(batch_owner)}</h1>')
    output_path.write_text(document, encoding="utf-8")
    links = []
    for position, item in enumerate(candidates, start=1):
        title = (item.get("source_title") or item["title"]).replace("[", "\\[").replace("]", "\\]")
        links.append(f"{position}. [{title}]({item.get('link', '#')})")
    output_path.with_name("links.md").write_text("\n".join(links) + "\n", encoding="utf-8")
