"""把本次GPT逐项审阅写入双层特征库，并生成可核对的实验页面。

该入口不自动猜测图片内容：每个图片/视频组件必须在annotations.json中有审阅。
文字保留全文作为来源声明；本地nomic模型只编码语义描述，不直接编码图片像素。
"""
import argparse
from collections import Counter
from pathlib import Path
import json
import html
import hashlib
import numpy as np
from .features import validate_part, validate_whole
from .whole_listing import build, input_fingerprint
from .local_encoder import LocalEncoder
from .reference_library import export_library
from .storage import write


def run(directory, library):
    """读取冻结任务与外部审阅，逐套生成整体向量、组件向量及可追溯索引。

    输出只写本实验，不覆盖历史结果或采集任务。所有结果仍待运营审核。
    """
    directory=Path(directory);library=Path(library)
    notes=json.loads((directory/'annotations.json').read_text(encoding='utf-8'))
    encoder=LocalEncoder(directory/'embedding_cache')
    bundles=[];cards=[];summary=[]
    for rank in range(1,6):
        folder=directory/f'rank{rank}'
        task=json.loads((folder/'task.json').read_text(encoding='utf-8'))
        note=notes[str(rank)];description=note['whole']
        task['coverage'].update(video_status='eight_sampled_frames_reviewed_audio_not_transcribed',analysis_method='GPT_in_Codex_conversation_contact_sheets_and_source_text',image_analysis_scope='contact_sheet_visual_features_not_full_resolution_OCR')
        for index,p in enumerate(task['parts']):
            item=note.get('parts',{}).get(str(index))
            if p['entity_kind']!='text' and item is None:
                raise ValueError(f'Missing visual review rank{rank} part{index}')
            if p.get('asset') and hashlib.sha256(Path(p['asset']['local_path']).read_bytes()).hexdigest()!=p['asset']['asset_sha256']:
                raise ValueError('Source asset changed')
            item=item or {}
            text=p.get('source_text')
            semantic=item.get('description') or ('Competitor '+p['role']+' source claims, not independently verified: '+text)
            limits=['竞品参数、认证及功效均未经独立核验，不可迁移为自有产品事实。']
            if p['entity_kind']=='image':limits.append('基于联系图识别构图与视觉主题，细小文字未逐字核对。')
            if p['entity_kind']=='video':limits.append('只检查8个采样帧，未观看连续全片、未转录或理解音频。')
            limits+=item.get('limitations',[])
            scope=item.get('scope','current_or_family')
            p['features']=validate_part({'semantic_description_en':semantic,'identity_scope':scope,
                'composition':item.get('composition','原文顺序见source_text' if p['entity_kind']=='text' else '具体构图、镜头与信息布局见semantic_description_en'),
                'palette':item.get('palette',note['palette'] if p['entity_kind']!='text' else []),
                'scene':item.get('scene','文字说明' if p['entity_kind']=='text' else '具体场景见semantic_description_en；整体场景：'+note['scene']),
                'themes':item.get('themes',note['themes'] if p['entity_kind']=='text' else []),
                'claims':[{'text':text,'basis':'source_claim'}] if text else [],'limitations':limits})
            p['features']['observed_text_claims_verified']=False
            p['features']['analysis_method']='GPT_in_Codex_conversation'
            p['features']['component_kind']=item.get('kind',p['entity_kind'])
            if item.get('exclude'):
                p['eligible_for_aggregate']=False
                p['analysis_controls']={'include_in_overall':False,'embed':True,'retrieve':False,'generation_reference':False}
            elif item.get('generation_reference') is False:
                p['analysis_controls']={'generation_reference':False}
        whole={k:description[k] for k in ('keywords','audience','scenes','style','information_order','limitations','embedding_text_en')}
        whole['selling_points']=[{'text':x['text'],'evidence_part_ids':[task['parts'][i]['part_id'] for i in x['parts']]} for x in description['selling_points']]
        validate_whole(whole,{p['part_id'] for p in task['parts']})
        whole['product_form']=note['product_form']
        whole['historical_rank']=rank
        whole['product_form_basis']='inferred_from_captured_product_images_and_source_text_not_verified_own_facts'
        review={'input_fingerprint':input_fingerprint(task),'reviewer':'GPT_in_Codex_conversation','review_date':'2026-11-03','status':'pending_operator_review','overall_features':whole}
        write(folder/'analyzed_bundle.json',task);write(folder/'review.json',review)
        result=build(task,review,encoder)
        write(folder/'listing_features.json',result);bundles.append(result)
        summary.append({'rank':rank,'asin':task['identity']['product_id'],'product_form':note['product_form'],'components':len(result['parts']),'component_vectors':sum('embedding' in p for p in result['parts']),'roles':dict(Counter(p['role'] for p in result['parts'])),'excluded_references':[i for i,p in enumerate(result['parts']) if p.get('analysis_controls',{}).get('retrieve') is False]})
        cards.append(render_listing(rank,result))
        print(json.dumps(summary[-1]),flush=True)
    # 不用全局默认覆盖逐项排除标记；沿用每个组件的明确审阅控制。
    manifest=export_library(bundles,library)
    matrix=np.asarray([b['embedding']['vector'] for b in bundles])
    write(directory/'whole_similarity.json',{'asins':[b['identity']['product_id'] for b in bundles],'cosine_similarity':(matrix@matrix.T).tolist(),'note':'五套样本的探索性整体相似度，不是质量评分或成熟聚类结论。'})
    status={'whole_vectors':len(manifest['whole_index']),'component_vectors':sum(x['component_vectors'] for x in summary),'retrievable_component_vectors':len(manifest['component_index']),'embedding_model':encoder.model,'dimensions':encoder.dimensions,'image_vector_method':'visual_features_to_text_then_local_text_embedding','paid_api_calls':0,'mysql_sync':'not_executed','qdrant_sync':'not_executed','approval':'pending_operator_review','listings':summary,'library_index':str(library/'library_index.json')}
    write(directory/'run.json',status)
    (directory/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>前五名·第二阶段实验</title><style>body{font:15px system-ui;margin:24px;background:#f2f5f8;color:#1b2938}section,article{background:white;padding:18px;margin:12px 0;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}details{margin:12px 0}img,video{width:100%;height:240px;object-fit:contain}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}.badge{background:#e4edf5;padding:6px}</style><h1>前五名 · 整体与组件特征实验</h1><p>GPT在当前对话提取视觉特征；本地nomic将语义描述编码为768维文本向量。整体独立编码，不平均组件。视频每个抽8帧，音频未转录。全部待运营审核。</p><p>保留视频封面、关联商品及品牌素材，但按逐项标记排除当前商品参考用途。相似度不是质量分，不据此推断销量。</p><a href="run.json">运行摘要</a> · <a href="whole_similarity.json">整体相似度矩阵</a>'+''.join(cards),encoding='utf-8')
    return status


def render_listing(rank,bundle):
    """离线展示每个整体及每项组件；直接引用归档媒体，不复制或改变原图。"""
    esc=lambda x:html.escape(str(x),quote=True)
    cards=[]
    for i,p in enumerate(bundle['parts']):
        media=''
        if p.get('asset'):
            url=esc(Path(p['asset']['local_path']).as_uri())
            media=('<video controls preload="none" src="'+url+'"></video>') if p['role']=='video' else ('<img loading="lazy" src="'+url+'">')
        exclude=p.get('analysis_controls',{}).get('retrieve') is False
        label='保留来源，排除当前商品参考' if exclude else '待审核参考'
        cards.append('<article><h3>'+str(i)+' · '+esc(p['role'])+'</h3><p class="badge">'+label+'</p>'+media+'<p>'+esc(p['features']['semantic_description_en'])+'</p><details><summary>原文、特征及证据</summary><pre>'+esc(json.dumps({k:v for k,v in p.items() if k!='embedding'},ensure_ascii=False,indent=2))+'</pre></details></article>')
    return '<section><h2>历史第'+str(rank)+'名 · '+esc(bundle['identity']['product_id'])+'</h2><pre>'+esc(json.dumps(bundle['overall_features'],ensure_ascii=False,indent=2))+'</pre><a href="rank'+str(rank)+'/listing_features.json">完整特征与向量</a><details><summary>展开全部'+str(len(cards))+'个组件</summary><div class="grid">'+''.join(cards)+'</div></details></section>'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--library',type=Path,required=True)
    a=p.parse_args();print(json.dumps(run(a.input,a.library),ensure_ascii=False,indent=2))
