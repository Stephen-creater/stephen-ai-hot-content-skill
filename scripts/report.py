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
  </div>
</article>"""
        )

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stephen AI 热点候选</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f1eb;color:#222;margin:0}}main{{max-width:900px;margin:auto;padding:32px 18px 80px}}header{{margin-bottom:28px}}h1{{font-size:30px;margin:0 0 8px}}.hint{{color:#666}}.card{{background:#fff;border:1px solid #ddd4c7;border-radius:14px;padding:20px;margin:16px 0}}.meta{{display:flex;justify-content:space-between;color:#806b51;font-size:13px}}h2{{font-size:21px;margin:10px 0}}a{{color:#222}}.reason{{color:#365b3b}}.penalty{{color:#9b3d2f}}.readiness{{font-size:13px;color:#6d5d49;background:#f8f4ed;padding:8px;border-radius:7px}}.review{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}button{{padding:9px;border:1px solid #cbbda9;background:#f8f4ed;border-radius:8px;cursor:pointer}}button.active{{background:#222;color:#fff}}textarea{{grid-column:1/-1;min-height:58px;padding:8px}}.missed{{background:#fff8df;border:1px solid #e2ca77;padding:18px;border-radius:12px;margin-top:30px}}input{{width:100%;box-sizing:border-box;margin:5px 0;padding:9px}}#export{{margin-top:20px;background:#222;color:#fff}}
</style></head><body><main><header><h1>Stephen AI 热点候选</h1><div class="hint">{html.escape(generated_at)} · 人工标记会保存在当前浏览器，可导出 JSON</div></header>
{''.join(cards)}
<section class="missed"><h2>补充遗漏选题</h2><input id="missed-title" placeholder="标题"><input id="missed-url" placeholder="链接"><input id="missed-reason" placeholder="为什么重要"><button id="add-missed">加入遗漏列表</button><ul id="missed-list"></ul></section>
<button id="export">导出审核结果</button>
</main><script>const candidates={payload};const key='stephen-topic-review:'+location.pathname;const state=JSON.parse(localStorage.getItem(key)||'{{"reviews":{{}},"missed":[]}}');function save(){{localStorage.setItem(key,JSON.stringify(state))}}document.querySelectorAll('.card').forEach(card=>{{const id=card.dataset.id;const candidate=candidates.find(item=>String(item.id)===id);const review=state.reviews[id]||{{status:candidate&&candidate.selected_by_default?'selected':'pending',note:''}};const area=card.querySelector('textarea');area.value=review.note;card.querySelectorAll('button[data-status]').forEach(button=>{{if(button.dataset.status===review.status)button.classList.add('active');button.onclick=()=>{{card.querySelectorAll('button').forEach(b=>b.classList.remove('active'));button.classList.add('active');state.reviews[id]={{status:button.dataset.status,note:area.value}};save()}}}});area.oninput=()=>{{state.reviews[id]={{status:(state.reviews[id]||{{}}).status||'pending',note:area.value}};save()}}}});function renderMissed(){{document.querySelector('#missed-list').innerHTML=state.missed.map((x,i)=>`<li>${{x.title}} <a href="${{x.url}}">链接</a> ${{x.reason}} <button onclick="removeMissed(${{i}})">删除</button></li>`).join('')}}window.removeMissed=i=>{{state.missed.splice(i,1);save();renderMissed()}};document.querySelector('#add-missed').onclick=()=>{{const title=document.querySelector('#missed-title').value.trim();if(!title)return;state.missed.push({{title,url:document.querySelector('#missed-url').value.trim(),reason:document.querySelector('#missed-reason').value.trim()}});save();renderMissed()}};document.querySelector('#export').onclick=()=>{{const output={{generated_at:'{html.escape(generated_at)}',reviews:state.reviews,missed:state.missed,candidates}};const blob=new Blob([JSON.stringify(output,null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='selection_feedback.json';a.click();URL.revokeObjectURL(a.href)}};renderMissed();</script></body></html>"""
    output_path.write_text(document, encoding="utf-8")
