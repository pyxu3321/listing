'use strict';
// 页面只负责输入、预览与导出；匹配始终调用 Python 原有算法。
const $ = id => document.getElementById(id);
const state = {library: null, output: null, details: new Map(), busy: false};
const roleNames = {title:'标题', bullet:'五点描述', bullet_point:'五点描述', description:'普通详情', aplus_text:'A+ 文本', main_image:'主图', gallery:'附图', aplus:'A+ 图片', aplus_image:'A+ 图片', video:'视频', video_thumbnail:'视频缩略图'};
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined && text !== null) n.textContent = text; if (cls) n.className = cls; return n; }
function safeLink(url, label) { try { const u = new URL(url); if (!['https:','http:'].includes(u.protocol)) return el('span',label); const a=el('a',label); a.href=u.href; a.target='_blank'; a.rel='noopener noreferrer'; return a; } catch { return el('span',label); } }
async function api(path, options) { const response = await fetch(path,options); const data=await response.json(); if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`); return data; }
const split = text => text.split(/[\n,，;；]+/).map(x=>x.trim()).filter(Boolean);
const features = x => (x.structured_features?.selling_points || []);
function featureText(x) { return x.label_zh || x.text_en || ''; }
function showError(error) { $('error').textContent = error.message || String(error); $('error').hidden=false; }
function setBusy(value) { state.busy=value; $('submit').disabled=value; $('submit').textContent=value?'正在匹配真实特征库…':'寻找整体参考 ↗'; }

function renderCards(rows, scored=false) {
  $('cards').replaceChildren(); $('empty').hidden=rows.length>0;
  $('resultCount').textContent=`${rows.length} 套`;
  for (const row of rows) {
    const card=el('button',null,'card'); card.type='button'; card.setAttribute('aria-label',`查看采集编号 ${row.historical_rank} ${row.identity.product_id}`);
    const image=el('div',null,'image-wrap');
    if (row.preview_url) { const img=el('img'); img.src=row.preview_url; img.loading='lazy'; img.alt=`${row.identity.product_id} 原始主图`; image.append(img); }
    else image.append(el('span','暂无主图','muted'));
    image.append(el('span',`采集 #${row.historical_rank ?? '未知'}`,'rank')); card.append(image);
    const body=el('div',null,'card-body'); body.append(el('div',row.identity.product_id,'product-id'),el('h3',row.title,'card-title'));
    const tags=el('div',null,'tags'); for(const feature of features(row).slice(0,3)) tags.append(el('span',featureText(feature),'tag')); body.append(tags);
    if(scored) { const score=el('div',null,'score');score.append(el('strong',row.similarity.toFixed(4)),el('span','综合相似度'));body.append(score);body.append(el('div',`卖点 ${row.product_similarity?.toFixed(4) ?? '—'} · 风格 ${row.style_similarity?.toFixed(4) ?? '未指定'}`,'score-detail')); }
    const meta=el('div',null,'card-meta');meta.append(el('span',`${row.identity.country_code} / ${row.identity.site_id}`),el('span',`${row.counts.image} 图 · ${row.counts.video} 视频`));body.append(meta);card.append(body);
    card.addEventListener('click',()=>openDetail(row.listing_version_id).catch(showError));$('cards').append(card);
  }
}

