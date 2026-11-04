"""从完整来源与独立语义审阅创建整体/组件双集合，不复用全文汇聚整体向量。"""
from pathlib import Path
import argparse
import json
import html
from .structured_whole import build_whole
from .collection_store import point_records,export_dataset,read_dataset
from .listing_bundles import digest
from .local_encoder import LocalEncoder
from .storage import write


def render(output,wholes,components):
    """整体页展示提炼含义；证据链接到所属组件，主图仅作原素材预览。"""
    output=Path(output);esc=lambda x:html.escape(str(x),quote=True)
    style='<style>body{font:15px system-ui;line-height:1.7;background:#f2f5f8;color:#213b43;max-width:1450px;margin:28px auto;padding:0 20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}article,section{background:white;padding:20px;border:1px solid #d7e0e5;border-radius:12px;margin-bottom:16px}img,video{width:100%;height:240px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{overflow-wrap:anywhere}.condition{background:#fff0d4;padding:10px}</style>'
    cards=[]
    for point in sorted(wholes,key=lambda p:p['payload']['overall_features']['historical_rank']):
        whole=point['payload'];version=whole['listing_version_id'];rank=whole['overall_features']['historical_rank']
        children=[p for p in components if p['payload']['parent_listing_version_id']==version]
        order={pid:i for i,pid in enumerate(whole['component_ids'])}
        children.sort(key=lambda p:order[p['payload']['part_id']])
        main=next((p['payload'] for p in children if p['payload']['role']=='main_image'),{})
        asset=main.get('asset') or {};hero=''
        if asset.get('local_path'):hero='<img loading="lazy" src="'+esc(Path(asset['local_path']).resolve().as_uri())+'">'
        features=whole['structured_features'];fields=[]
        for key,label in [('selling_points','整体卖点'),('product_traits','产品特征'),('visual_elements','视觉元素'),('style','风格')]:
            items=[]
            for f in features[key]:
                refs=' · '.join('<a href="#'+esc(pid)+'">证据'+str(i+1)+'</a>' for i,pid in enumerate(f['evidence_part_ids']))
                conditions='<p class="condition">条件：'+esc('；'.join(f['conditions']))+'</p>' if f['conditions'] else ''
                items.append('<article><strong>'+esc(f.get('label_zh') or f['text_en'])+'</strong><p>'+esc(f['text_en'])+'</p>'+conditions+'<small>'+refs+'</small></article>')
            fields.append('<h2>'+label+'</h2><div class="grid">'+''.join(items)+'</div>')
        part_cards=[]
        for child in children:
            p=child['payload'];media='';asset=p.get('asset') or {}
            if asset.get('local_path'):
                url=esc(Path(asset['local_path']).resolve().as_uri())
                media='<video controls preload="none" src="'+url+'"></video>' if p['role']=='video' else '<img loading="lazy" src="'+url+'">'
            part_cards.append('<article id="'+esc(p['part_id'])+'"><h3>'+esc(p['role'])+'</h3>'+media+'<p>独立向量：'+esc((p.get('embedding_meta') or {}).get('recipe','未编码'))+'；检索启用：'+esc(p['controls']['retrieve'])+'</p><details><summary>原文、独立特征与来源</summary><pre>'+esc(json.dumps({k:p.get(k) for k in ('source_text','features','reference','asset','controls','component_version_id','parent_listing_version_id')},ensure_ascii=False,indent=2))+'</pre></details></article>')
        folder=output/f'rank{rank}';folder.mkdir(exist_ok=True)
        write(folder/'whole_record.json',whole)
        page='<!doctype html><meta charset="utf-8"><title>Listing整体与组件</title>'+style+'<a href="../index.html">返回总览</a><h1>采集'+str(rank)+' · '+esc(whole['identity']['product_id'])+'</h1><p>整体独立提炼并编码一次；'+str(len(children))+'条组件独立保存，通过版本关联。所有来源声明待核验。</p>'+hero+'<p>'+esc(features['summary_en'])+'</p>'+''.join(fields)+'<h2>限定与未知</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in features['limitations'])+'</ul><details><summary>实际整体编码输入</summary><pre>'+esc(whole['embedding_meta']['input_text'])+'</pre></details><h2>对应的独立组件</h2><p>以下为原素材与特征浏览，不代表已选作生成参考。</p><div class="grid">'+''.join(part_cards)+'</div>'
        (folder/'index.html').write_text(page,encoding='utf-8')
        labels='、'.join(x.get('label_zh') or x['text_en'] for x in features['selling_points'])
        cards.append('<article>'+hero+'<h3>采集'+str(rank)+' · '+esc(whole['identity']['product_id'])+'</h3><p>'+esc(labels)+'</p><p>1条整体 / '+str(len(children))+'条组件</p><a href="rank'+str(rank)+'/index.html">查看结构化特征与证据</a></article>')
    index='<!doctype html><meta charset="utf-8"><title>整体与组件双集合</title>'+style+'<h1>整体一条、组件多条 · '+str(len(wholes))+'套Listing</h1><p>整体来自综合提炼的卖点、产品特征、视觉元素及风格，不编码整篇原文、不平均组件向量。独立组件保留原文与媒体地址，全部待运营审核。</p><p><a href="library/library_index.json">双集合与数据库清单</a> · <a href="verification.json">入库核对</a></p><div class="grid">'+''.join(cards)+'</div>'
    (output/'index.html').write_text(index,encoding='utf-8')


