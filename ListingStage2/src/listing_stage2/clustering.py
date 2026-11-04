# 文件用途：历史图片描述文本向量聚类：先按角色/结构/身份分桶，再按固定代表的余弦相似度分组；不是像素模型。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import numpy as np

# 功能及输出：输入旧payload及(0,1]相似度阈值；返回稳定顺序的候选分组及成员分数，待人工校准。
# 参数：payload（旧实验结构化数据）；threshold（余弦分组阈值）。
def group(payload, threshold=0.78):
    if not 0 < threshold <= 1: raise ValueError('Threshold out of range')
    refs={r['reference_id']:r for r in payload['references']}
    vectors={e['feature_id']:np.asarray(e['vector']) for e in payload['embeddings']}
    groups=[]
    for f in sorted(payload['features'],key=lambda x:x['entity_key']):
        if not f['image_reference_id']: continue
        ref=refs[f['image_reference_id']]; note=f['features']
        bucket=(ref['source_role'],note.get('product_form','unknown'),note.get('identity_scope','unknown'))
        v=vectors[f['feature_id']]
        candidates=[(float(v@g['_vector']),g) for g in groups if g['_bucket']==bucket]
        score,g=max(candidates,key=lambda pair:pair[0]) if candidates else (-1,None)
        if g is None or score<threshold:
            g={'cluster_id':f'C{len(groups)+1:03d}','source_role':bucket[0],'product_form':bucket[1],'identity_scope':bucket[2],'representative':f['feature_id'],'members':[],'_bucket':bucket,'_vector':v}
            groups.append(g); score=1.
        g['members'].append({'feature_id':f['feature_id'],'similarity_to_representative':round(score,6)})
    return [dict({k:v for k,v in g.items() if not k.startswith('_')},algorithm='deterministic-leader-cosine-v1',threshold=threshold,vector_kind='feature_text',status='pending_review') for g in groups]
