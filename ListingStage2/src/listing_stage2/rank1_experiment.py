# 文件用途：第一名v3独立整体/组件实验，读取人工审阅和补充视频下载记录；可选写入历史试验MySQL。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Run the reviewed rank-one experiment, including the separately downloaded video."""
import argparse
import json
from pathlib import Path
import html
from .settings import ROOT
from .phase1_reader import load
from .listing_bundles import assemble
from .whole_listing import attach_video, build
from .local_encoder import LocalEncoder
from .storage import write, equivalent


REVIEW=ROOT/'config/rank1-whole-review.json'
VIDEO=Path('D:/Crawl4AI/library/products/US/amazon/toppers/B0FVYBPSWY/20261029T004510Z_fdcb2277_content_a81a90/视频/视频下载记录.json')


# 功能及输出：输入人工整体审阅；从冻结数据选择第一名并挂接已下载视频，返回原始分析包。
# 参数：review（绑定输入指纹的整体审阅）。
def source_bundle(review):
    payload=load()
    report=json.loads(Path(payload['provenance']['source_report']).read_text(encoding='utf-8'))
    first=min(report['products'],key=lambda p:p.get('listing_rank') or 999999)
    bundle=next(b for b in assemble(payload,report) if b['identity']['snapshot_id']==first['snapshot_id'])
    # Product-level analysis belongs in overall_features, not among selectable parts.
    bundle['parts']=[p for p in bundle['parts'] if p['entity_kind']!='product']
    return attach_video(bundle,VIDEO,review['video_features'])


# 功能及输出：第一名实验CLI；本地编码并写页面/结果指针，--mysql时写数据库并读回验证。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,default=REVIEW)
    parser.add_argument('--mysql',action='store_true')
    args=parser.parse_args()
    review=json.loads(args.review.read_text(encoding='utf-8'))
    result=build(source_bundle(review),review,LocalEncoder(ROOT/'data/listing_embedding_cache'))
    i=result['identity']
    out=ROOT/'outputs/experiments/rank1-v3'/result['bundle_id'][:20]
    relative=Path('catalog',i['country_code'],i['site_id'],i['category_id'],i['product_id'],i['snapshot_id'],'listing_features.json')
    write(out/relative,result)
    write(out/'stage3_bundle.json',{'schema_version':3,'status':'pending_operator_review','retrieval_unit':'whole_listing','listing_path':relative.as_posix(),'overall_vector_path':'embedding.vector','part_vectors_path':'parts[].embedding.vector','selectable_parts':[{'part_id':p['part_id'],'role':p['role']} for p in result['parts']]})
    esc=lambda x:html.escape(str(x),quote=True)
    cards=[]
    for p in result['parts']:
        asset=p.get('asset')
        media=''
        if asset:
            url=esc(Path(asset['local_path']).as_uri())
            media='<video controls preload="metadata" src="'+url+'"></video>' if p['role']=='video' else '<img loading="lazy" src="'+url+'">'
        cards.append('<article><h3>'+esc(p['role'])+'</h3>'+media+'<pre>'+esc(p['source_text'] or json.dumps(p['features'],ensure_ascii=False,indent=2))+'</pre><small>'+esc(p['part_id'])+'</small></article>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>排名第一 · 整体特征实验</title><style>body{font:16px system-ui;background:#f4f6f8;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}section,article{background:white;padding:20px;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}img,video{width:100%;max-height:280px;object-fit:contain}small{overflow-wrap:anywhere}</style><h1>排名第一 · 整套 Listing 特征</h1><p>整体向量来自下方整体描述；各部分单独编码。待运营审核；视频只分析关键帧，未转录语音。</p><section><h2>整体关键词、卖点与表达策略</h2><pre>'+esc(json.dumps(result['overall_features'],ensure_ascii=False,indent=2))+'</pre><p>整体向量 '+str(result['embedding']['dimensions'])+' 维</p><a href="'+esc(relative.as_posix())+'">完整特征与向量 JSON</a></section><div class="grid">'+''.join(cards)+'</div>',encoding='utf-8')
    mysql='not_requested'
    if args.mysql:
        from .pipeline import legacy
        conn=legacy().connect()
        try:
            with conn.cursor() as c:
                c.execute('CREATE TABLE IF NOT EXISTS stage2_whole_listing_v3 (bundle_id VARCHAR(64) PRIMARY KEY, bundle_json JSON NOT NULL)')
                c.execute('INSERT INTO stage2_whole_listing_v3 (bundle_id,bundle_json) VALUES (%s,%s) ON DUPLICATE KEY UPDATE bundle_json=VALUES(bundle_json)',(result['bundle_id'],json.dumps(result,ensure_ascii=False)))
            conn.commit()
            with conn.cursor() as c:
                c.execute('SELECT bundle_json FROM stage2_whole_listing_v3 WHERE bundle_id=%s',(result['bundle_id'],))
                if not equivalent(result,json.loads(c.fetchone()[0])):raise ValueError('Whole Listing readback failed')
            mysql='committed_and_verified'
        finally:conn.close()
    status={'status':'ready_for_operator_review','bundle_id':result['bundle_id'],'overall_vectors':1,'part_vectors':sum('embedding' in p for p in result['parts']),'parts':len(result['parts']),'mysql':mysql,'paid_api_calls':0,'directory':str(out),'viewer':str(out/'index.html')}
    write(out/'run.json',status)
    write(ROOT/'outputs/rank1-latest.json',status)
    print(json.dumps(status,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
