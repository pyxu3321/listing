"""导出可追溯参考包及离线核对页面，不复制或改写来源图片。"""
import html
import json
from pathlib import Path


def write(directory,result,inventory):
    """保存结果JSON与HTML。页面引用本机原图/视频，转发需另行打包素材。"""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'reference_package.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (directory/'library_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=lambda x:html.escape(str(x),quote=True)
    whole_cards=[]
    for x in result['whole_candidates']:
        proof=''.join('<figure><img loading="lazy" src="'+esc(Path(e['asset']['local_path']).resolve().as_uri())+'"><figcaption>'+esc(e['description'])+' · 风格相似度 '+str(e['similarity'])+'</figcaption></figure>' for e in x.get('style_evidence',[]) if e.get('asset',{}).get('local_path'))
        preview=x.get('preview_image') or {}
        hero='<figure><img src="'+esc(Path(preview['local_path']).resolve().as_uri())+'"><figcaption>原Listing主图预览，未选作生成参考</figcaption></figure>' if preview.get('local_path') and Path(preview['local_path']).is_file() else ''
        scores='<p>综合排序分 '+str(x.get('relevance_score',x['similarity']))+' · 产品卖点 '+str(x.get('product_similarity',x['similarity']))+' · 视觉风格 '+str(x.get('style_similarity'))+'</p><p>实际权重 '+esc(x.get('weights',{}))+' · '+esc(x.get('style_status','legacy'))+'</p>'
        whole_cards.append('<article><h3>采集排名 '+esc(x['overall_features'].get('historical_rank','未知'))+' · '+esc(x['identity']['product_id'])+'</h3>'+scores+hero+proof+'<details><summary>整体特征与来源说明</summary><pre>'+esc(json.dumps(x['overall_features'],ensure_ascii=False,indent=2))+'</pre></details></article>')
    whole=''.join(whole_cards)
    groups=[]
    for need in result['reference_needs']:
        cards=[]
        for item in need['candidates']:
            media='';asset=item.get('asset')
            if asset and asset.get('local_path'):
                path=Path(asset['local_path'])
                if path.is_file():
                    url=esc(path.resolve().as_uri())
                    media=('<video controls preload="none" src="'+url+'"></video>') if item['source_role']=='video' else '<img loading="lazy" src="'+url+'">'
            ranking='<p>组件向量相似度 '+str(item['similarity'])+' · 用途排序分 '+str(item.get('relevance_score',item['similarity']))+'</p><p>标签命中：'+esc('、'.join(item.get('theme_matches',[])) or '未配置或未命中')+' · '+esc(item.get('ranking_method','cosine_only'))+'</p>'
            cards.append('<article>'+media+'<h3>'+esc(item['identity']['product_id'])+'</h3>'+ranking+'<pre>'+esc(item.get('source_text') or json.dumps(item['features'],ensure_ascii=False,indent=2))+'</pre><small>'+esc(item['part_id'])+'</small></article>')
        groups.append('<section><h2>'+esc(need['role'])+' · '+esc(need['purpose'])+'</h2><p>'+esc(need['status'])+'</p><div class="grid">'+''.join(cards)+'</div></section>')
    component_note='<p>本次仅选整体。组件挑选暂缓至后续生成规划，按具体图片和文案用途再执行。</p>' if result.get('component_matching',{}).get('status')=='deferred_to_generation_planning' else ''
    page='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>第三阶段 · 参考匹配</title><style>body{font:15px system-ui;background:#f3f6f2;color:#183c32;padding:24px;max-width:1500px;margin:auto}article{background:white;padding:18px;border:1px solid #d6dfd8;border-radius:10px;min-width:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}img,video{width:100%;max-height:300px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}small{overflow-wrap:anywhere}</style><h1>第三阶段 · 整体优先匹配</h1><p>'+esc(result['status'])+' · '+esc(result['warning'])+'</p><p>生成前还需：'+esc('、'.join(result['missing_generation_inputs']) or '运营确认具体参考及版本')+'</p><a href="reference_package.json">完整参考包</a><h2>整套候选</h2><div class="grid">'+whole+'</div>'+component_note+''.join(groups)
    (directory/'index.html').write_text(page,encoding='utf-8')
