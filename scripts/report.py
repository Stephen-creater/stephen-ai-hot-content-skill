from __future__ import annotations

import html
import json
from pathlib import Path


def generate_report(candidates: list[dict], output_path: Path, generated_at: str) -> None:
    payload = json.dumps(candidates, ensure_ascii=False).replace("</", "<\\/")
    cards = []
    for item in candidates:
        cards.append(
            f"""
<article class="card" data-id="{html.escape(str(item['id']))}">
  <div class="meta"><span>{html.escape(item.get('source_name', '未知来源'))} · {html.escape(item.get('content_form', 'article'))}</span><span>评分 {item['score']}</span></div>
  <h2><a href="{html.escape(item.get('link', '#'))}" target="_blank" rel="noreferrer">{html.escape(item.get('title_zh') or item['title'])}</a></h2>
  <p>{html.escape(item.get('summary') or item.get('content', '')[:240])}</p>
  <p class="reason">{html.escape(item.get('reason', ''))}</p>
  <p class="penalty">{html.escape(item.get('penalty', ''))}</p>
  <p class="readiness">文字材料 {html.escape(item.get('content_status', 'unknown'))} · 二创成熟度 {html.escape(item.get('adaptation_readiness', '未知'))} · 研究成本 {html.escape(item.get('research_cost', '未知'))}</p>
  <div class="review">
    <button data-status="selected">应该入选</button>
    <button data-status="rejected">不应入选</button>
    <button data-status="pending">待定</button>
    <textarea placeholder="原因或缺失信息"></textarea>
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
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f1eb;color:#222;margin:0}}main{{max-width:900px;margin:auto;padding:24px 18px 80px}}header{{margin-bottom:20px}}h1{{font-size:30px;margin:0 0 8px}}.hint{{color:#666}}.toolbar{{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;gap:16px;margin:0 0 22px;padding:12px 14px;background:rgba(244,241,235,.96);border:1px solid #d8cdbc;border-radius:12px;box-shadow:0 6px 18px rgba(70,55,35,.08);backdrop-filter:blur(10px)}}.toolbar-summary{{display:flex;flex-wrap:wrap;gap:8px 14px;font-size:13px;color:#5c5144}}.export-state{{font-weight:600}}.export-state.dirty{{color:#a13f2c}}.export-state.clean{{color:#35633d}}.export-button{{flex:0 0 auto;background:#222;color:#fff;font-weight:600}}.card{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:20px;margin:16px 0}}.empty-state{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:32px 24px;margin:18px 0;color:#5c5144}}.empty-state h2{{color:#222}}.meta{{display:flex;justify-content:space-between;color:#806b51;font-size:13px}}h2{{font-size:21px;margin:10px 0}}a{{color:#222}}.reason{{color:#365b3b}}.penalty{{color:#9b3d2f}}.readiness{{font-size:13px;color:#6d5d49;background:#f8f4ed;padding:8px;border-radius:7px}}.review{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}button{{padding:9px;border:1px solid #cbbda9;background:#f8f4ed;border-radius:8px;cursor:pointer}}button.active{{background:#222;color:#fff}}textarea{{grid-column:1/-1;min-height:58px;padding:8px}}.card-save-status{{grid-column:1/-1;color:#777;font-size:12px}}.card-save-status.saved{{color:#35633d}}.missed{{background:#fff8df;border:1px solid #e2ca77;padding:18px;border-radius:12px;margin-top:30px}}input{{width:100%;box-sizing:border-box;margin:5px 0;padding:9px}}#export-bottom{{margin-top:20px;background:#222;color:#fff}}@media(max-width:620px){{.toolbar{{align-items:stretch;flex-direction:column}}.export-button{{width:100%}}}}
</style></head><body><main><header><h1>Stephen AI 热点候选</h1><div class="hint">{html.escape(generated_at)} · 标记和备注会实时保存到当前浏览器。导出文件会暂存在浏览器下载目录，导入 Skill 后再清理</div></header>
<section class="toolbar" aria-label="审核进度">
  <div class="toolbar-summary"><span id="review-counts"></span><span id="export-state" class="export-state"></span></div>
  <button class="export-button" data-export>导出全部审核结果</button>
</section>
{candidate_content}
<section class="missed"><h2>补充遗漏选题</h2><input id="missed-title" placeholder="标题"><input id="missed-url" placeholder="链接"><input id="missed-reason" placeholder="为什么重要"><button id="add-missed">加入遗漏列表</button><ul id="missed-list"></ul></section>
<button id="export-bottom" data-export>导出全部审核结果</button>
</main><script>
const candidates={payload};
const key='stephen-topic-review:'+location.pathname;
let state;
try{{state=JSON.parse(localStorage.getItem(key)||'{{"reviews":{{}},"missed":[],"dirty":false}}')}}catch(error){{state={{reviews:{{}},missed:[],dirty:false}}}}
state.reviews=state.reviews||{{}};
state.missed=state.missed||[];
state.dirty=state.dirty===undefined?Boolean(Object.keys(state.reviews).length||state.missed.length):Boolean(state.dirty);

function effectiveReview(candidate){{
  return state.reviews[String(candidate.id)]||{{status:candidate.selected_by_default?'selected':'pending',note:''}};
}}

function renderSummary(){{
  const counts={{selected:0,rejected:0,pending:0}};
  candidates.forEach(candidate=>{{const status=effectiveReview(candidate).status||'pending';counts[status]=(counts[status]||0)+1}});
  document.querySelector('#review-counts').textContent=`应该入选 ${{counts.selected}} · 不应入选 ${{counts.rejected}} · 待定 ${{counts.pending}} · 遗漏 ${{state.missed.length}}`;
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
  card.querySelectorAll('button[data-status]').forEach(button=>{{
    if(button.dataset.status===review.status)button.classList.add('active');
    button.onclick=()=>{{
      card.querySelectorAll('button[data-status]').forEach(item=>item.classList.remove('active'));
      button.classList.add('active');
      state.reviews[id]={{status:button.dataset.status,note:area.value}};
      save();
      markCardSaved(card);
    }};
  }});
  area.oninput=()=>{{
    state.reviews[id]={{status:(state.reviews[id]||review).status||'pending',note:area.value}};
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

function exportFeedback(){{
  const exportedAt=new Date().toISOString();
  const output={{generated_at:'{html.escape(generated_at)}',exported_at:exportedAt,reviews:state.reviews,missed:state.missed,candidates}};
  const blob=new Blob([JSON.stringify(output,null,2)],{{type:'application/json'}});
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  link.href=url;link.download='selection_feedback-{html.escape(generated_at)}.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),0);
  state.dirty=false;state.last_exported_at=exportedAt;save(false);
}}

document.querySelectorAll('[data-export]').forEach(button=>button.onclick=exportFeedback);
window.addEventListener('beforeunload',event=>{{if(!state.dirty)return;event.preventDefault();event.returnValue=''}});
renderMissed();
renderSummary();
</script></body></html>"""
    output_path.write_text(document, encoding="utf-8")
