# 文件用途：历史审阅接口；默认只编码综合摘要。新双集合流程使用structured_whole.py与structured_batch.py。
# 核对说明：全文汇聚v4仅在full_evidence=True时显式执行，不再作为默认整体表示。
"""Full-evidence whole Listing encoded independently from existing component vectors."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .listing_bundles import digest

RECIPE = 'reviewed-whole-listing-summary-v3'


# 功能及输出：输入素材bundle；返回身份与全部组件的摘要，供审阅版本绑定。
# 参数：bundle（一个Listing快照及组件）。
def input_fingerprint(bundle):
    return digest({'identity':bundle['identity'],'parts':bundle['parts']})


# 功能及输出：输入bundle、下载记录路径和视频审阅；验证商品/快照及文件哈希，返回加入视频组件的新副本。
# 参数：bundle（一个Listing快照及组件）；record_path（视频下载记录路径）；review（绑定输入指纹的整体审阅）。
def attach_video(bundle, record_path, review):
    record = json.loads(Path(record_path).read_text(encoding='utf-8'))
    if record['snapshot_id'] != bundle['identity']['snapshot_id'] or record['identity']['product_id'] != bundle['identity']['product_id']:
        raise ValueError('Video belongs to another product or snapshot')
    path = Path(record['export_path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Video bytes changed')
    part_id=digest(['video',record['sha256'],bundle['identity']])
    part={'part_id':part_id,'role':'video','entity_kind':'video','source_text':None,'features':review,'reference':{'snapshot_id':record['snapshot_id'],'source_url':record['source_url'],'asset_sha256':record['sha256']},'asset':{'local_path':str(path),'asset_sha256':record['sha256']},'is_main_image':False,'eligible_for_aggregate':True,'module_placements':[]}
    bundle=deepcopy(bundle)
    bundle['parts'].append(part)
    bundle['coverage']['video_status']='sampled_frames_reviewed_audio_not_transcribed'
    bundle['coverage']['video_download_record']=str(record_path)
    return bundle


# 功能及输出：历史接口，默认返回v3综合摘要；full_evidence=True时显式复现v4。当前v5走structured_batch。
# 参数：bundle（一个Listing快照及组件）；review（绑定输入指纹的整体审阅）；encoder（带模型摘要的编码器）；component_ids（允许编码的组件ID集合，None为全部）。
def build(bundle, review, encoder, component_ids=None, full_evidence=False):
    if review['input_fingerprint'] != input_fingerprint(bundle):
        raise ValueError('Whole review is stale; source components changed')
    ids={p['part_id'] for p in bundle['parts']}
    overall=review['overall_features']
    for claim in overall['selling_points']:
        if not claim.get('evidence_part_ids') or not set(claim['evidence_part_ids']) <= ids:
            raise ValueError('Selling point has missing or foreign evidence')
    # v3仅编码人工综合摘要；v4随后收集全部允许参与的原文与视觉证据。
    text=overall['embedding_text_en']
    if not text or len(text)>6000:
        raise ValueError('Whole summary must be nonempty and fit the explicit input budget')
    # 历史v3直接编码审阅摘要；仅显式选择v4才在末尾调用全文汇聚实验。
    vector=encoder.encode(text).tolist() if not full_evidence else []
    result=deepcopy(bundle)
    result.update(schema_version=3,recipe=RECIPE,overall_features=overall,review_provenance={k:v for k,v in review.items() if k!='overall_features'},approval_status='pending_operator_review',quality_score=None)
    result.pop('weights',None)
    result.pop('aggregate_documents',None)
    result['bundle_id']=digest([bundle['identity'],review,encoder.digest,RECIPE])
    result['embedding']={'model':encoder.model,'model_digest':encoder.digest,'recipe':RECIPE,'space_id':digest([encoder.digest,RECIPE]),'dimensions':len(vector),'input_text':text,'input_sha256':hashlib.sha256(text.encode()).hexdigest(),'vector':vector,'derived_from':'explicit_reviewed_whole_listing_narrative'}
    for part in result['parts']:
        if component_ids is not None and part['part_id'] not in component_ids:
            part.pop('embedding',None)
            part['embedding_status']='disabled_by_analysis_policy'
            continue
        f=part['features']
        text=f.get('semantic_description_en') or part.get('source_text')
        if not text:
            part['embedding_status']='missing_semantic_text'
            continue
        if len(text)>6000:
            raise ValueError('Part must be split explicitly before encoding')
        v=encoder.encode(part['role']+': '+text).tolist()
        part['embedding']={'model':encoder.model,'model_digest':encoder.digest,'recipe':'component-semantic-text-v1','dimensions':len(v),'input_sha256':digest(part['role']+': '+text),'vector':v}
        part['embedding_status']='ready'
    if full_evidence:
        from .whole_document import upgrade
        return upgrade(result,encoder)
    return result
