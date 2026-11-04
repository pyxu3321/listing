"""50套已捕获Listing的第二阶段批处理：冻结、审阅任务、整体/组件独立编码。

视觉判断来自外部逐项审阅文件，不用文件名、排名或文本模型猜图。当前由GPT在
对话内查看联系图填写审阅；模板只把已选择的视觉标签转成可编码描述。未来可以
由图文API提供同一数据契约。没有审阅的素材必须报错，禁止自动填充后冒充完成。
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse,hashlib,html,json,shutil
import cv2
from PIL import Image
from .features import from_report,validate_part,validate_whole
from .listing_bundles import digest
from .storage import write
from .whole_listing import build,input_fingerprint
from .local_encoder import LocalEncoder
from .reference_library import export_library
from .prepare_five_experiment import sheet


def signature(bundle):
    """按组件ID、角色、内容、原件哈希和来源绑定比较，不把图片缩略图当原件。"""
    return digest({'identity':bundle['identity'],'parts':[{k:p.get(k) for k in ('part_id','role','source_text','asset','reference','module_placements')} for p in bundle['parts']]})


def prepare(report_path,output,reuse):
    """冻结完成报告，校验归档原件，生成逐商品图片联系图及视频8帧审阅任务。

    report_path：完成的第一阶段报告。output须为空。reuse：前五名已审阅实验目录。
    输出稳定源报告及task.json；不会改变第一阶段或旧实验。
    """
    output=Path(output);reuse=Path(reuse)
    if output.exists():raise ValueError('Use a new batch output')
    raw=Path(report_path).read_bytes();report=json.loads(raw)
    if report['status']!='success' or len(report['products'])!=50:raise ValueError('Need completed 50-product report')
    output.mkdir(parents=True);(output/'source_report.json').write_bytes(raw)
    write(output/'provenance.json',{'source_report':str(report_path),'source_report_sha256':hashlib.sha256(raw).hexdigest(),'reuse_directory':str(reuse),'no_new_web_capture':True})
    products=[];seen_hashes=set()
    for p in sorted(report['products'],key=lambda x:x['listing_rank']):
        rank=p['listing_rank'];folder=output/f'rank{rank}';folder.mkdir()
        task=from_report(output/'source_report.json',rank)
        for m in p['media']:
            if m.get('status')!='stored':continue
            if m['sha256'] not in seen_hashes:
                if hashlib.sha256(Path(m['path']).read_bytes()).hexdigest()!=m['sha256']:raise ValueError('Changed asset')
                seen_hashes.add(m['sha256'])
            if m.get('kind')!='video':continue
            task['parts'].append({'part_id':digest(['video',m['sha256'],task['identity']]),'role':'video','entity_kind':'video','source_text':None,'features':{},'reference':{'snapshot_id':p['snapshot_id'],'source_url':m['source_url'],'asset_sha256':m['sha256']},'asset':{'local_path':m.get('export_path') or m['path'],'asset_sha256':m['sha256']},'is_main_image':False,'eligible_for_aggregate':True,'module_placements':[]})
        old=reuse/f'rank{rank}'
        can_reuse=False
        if rank<=5 and (old/'task.json').exists():
            previous=json.loads((old/'task.json').read_bytes())
            # 视频存储路径可能改用对象归档，但内容/来源必须相同；路径别名本身不是新内容。
            canonical=lambda b:[(x['part_id'],x['role'],x.get('source_text'),(x.get('asset') or {}).get('asset_sha256'),x['reference'],x.get('module_placements',[])) for x in b['parts']]
            can_reuse=canonical(task)==canonical(previous)
        if can_reuse:
            for name in ['listing_features.json','review.json','analyzed_bundle.json']:
                shutil.copyfile(old/name,folder/name)
            task=previous
            write(folder/'reuse.json',{'verified_content_signature':signature(previous),'source':str(old),'status':'same_components_and_asset_hashes_review_reused'})
        else:
            image_cards=[];video_cards=[]
            for i,part in enumerate(task['parts']):
                asset=part.get('asset')
                if part['entity_kind']=='image':
                    with Image.open(asset['local_path']) as im:image=im.convert('RGB')
                    image_cards.append((f"part {i} | {part['role']}",image))
                elif part['entity_kind']=='video':
                    cap=cv2.VideoCapture(asset['local_path']);n=cap.get(cv2.CAP_PROP_FRAME_COUNT);fps=cap.get(cv2.CAP_PROP_FPS);times=[]
                    if not n or not fps:raise ValueError('Cannot sample video')
                    for j in range(8):
                        fi=round((n-1)*(j+.5)/8);cap.set(cv2.CAP_PROP_POS_FRAMES,fi);ok,frame=cap.read()
                        if not ok:raise ValueError('Frame sample failed')
                        stamp=round(fi/fps,2);times.append(stamp)
                        video_cards.append((f'part {i} | {stamp}s',Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))))
                    cap.release();part['sampled_frame_evidence']={'sample_count':8,'timestamps_seconds':times,'audio_transcribed':False,'contact_sheet':str(folder/'video.jpg')}
            sheet(image_cards,folder/'images.jpg')
            if video_cards:sheet(video_cards,folder/'video.jpg')
        task['bundle_id']=digest([task['identity'],task['parts']])
        write(folder/'task.json',task)
        row={'rank':rank,'asin':p['requested_asin'],'components':len(task['parts']),'roles':dict(Counter(x['role'] for x in task['parts'])),'review_reused':can_reuse}
        products.append(row);print(json.dumps(row),flush=True)
    write(output/'preparation.json',products)
    return products


def encode(output,library,annotations_path):
    """校验完整审阅后编码；保存逐商品断点，全部成功才导出50套活动索引。

    annotations_path保存明确的逐组件特征及独立整体叙述；仅可复用签名一致的审阅。
    embeddings为视觉语义文字的本地文本向量，不是原生像素向量。
    """
    output=Path(output);notes=json.loads(Path(annotations_path).read_bytes());plans=json.loads((output/'preparation.json').read_bytes())
    encoder=LocalEncoder(Path(r'D:\ListingStage2\data\listing_embedding_cache'));bundles=[];summary=[]
    for plan in plans:
        rank=plan['rank'];folder=output/f'rank{rank}';task=json.loads((folder/'task.json').read_bytes())
        if plan['review_reused']:
            result=json.loads((folder/'listing_features.json').read_bytes())
            if result['embedding']['model_digest']!=encoder.digest:raise ValueError('Changed embedding model')
            # 此入口保留v3历史实验；不再自动把复用记录转成全文汇聚向量。
            # 当前整体/组件双集合流程使用structured_batch和绑定完整来源的结构化审阅。
        else:
            note=notes[str(rank)]
            if note['input_signature']!=signature(task):raise ValueError('Stale review')
            if set(note['parts'])!={str(i) for i in range(len(task['parts']))}:raise ValueError('Incomplete component review')
            task=deepcopy(task)
            for i,part in enumerate(task['parts']):
                value=note['parts'][str(i)]
                part['features']=validate_part(value['features'])
                part['eligible_for_aggregate']=value.get('eligible_for_aggregate',True)
                part['analysis_controls']=value.get('analysis_controls',{})
                part['review_method']=value.get('review_method','GPT_contact_sheet_tag_review_and_source_text')
            overall=validate_whole(note['overall_features'],{p['part_id'] for p in task['parts'] if p['eligible_for_aggregate']})
            overall['product_form']=note['product_form'];overall['historical_rank']=rank
            task['coverage'].update(video_status='eight_sampled_frames_reviewed_audio_not_transcribed' if any(p['role']=='video' for p in task['parts']) else 'not_observed_in_source',image_analysis_scope='contact_sheet_visual_tag_review_not_full_resolution_OCR')
            review={'input_fingerprint':input_fingerprint(task),'overall_features':overall,'producer':'GPT_in_Codex_conversation','review_date':'2026-11-03','approval_status':'pending_operator_review','visual_method':'contact_sheet_tags_with_explicit_caption_templates','annotation_file':str(annotations_path)}
            write(folder/'analyzed_bundle.json',task);write(folder/'review.json',review)
            result=build(task,review,encoder);write(folder/'listing_features.json',result)
        bundles.append(result)
        row={**plan,'whole_vector_dimensions':result['embedding']['dimensions'],'component_vectors':sum('embedding' in p for p in result['parts']),'product_form':result['overall_features'].get('product_form')}
        summary.append(row);print(json.dumps(row),flush=True)
    manifest=export_library(bundles,library)
    import numpy as np
    matrix=np.asarray([b['embedding']['vector'] for b in bundles])
    write(output/'whole_similarity.json',{'rank_order':[p['rank'] for p in summary],'cosine_similarity':(matrix@matrix.T).tolist(),'purpose':'exploratory_not_quality_score'})
    stats={'status':'encoded_pending_operator_review','listings':50,'whole_vectors':len(manifest['whole_index']),'component_vectors':sum(p['component_vectors'] for p in summary),'active_component_vectors':len(manifest['component_index']),'dimensions':768,'model':encoder.model,'model_digest':encoder.digest,'paid_api_calls':0,'mysql_sync':'not_executed','qdrant_sync':'not_executed','image_method':'reviewed_visual_tags_and_captions_to_text_embedding','library_index':str(Path(library)/'library_index.json'),'products':summary}
    write(output/'run.json',stats);render(output,bundles,stats)
    return stats


def render(output,bundles,stats):
    """写分页核对页；主页面只加载50张主图，各商品可展开全部来源与特征。"""
    from .reviewed_experiment import render_listing
    esc=lambda x:html.escape(str(x),quote=True)
    cards=[]
    for i,b in enumerate(bundles,1):
        f=output/f'rank{i}/index.html'
        f.write_text('<!doctype html><meta charset="utf-8"><style>body{font:15px system-ui;padding:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:15px}article{border:1px solid #ddd;padding:15px}img,video{width:100%;max-height:300px;object-fit:contain}</style>'+render_listing(i,b).replace(f'rank{i}/listing_features.json','listing_features.json'),encoding='utf-8')
        main=next(p for p in b['parts'] if p['role']=='main_image')
        cards.append('<article><img loading="lazy" src="'+esc(Path(main['asset']['local_path']).as_uri())+'"><h3>历史第'+str(i)+'名 · '+esc(b['identity']['product_id'])+'</h3><p>'+esc(b['overall_features'].get('product_form'))+'</p><p>'+esc(' · '.join(b['overall_features']['keywords']))+'</p><a href="rank'+str(i)+'/index.html">查看整套与各组件</a></article>')
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>50套Listing特征库</title><style>body{font:15px system-ui;background:#f1f5f9;color:#20344b;max-width:1500px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:15px}article{background:white;border-radius:12px;padding:16px}img{width:100%;height:240px;object-fit:contain}p{line-height:1.6}</style><h1>50套Listing · 第二阶段特征与向量</h1><p>50个整体向量 + '+str(stats['component_vectors'])+'个组件向量，768维。视觉由GPT按联系图审阅，文字按来源原文编码；新审阅的图片标签由显式模板展开后交给本地nomic编码。前五名匹配输入后复用原审阅；视频每个8帧，不含音频转录。全部待运营审核。</p><p>整体独立综合编码，保留各图片/文案/视频的单独向量；封面、关联产品和认证标志按用途关闭参考。向量不是质量分，不证明功效。未写入MySQL或Qdrant。</p><a href="run.json">运行摘要</a> · <a href="whole_similarity.json">整体相似度矩阵</a><div class="grid">'+''.join(cards)+'</div>',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['prepare','encode']);p.add_argument('--report',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--reuse',type=Path);p.add_argument('--library',type=Path);p.add_argument('--annotations',type=Path)
    a=p.parse_args()
    if a.mode=='prepare':prepare(a.report,a.output,a.reuse)
    else:encode(a.output,a.library,a.annotations)
