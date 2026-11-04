"""完整证据文档：不截断原文，来源去重、分块编码，并生成一个独立整体向量。

不按关键词判断卖点，不调用LLM。文字保存为原始来源声明，语义归纳仍待模型/人工。
分块是同一整体文档的长度处理，不是平均既有图片、五点等组件向量。
"""
from copy import deepcopy
import hashlib
import numpy as np
from .listing_bundles import digest
from .local_encoder import normalized
from .component_policy import resolve

RECIPE='whole-listing-full-evidence-v4'
DERIVED_FROM='explicit_full_listing_document_chunks'


def split_document(text, max_chars=2000):
    """完整切分，不丢空白或尾部；优先在换行处切开，返回字符偏移。

    max_chars是每次编码的保守字符预算，不是丢弃阈值，也不冒充模型token上限。
    实际编码请求继续truncate=False；如服务拒绝输入则报错，不悄悄删除后半段。
    """
    if type(max_chars) is not int or max_chars<128:raise ValueError('max_chars must be at least 128')
    if not isinstance(text,str) or not text:raise ValueError('Empty whole document')
    chunks=[];start=0
    while start<len(text):
        end=min(start+max_chars,len(text))
        if end<len(text):
            boundary=text.rfind('\n',start+max_chars//2,end)
            if boundary>=0:end=boundary+1
        content=text[start:end]
        chunks.append({'start':start,'end':end,'text':content,'sha256':hashlib.sha256(content.encode('utf-8')).hexdigest()})
        start=end
    if ''.join(c['text'] for c in chunks)!=text:raise ValueError('Whole document coverage gap')
    return chunks


def collect_document(bundle):
    """收集每个允许参与整体的完整原文/已有视觉描述，去重只合并完全相同的内容。

    重复内容保留全部组件ID与来源。关闭include_in_overall的材料显式列入排除清单。
    关联/品牌图片不因有文字描述而恢复为当前商品证据；图片缺少审阅时直接报错。
    """
    controls=resolve(bundle);sections=[];seen={};excluded=[];text_ids=[];visual_ids=[]
    for p in bundle['parts']:
        pid=p['part_id'];f=p.get('features',{})
        if not controls[pid]['include_in_overall']:
            excluded.append({'part_id':pid,'reason':'include_in_overall_disabled'});continue
        if p.get('asset') and f.get('identity_scope') not in {'current_or_family'}:
            # 旧视频可能没有identity_scope，但已有eligible_for_aggregate及人工抽帧描述。
            if not (p['role']=='video' and p.get('eligible_for_aggregate') and f.get('semantic_description_en')):
                excluded.append({'part_id':pid,'reason':'not_current_or_family'});continue
        raw=p.get('source_text')
        is_text=isinstance(raw,str) and bool(raw.strip())
        text=raw if is_text else f.get('semantic_description_en')
        if not isinstance(text,str) or not text.strip():raise ValueError('Missing reviewed whole evidence: '+pid)
        kind='source_text' if is_text else 'reviewed_visual_description'
        (text_ids if is_text else visual_ids).append(pid)
        evidence={'part_id':pid,'role':p['role'],'reference':deepcopy(p.get('reference')),
                  'asset_sha256':(p.get('asset') or {}).get('asset_sha256')}
        key=(kind,text)
        if key in seen:sections[seen[key]]['evidence'].append(evidence);continue
        seen[key]=len(sections)
        sections.append({'section_id':digest([kind,text]),'kind':kind,'text':text,
                         'text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'evidence':[evidence],
                         'interpretation':'source_claim_not_verified' if is_text else 'reused_visual_review_not_new_image_analysis'})
    if not sections:raise ValueError('No whole evidence after policy filtering')
    f=bundle['overall_features']
    header='Complete competitor Listing expression reference; source statements are not independently verified.\n'
    header+='Product structure: '+str(f.get('product_form','unknown'))+'\n'
    header+='Visual style: '+', '.join(f.get('style',[]))+'\nScenes: '+', '.join(f.get('scenes',[]))+'\n'
    document=header
    for section in sections:
        label='\n['+section['kind']+' | '+','.join(sorted({x['role'] for x in section['evidence']}))+']\n'
        document+=label;section['document_start']=len(document);document+=section['text'];section['document_end']=len(document)
    coverage={'source_text_part_ids':text_ids,'visual_description_part_ids':visual_ids,'excluded_parts':excluded,
              'included_parts':len(text_ids)+len(visual_ids),'unique_sections':len(sections),
              'deduplication':'exact_content_only_all_source_bindings_retained',
              'raw_text_characters':sum(len(p['source_text']) for p in bundle['parts'] if p['part_id'] in text_ids),
              'source_text_truncated':False,'semantic_claim_extraction':'pending_llm_or_human',
              'scope':'all_available_policy_eligible_evidence_not_uncaptured_page_content'}
    return document,sections,coverage


def upgrade(bundle,encoder,max_chars=2000):
    """生成新版本，复用组件向量，独立编码完整整体文档；不改原快照和旧版本。

    文档长于单次输入预算时，对连续文档块编码，按实际字符长度加权池化并归一化。
    所有块均参与；这保证输入完整，不保证每个卖点能在一个向量里被独立准确召回。
    """
    document,sections,coverage=collect_document(bundle)
    chunks=split_document(document,max_chars);vectors=[];chunk_records=[]
    for index,chunk in enumerate(chunks):
        vector=normalized(encoder.encode(chunk['text']))
        vectors.append(vector)
        chunk_records.append({**{k:v for k,v in chunk.items() if k!='text'},'chunk_id':f'whole-chunk-{index+1}',
                              'weight':len(chunk['text']),
                              'section_ids':[x['section_id'] for x in sections if x['document_start']<chunk['end'] and x['document_end']>chunk['start']]})
    if len({len(v) for v in vectors})!=1:raise ValueError('Mixed whole chunk dimensions')
    vector=normalized(sum(v*c['weight'] for v,c in zip(vectors,chunk_records)))
    if sum(c['weight'] for c in chunk_records)!=len(document):raise ValueError('Not all document characters encoded')
    result=deepcopy(bundle);old_version=bundle['bundle_id']
    result.update(schema_version=4,recipe=RECIPE)
    f=result['overall_features'];f['previous_reviewed_summary_en']=f.get('embedding_text_en');f['embedding_text_en']=document
    # 原文声明独立保存，不把按词提取的标签冒充LLM归纳结果。
    f['source_statements']=[{'text':x['text'],'basis':'source_claim_not_verified','semantic_review_status':'pending',
                             'evidence_part_ids':[e['part_id'] for e in x['evidence']], 'section_id':x['section_id']}
                            for x in sections if x['kind']=='source_text']
    f['limitations']=list(f.get('limitations',[]))+['完整原文参与整体文档编码；声明未经过新LLM语义归纳或真实性核验。']
    result['whole_document']={'recipe':RECIPE,'sections':sections,'coverage':coverage,'max_chunk_chars':max_chars,'chunks':chunk_records}
    result['bundle_id']=digest([old_version,RECIPE,hashlib.sha256(document.encode('utf-8')).hexdigest(),max_chars,encoder.digest])
    result['review_provenance']={'producer':'full_source_reencoding_with_reused_visual_review','previous_bundle_id':old_version,
                                'previous_review':deepcopy(bundle.get('review_provenance',{})),
                                'llm_semantic_review_executed':False,'paid_api_calls':0}
    result['embedding']={'model':encoder.model,'model_digest':encoder.digest,'recipe':RECIPE,
        'space_id':digest([encoder.digest,RECIPE]),'dimensions':len(vector),'input_text':document,
        'input_sha256':hashlib.sha256(document.encode('utf-8')).hexdigest(),'vector':vector.tolist(),
        'derived_from':DERIVED_FROM,'pooling':'document_chunk_character_weighted_mean_then_l2_normalize',
        'chunks':chunk_records,'encoded_characters':len(document)}
    return result
