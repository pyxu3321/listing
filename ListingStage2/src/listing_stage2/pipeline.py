# 文件用途：历史五商品v2流程与可选MySQL试验；不等同于新API流程，不自动升级旧向量配方。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import argparse, json, importlib.util, sys
from pathlib import Path
from .settings import ROOT, LEGACY
from .phase1_reader import load
from .contracts import validate, sha
from .clustering import group
from .scoring import assess, principles
from .export import publish
from .storage import write, equivalent
from .listing_bundles import assemble, encode_bundle, export_bundles
from .local_encoder import LocalEncoder

# 功能及输出：动态载入D:/ListingAnalysis旧pipeline，并扩展模块搜索路径；返回模块供刷新/历史数据库试验使用。
def legacy():
    sys.path.insert(0,str(LEGACY/'.deps')); sys.path.insert(0,str(LEGACY))
    spec=importlib.util.spec_from_file_location('pilot_pipeline',LEGACY/'experiments/gpt_top5/pipeline.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

# 功能及输出：历史CLI：加载/刷新旧payload、v2编码聚类导出，可选写MySQL并读回验证；有本地服务和可选数据库副作用。
def main():
    p=argparse.ArgumentParser(description='Stage 2 frozen-five pilot, no paid API calls')
    p.add_argument('--payload',type=Path,help='Validated reviewed feature payload; default is the frozen pilot')
    p.add_argument('--threshold',type=float,default=.78)
    p.add_argument('--mysql',action='store_true')
    p.add_argument('--refresh-vectors',action='store_true')
    args=p.parse_args()
    if args.payload and args.refresh_vectors: p.error("--payload and --refresh-vectors are mutually exclusive")
    if args.refresh_vectors:
        mod=legacy(); mod.OUT=ROOT/'data/runtime';mod.PAYLOAD=ROOT/'data/cache/payload.json'
        mod.OUT.mkdir(parents=True,exist_ok=True);mod.PAYLOAD.parent.mkdir(parents=True,exist_ok=True)
        mod.build_payload(); payload=validate(json.loads(mod.PAYLOAD.read_text(encoding='utf-8')))
    elif args.payload: payload=validate(json.loads(args.payload.read_text(encoding='utf-8')))
    else: payload=load()
    report=json.loads(Path(payload['provenance']['source_report']).read_text(encoding='utf-8'))
    encoder=LocalEncoder(ROOT/'data/listing_embedding_cache')
    bundles=[encode_bundle(b,encoder) for b in assemble(payload,report)]
    run=sha(json.dumps([payload['batch_id'],'stage2-listing-v2',args.threshold,encoder.digest,[(b['bundle_id'],b['embedding']['input_sha256']) for b in bundles]],sort_keys=True).encode())[:20]
    out=ROOT/'outputs/batches'/run
    clusters=group(payload,args.threshold)
    publish(out,payload,clusters,assess(payload),principles(payload))
    export_bundles(out,bundles)
    handoff=json.loads((out/'stage3_bundle.json').read_text(encoding='utf-8'))
    handoff.update(schema_version=2,retrieval_unit='whole_listing',listing_index='listing_index.json',part_selection_supported=True)
    write(out/'stage3_bundle.json',handoff)
    status={'run_id':run,'status':'ready_for_review','products':len(payload['snapshots']),'images':len(payload['assets']),'text_vectors':len(payload['embeddings']),'clusters':len(clusters),'paid_api_calls':0,'mysql':'not_requested','whole_listing_vectors':len(bundles),'listing_dimensions':encoder.dimensions,'overall_vector_recipe':bundles[0]['recipe'] if bundles else None}
    if args.mysql:
        mod=legacy();mod.PAYLOAD=out/'payload.json';mod.OUT=out
        status['mysql']=mod.load_mysql()
        conn=mod.connect()
        try:
            with conn.cursor() as c:
                c.execute('CREATE TABLE IF NOT EXISTS stage2_exports (run_id VARCHAR(64) PRIMARY KEY, result_json JSON NOT NULL)')
                c.execute('INSERT INTO stage2_exports (run_id,result_json) VALUES (%s,%s) ON DUPLICATE KEY UPDATE result_json=VALUES(result_json)',(run,json.dumps({'clusters':clusters,'quality':assess(payload),'principles':principles(payload)},ensure_ascii=False)))
                c.execute('CREATE TABLE IF NOT EXISTS stage2_listing_bundles (run_id VARCHAR(64) NOT NULL, bundle_id VARCHAR(64) NOT NULL, bundle_json JSON NOT NULL, PRIMARY KEY (run_id,bundle_id))')
                for bundle in bundles:
                    c.execute('INSERT INTO stage2_listing_bundles (run_id,bundle_id,bundle_json) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE bundle_json=VALUES(bundle_json)',(run,bundle['bundle_id'],json.dumps(bundle,ensure_ascii=False)))
                c.execute('SELECT bundle_id,bundle_json FROM stage2_listing_bundles WHERE run_id=%s',(run,))
                saved={row[0]:json.loads(row[1]) if isinstance(row[1],str) else row[1] for row in c.fetchall()}
                if not equivalent(saved,{b['bundle_id']:b for b in bundles}): raise ValueError('Listing bundle database readback mismatch')
            conn.commit()
            status['whole_listing_mysql_verified']=True
        except Exception:
            conn.rollback()
            raise
        finally: conn.close()
    write(out/'run.json',status)
    write(ROOT/'outputs/latest.json',{'run_id':run,'directory':str(out),'viewer':str(out/'listings.html'),'parts_viewer':str(out/'index.html')})
    print(json.dumps(status,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