function browse() { if(!state.library)return; $('resultTitle').textContent='素材库预览';$('resultNote').textContent='按历史采集编号浏览。点击整套素材，核对主图、附图、视频、标题、五点与特征证据。';$('querySummary').hidden=true; renderCards([...state.library.listings].sort((a,b)=>(a.historical_rank??Infinity)-(b.historical_rank??Infinity))); }
async function openDetail(version, partId) {
  if(!state.details.has(version)) state.details.set(version,await api('/api/listings/'+encodeURIComponent(version)));
  const data=state.details.get(version);$('detailTitle').textContent=`采集 #${data.historical_rank} · ${data.identity.product_id}`;
  const body=$('detailBody');body.replaceChildren(el('p',data.title,'detail-summary'));
  const tabs=el('div',null,'detail-tabs'); const content=el('div');
  const choices=[['整体特征','features'],['图片','image'],['视频','video'],['标题 / 五点 / 详情','text'],['来源与版本','source']];
  if(data.structured_features?.attribute_features)choices.splice(1,0,['属性与条件','attributes']);
  function switchTab(kind, focusPart) {
    for(const button of tabs.children)button.classList.toggle('active',button.dataset.kind===kind);
    content.replaceChildren();
    if(kind==='features') {
      const f=data.structured_features || {};content.append(el('p',f.summary_en || '未提供整体摘要','detail-summary'));
      for(const [key,label] of [['selling_points','整体卖点'],['product_traits','产品特征'],['visual_elements','视觉元素'],['style','整体风格']]){
        const box=el('section',null,'feature');box.append(el('h3',label));
        for(const x of f[key]||[]) {const item=el('div');item.append(el('strong',featureText(x)),el('p',x.text_en));
          if(x.conditions?.length)item.append(el('p','适用条件：'+x.conditions.join('；'),'condition'));
          for(const [i,id] of (x.evidence_part_ids||[]).entries()){const part=data.components.find(p=>p.part_id===id);if(!part)continue;const b=el('button',`证据 ${i+1} · ${roleNames[part.role]||part.role}`,'evidence-link');b.type='button';b.onclick=()=>switchTab(part.entity_kind,id);item.append(b);}box.append(item);}
        content.append(box);
      }
    }else if(kind==='attributes') {
      for(const a of data.structured_features.attribute_features){const box=el('section',null,'feature');box.append(el('h3',a.label_zh),el('p',`${a.field} / ${a.object} · ${a.status}`),el('p',a.text_en));if(a.conditions.length)box.append(el('p',a.conditions.join('；'),'condition'));for(const [i,e] of a.evidence.entries()){const p=data.components.find(p=>p.part_id===e.part_id);if(!p)continue;const b=el('button',`证据 ${i+1} · ${roleNames[p.role]||p.role}`,'evidence-link');b.type='button';b.title=e.quote||e.region||'';b.onclick=()=>switchTab(p.entity_kind,p.part_id);box.append(b);}content.append(box);}
    }else if(kind==='source') {content.append(el('pre',JSON.stringify({identity:data.identity,listing_version_id:version,approval_status:data.approval_status,source:data.source},null,2),'detail-source'));}
    else {
      const grid=el('div',null,kind==='text'?'text-components':'component-grid');const parts=data.components.filter(p=>p.entity_kind===kind);
      if(!parts.length)content.append(el('p','本次采集中没有此类组件。','muted'));
      for(const p of parts){const box=el('article',null,'component');box.id='part-'+p.part_id;box.classList.toggle('disabled',p.controls?.enabled===false);box.append(el('h3',`${roleNames[p.role]||p.role}${p.is_main_image?' · 主图':''}${p.controls?.enabled===false?' · 已禁用':''}`));
        if(p.media_url){const media=el(kind==='video'?'video':'img');media.src=p.media_url;if(kind==='video'){media.controls=true;media.preload='none';}else{media.loading='lazy';media.alt=p.features?.semantic_description_en||p.role;}box.append(media);}
        if(p.source_text)box.append(el('p',p.source_text,'source-text'));
        if(p.entity_kind!=='text' && p.features?.semantic_description_en)box.append(el('p',p.features.semantic_description_en));
        if(p.reference?.source_url)box.append(safeLink(p.reference.source_url,'打开原始页面 ↗'));
        box.append(el('p',`组件 ${p.part_id}`,'version'));grid.append(box);
      }content.append(grid);
    }
    if(focusPart)requestAnimationFrame(()=>document.getElementById('part-'+focusPart)?.scrollIntoView({block:'center'}));
  }
  for(const [name,kind] of choices){const b=el('button',name);b.type='button';b.dataset.kind=kind;b.onclick=()=>switchTab(kind);tabs.append(b);}
  body.append(tabs,content);const focus=data.components.find(x=>x.part_id===partId);switchTab(focus?.entity_kind||'features',partId);if(!$('detail').open)$('detail').showModal();
}

$('searchForm').addEventListener('submit',async event=>{
  event.preventDefault();if(state.busy)return;$('error').hidden=true;
  const request={selling_points:split($('sellingPoints').value)};
  for(const [id,key] of [['description','product_description'],['style','style'],['country','country_code'],['category','category_id']])if($(id).value.trim())request[key]=$(id).value.trim();
  if($('site').value)request.site_ids=[$('site').value];
  if(!request.selling_points.length&&!request.product_description)return showError(new Error('请填写卖点或产品描述。风格、国家与品类仅作为附加条件。'));
  setBusy(true);
  try{
    const output=await api('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request,top_k:Number($('topK').value),raw_order:$('rawOrder').checked})});state.output=output;
    $('resultTitle').textContent='整体匹配候选';$('resultNote').textContent='点击候选，查看整套图片、视频与文案。';
    $('querySummary').hidden=false;$('querySummary').textContent=`本次输入：${[...request.selling_points,request.product_description,request.style].filter(Boolean).join(' / ')}\n排序：${$('rawOrder').checked?'原始相似度':'默认排序，接近分数参考历史采集顺序'} · 返回 ${output.result.whole_candidates.length} 套`;
    renderCards(output.result.whole_candidates,true);$('export').disabled=false;
  }catch(error){showError(error);}finally{setBusy(false);}
});
$('browse').onclick=browse;
$('closeDetail').onclick=()=>$('detail').close();
$('detail').addEventListener('click',event=>{if(event.target===$('detail')){const r=$('detail').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('detail').close();}});
for(const button of document.querySelectorAll('[data-sample]'))button.onclick=()=>{$('sellingPoints').value={soft:'soft\nlightweight',cover:'removable washable cover',firm:'extra firm'}[button.dataset.sample];};
$('export').onclick=()=>{if(!state.output)return;const blob=new Blob([JSON.stringify(state.output,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download='listing-reference-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
async function start(){try{state.library=await api('/api/library');$('wholeCount').textContent=state.library.listings.length;$('partCount').textContent=state.library.component_count.toLocaleString();$('connection').textContent='● 本地特征库已连接';$('featureVersion').textContent=state.library.feature_recipes?.includes('reviewed-detailed-whole-v6')?'V6':'V5';
  for(const [id,key] of [['country','country_code'],['category','category_id'],['site','site_id']])for(const value of [...new Set(state.library.listings.map(x=>x.identity[key]))].sort()){const o=el('option',value);o.value=value;$(id).append(o);}browse();
}catch(error){$('connection').textContent='连接失败';showError(error);}}
start();