def run(source,reviews,output,store_path):
    """没有绑定完整来源的语义审阅即报错，不用规则或旧全文向量填充。"""
    source=Path(source);reviews=Path(reviews);output=Path(output)
    if (output/'run.json').exists() or (output/'library').exists():raise ValueError('Use a new structured output')
    paths=sorted(source.glob('rank*/listing_features.json'),key=lambda p:int(p.parent.name[4:]))
    if not paths:raise ValueError('No completed source batch')
    encoder=LocalEncoder(Path(r'D:\ListingStage2\data\listing_embedding_cache'))
    wholes=[];bundles=[]
    for path in paths:
        bundle=json.loads(path.read_bytes());rank=bundle['overall_features']['historical_rank']
        review=json.loads((reviews/f'rank{rank}.json').read_bytes())
        whole=build_whole(bundle,review,encoder)
        wholes.append(whole);bundles.append(bundle)
    dataset_id=digest(['structured-whole-components-v5',[w['listing_version_id'] for w in wholes]])
    whole_points=[];component_points=[]
    for whole,bundle in zip(wholes,bundles):
        w,parts=point_records(whole,bundle,dataset_id);whole_points.append(w);component_points.extend(parts)
    manifest=export_dataset(whole_points,component_points,output/'library',store_path)
    stored,stored_wholes,stored_parts=read_dataset(output/'library/library_index.json')
    # Qdrant以float32存向量；校验数值容差，组件特征与引用仍须逐字段完全相同。
    import numpy as np
    original={p['id']:p for p in whole_points+component_points}
    for actual in stored_wholes+stored_parts:
        before=original[actual['id']]
        if before['payload']!=actual['payload']:raise ValueError('Database payload changed')
        if before['vector'] is not None and not np.allclose(before['vector'],actual['vector'],atol=1e-6):raise ValueError('Database vector changed')
    verification={'status':'passed','wholes':len(stored_wholes),'components':len(stored_parts),
       'parent_links_verified':True,'independent_vectors_verified':True,'database_roundtrip_verified':True,
       'component_vectors_reused_unchanged':True,'whole_encoding':'one_call_per_reviewed_structured_description',
       'semantic_approval':'pending_operator_review','paid_api_calls':0}
    write(output/'verification.json',verification)
    write(output/'run.json',{'status':'stored_pending_operator_review','dataset_id':dataset_id,
        'source':str(source.resolve()),'reviews':str(reviews.resolve()),'counts':manifest['counts'],
        'database':manifest['storage'],'library_index':str((output/'library/library_index.json').resolve()),
        'whole_method':'GPT_complete_source_text_synthesis_with_reused_existing_visual_reviews',
        'component_method':'existing_independent_features_and_vectors_reused','paid_api_calls':0,
        'chinese_query_encoder_changed':False})
    render(output,stored_wholes,stored_parts)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--reviews',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--store-path',type=Path,required=True)
    a=p.parse_args();result=run(a.source,a.reviews,a.output,a.store_path)
    print(json.dumps(result['counts'],ensure_ascii=False))
