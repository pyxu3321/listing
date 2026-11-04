# 文件用途：历史五商品结果导出，写JSON与本地HTML；publish仅指写报告，不发布亚马逊。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import html
from .storage import write

# 功能及输出：输入目录、旧payload、聚类、评分和原则；写本地报告与HTML，媒体仍引用原文件；不联网发布。
# 参数：out（输出目录）；payload（旧实验结构化数据）；clusters（候选聚类）；quality（质量记录）；principles（候选借鉴原则）。
def publish(out,payload,clusters,quality,principles):
    write(out/'payload.json',payload)
    write(out/'clusters.json',clusters)
    write(out/'quality.json',quality)
    write(out/'principles.json',principles)
    assets={a['asset_sha256']:a for a in payload['assets']}
    refs={r['reference_id']:r for r in payload['references']}
    from pathlib import Path
    cards=[]
    membership={m['feature_id']:g['cluster_id'] for g in clusters for m in g['members']}
    for f in payload['features']:
        if not f['image_reference_id']: continue
        ref=refs[f['image_reference_id']]; asset=assets[ref['asset_sha256']]
        esc=html.escape
        cards.append('<article><img loading="lazy" src="'+esc(Path(asset['local_path']).as_uri())+'"><h2>'+esc(f['entity_key'])+'</h2><p>'+esc(ref['source_role']+' / '+membership[f['feature_id']])+'</p><pre>'+esc(__import__('json').dumps(f['features'],ensure_ascii=False,indent=2))+'</pre></article>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>第二阶段特征库</title><style>body{font-family:Arial;background:#f3f6f4;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}article{background:white;padding:16px;border-radius:12px}img{width:100%;height:230px;object-fit:contain}pre{white-space:pre-wrap;font-size:13px}</style><h1>第二阶段 · 前五个商品特征库</h1><p>复用已有 GPT 逐图审阅；分组基于描述文本向量。质量分待校准；未执行新的视觉 API 或像素向量。</p><main>'+''.join(cards)+'</main>',encoding='utf-8')
    write(out/'stage3_bundle.json',{'schema_version':1,'status':'pending_review','payload':'payload.json','clusters':'clusters.json','quality':'quality.json','principles':'principles.json','image_embeddings_status':'not_implemented','video_status':'skipped_no_input','rank_is_quality':False})
