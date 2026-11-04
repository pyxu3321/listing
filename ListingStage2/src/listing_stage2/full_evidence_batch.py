"""从已有完整组件原文及视觉审阅重建整体向量，输出新批次，不覆盖历史数据。"""
import argparse
import hashlib
import json
from pathlib import Path
from .local_encoder import LocalEncoder
from .whole_document import upgrade,RECIPE
from .reference_library import export_library
from .storage import write
from .batch_review import render


def run(source,output,library,max_chars=2000):
    """逐套重建并检查全文参与情况；全部成功后发布独立参考库索引。

    source为已完成第二阶段批次，组件向量及原图沿用，整体向量重新编码。
    当前是完整证据编码，不宣称执行了新的LLM卖点归纳。
    """
    source=Path(source);output=Path(output);library=Path(library)
    if output.exists() or library.exists():raise ValueError('Use new output and library directories')
    paths=sorted(source.glob('rank*/listing_features.json'),key=lambda p:int(p.parent.name[4:]))
    if not paths:raise ValueError('No reviewed bundles found')
    output.mkdir(parents=True);encoder=LocalEncoder(Path(r'D:\ListingStage2\data\listing_embedding_cache'))
    bundles=[];products=[];verification=[]
    try:
        for path in paths:
            raw=path.read_bytes();old=json.loads(raw)
            if old['embedding']['model_digest']!=encoder.digest:raise ValueError('Model changed; component vectors must be rebuilt first')
            rank=old['overall_features']['historical_rank'];new=upgrade(old,encoder,max_chars)
            if old['identity']!=new['identity'] or old['parts']!=new['parts']:raise ValueError('Changed source or component embeddings')
            document=new['embedding']['input_text'];sections=new['whole_document']['sections'];coverage=new['whole_document']['coverage']
            by_id={p['part_id']:p for p in old['parts']}
            for pid in coverage['source_text_part_ids']:
                found=[s for s in sections if any(e['part_id']==pid for e in s['evidence'])]
                if len(found)!=1 or found[0]['text']!=by_id[pid]['source_text']:raise ValueError('Incomplete source text coverage')
            if new['embedding']['encoded_characters']!=len(document):raise ValueError('Input coverage mismatch')
            folder=output/f'rank{rank}'
            write(folder/'listing_features.json',new);write(folder/'whole_document.json',new['whole_document'])
            folder.joinpath('whole_input.txt').write_text(document,encoding='utf-8')
            write(folder/'source_statements.json',new['overall_features']['source_statements'])
            write(folder/'provenance.json',{'previous_file':str(path.resolve()),'previous_sha256':hashlib.sha256(raw).hexdigest(),
                'previous_bundle_id':old['bundle_id'],'new_bundle_id':new['bundle_id'],'original_assets_changed':False})
            row={'rank':rank,'asin':old['identity']['product_id'],'components':len(old['parts']),
                'component_vectors':sum(bool(p.get('embedding')) for p in old['parts']),
                'whole_document_characters':len(document),'whole_chunks':len(new['whole_document']['chunks']),
                'source_text_parts':len(coverage['source_text_part_ids']),'raw_text_characters':coverage['raw_text_characters']}
            products.append(row);bundles.append(new);verification.append({'rank':rank,'full_text_exact_match':True,'component_vectors_unchanged':True,'all_chunks_encoded':True})
            write(output/'progress.json',{'status':'encoding','completed':len(bundles),'total':len(paths),'latest':row})
            print(json.dumps(row),flush=True)
        index=export_library(bundles,library)
        stats={'status':'encoded_pending_operator_review','recipe':RECIPE,'listings':len(bundles),'whole_vectors':len(index['whole_index']),
            'component_vectors':sum(x['component_vectors'] for x in products),'active_component_vectors':len(index['component_index']),
            'dimensions':encoder.dimensions,'model':encoder.model,'model_digest':encoder.digest,'paid_api_calls':0,
            'llm_semantic_review_executed':False,'source_text_truncated':False,'products':products,
            'mysql_sync':'not_executed','qdrant_sync':'not_executed','library_index':str(library/'library_index.json')}
        write(output/'run.json',stats);write(output/'verification.json',{'status':'passed','products':verification,
            'scope':'source inclusion and vector integrity, not semantic coverage or quality'})
        render(output,bundles,stats)
        for page_path in output.glob('rank*/index.html'):
            content=page_path.read_text(encoding='utf-8')
            page_path.write_text('<nav><a href="whole_input.txt">完整整体编码输入</a> · <a href="source_statements.json">完整来源文字声明</a> · <a href="whole_document.json">分块、来源与覆盖记录</a></nav>'+content,encoding='utf-8')
        # 通用旧页面的文案针对v3，本次覆盖简介，避免误称只是原来的单段摘要编码。
        p=output/'index.html';page=p.read_text(encoding='utf-8');start=page.index('<h1>');end=page.index('<div class="grid">',start)
        page=page[:start]+'<h1>完整证据整体向量 · '+str(len(bundles))+'套Listing</h1><p>完整标题、五点、已采集详情/A+文字及已有视觉描述进入整体文档；分块编码后汇成一个整体向量，组件向量独立保留。不执行新LLM语义归纳，来源声明待核验。</p><a href="run.json">批次记录</a> · <a href="verification.json">完整性验证</a>'+page[end:]
        p.write_text(page,encoding='utf-8')
        write(output/'progress.json',{'status':'finished','completed':len(bundles),'total':len(paths)})
        return stats
    except Exception as error:
        write(output/'progress.json',{'status':'failed','completed':len(bundles),'total':len(paths),'error':str(error)})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--library',type=Path,required=True)
    p.add_argument('--max-chars',type=int,default=2000);args=p.parse_args()
    run(args.source,args.output,args.library,args.max_chars)
