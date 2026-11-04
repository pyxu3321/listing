# 文件用途：旧payload完整性校验：来源哈希、重复ID、素材引用、向量维度/归一化/模型摘要。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import hashlib, json
from pathlib import Path
import numpy as np

# 功能及输出：输入bytes，返回SHA256十六进制摘要。
# 参数：value（待校验/序列化对象）。
def sha(value):
    return hashlib.sha256(value).hexdigest()

# 功能及输出：输入旧payload；读取本地来源/审阅/图片进行哈希校验并检查ID和向量，成功返回原payload。
# 参数：payload（旧实验结构化数据）。
def validate(payload):
    for field in ('snapshots','assets','references','features','embeddings'):
        if not payload.get(field): raise ValueError('Missing '+field)
    provenance=payload['provenance']
    if sha(Path(provenance['source_report']).read_bytes()) != payload['source_report_sha256']:
        raise ValueError('Source report changed')
    if sha(Path(provenance['review_file']).read_bytes()) != payload['review_sha256']:
        raise ValueError('Review changed: rebuild embeddings before continuing')
    for rows,key in ((payload['snapshots'],'snapshot_key'),(payload['assets'],'asset_sha256'),(payload['references'],'reference_id'),(payload['features'],'feature_id'),(payload['embeddings'],'feature_id')):
        ids=[x[key] for x in rows]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate '+key)
    assets={a['asset_sha256']:a for a in payload['assets']}
    snaps={x['snapshot_key'] for x in payload['snapshots']}
    refs={x['reference_id']:x for x in payload['references']}
    features={x['feature_id']:x for x in payload['features']}
    for a in assets.values():
        if sha(Path(a['local_path']).read_bytes())!=a['asset_sha256']: raise ValueError('Asset changed')
    for ref in refs.values():
        if ref['snapshot_key'] not in snaps or ref['asset_sha256'] not in assets: raise ValueError('Broken reference')
    for f in features.values():
        if f['snapshot_key'] not in snaps: raise ValueError('Broken snapshot')
        if f['image_reference_id'] and f['image_reference_id'] not in refs: raise ValueError('Broken image evidence')
    if {e['feature_id'] for e in payload['embeddings']}!=set(features): raise ValueError('Incomplete vectors')
    for e in payload['embeddings']:
        v=np.array(e['vector'])
        if len(v)!=e['dimensions'] or not np.isfinite(v).all() or abs(np.linalg.norm(v)-1)>1e-4: raise ValueError('Invalid vector')
        if sha(e['input_text'].encode())!=e['input_sha256']: raise ValueError('Stale vector')
        if e['model_digest']!=provenance['embedding_model_digest']: raise ValueError('Mixed embedding spaces')
    return payload
