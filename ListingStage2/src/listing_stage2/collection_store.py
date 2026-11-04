"""整体/组件两个Qdrant集合，使用版本外键关联；原媒体只保存地址。

本地模式用于当前单机实验；后续可换服务端实现，同一记录契约不变。
原始记录另存JSONL作审计与迁移，不把全部组件嵌入整体记录。
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import uuid
import math
from .component_policy import resolve
from .listing_bundles import digest

SCHEMA = 'listing-reference-collections-v2'
WHOLE_COLLECTION = 'listing_wholes_v5'
COMPONENT_COLLECTION = 'listing_components_v5'


def point_id(kind, version, part_id=''):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'listing-studio/'+kind+'/'+version+'/'+part_id))


def point_records(whole, bundle, dataset_id):
    """整体一条、每个来源组件一条；独立组件向量复用原版本，父版本重新绑定。"""
    version = whole['listing_version_id']
    identity = whole['identity']
    w = deepcopy(whole)
    embedding = w.pop('embedding')
    vector = embedding.pop('vector')
    w.update(dataset_id=dataset_id, embedding_meta=embedding, **identity)
    # 数据集是发布投影；同一语义版本可以出现在不同发布中，不能覆盖另一发布的成员关系。
    whole_point = {'id': point_id('whole/'+dataset_id,version), 'vector':vector, 'payload':w}
    controls = resolve(bundle)
    components=[]
    for part in bundle['parts']:
        p=deepcopy(part)
        e=p.pop('embedding',None)
        v=e.pop('vector') if e else None
        pid=p['part_id']
        p.update(record_type='component', component_version_id=point_id('component/'+dataset_id,version,pid),
                 listing_version_id=version, parent_listing_version_id=version, dataset_id=dataset_id,
                 identity=deepcopy(identity), embedding_meta=e, controls=controls[pid], **identity)
        p['identity_scope']=part.get('features',{}).get('identity_scope','unknown')
        p['usage_boundary']='expression_reference_not_verified_own_product_facts'
        components.append({'id':p['component_version_id'],'vector':v,'payload':p})
    return whole_point,components


def validate_points(wholes,components):
    """入库前检查外键、向量空间、数量和来源引用；不替代语义审阅。"""
    all_points=wholes+components
    if not wholes or len({p['id'] for p in all_points})!=len(all_points):
        raise ValueError('Missing wholes or duplicate vector point IDs')
    parents={p['payload']['listing_version_id']:p for p in wholes}
    if len(parents)!=len(wholes):raise ValueError('Duplicate whole versions')
    per_parent={v:[] for v in parents}
    dimensions=set();digests=set();whole_recipes=set();datasets=set()
    for point in all_points:
        payload=point['payload'];datasets.add(payload['dataset_id'])
        vector=point['vector'];meta=payload.get('embedding_meta')
        if vector is not None:
            if not meta or len(vector)!=meta['dimensions'] or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in vector):
                raise ValueError('Invalid independent vector')
            if abs(sum(v*v for v in vector)**.5-1)>1e-4:raise ValueError('Unnormalized vector')
            dimensions.add(len(vector));digests.add(meta['model_digest'])
        if payload['record_type']=='whole_listing':
            if 'components' in payload or vector is None:raise ValueError('Whole must be one independent vector without embedded components')
            whole_recipes.add(meta['recipe'])
        else:
            version=payload['parent_listing_version_id']
            if version not in parents or payload['listing_version_id']!=version:raise ValueError('Orphan component or version mismatch')
            if payload['identity']!=parents[version]['payload']['identity']:raise ValueError('Component identity differs from parent')
            per_parent[version].append(payload['part_id'])
    if len(dimensions)!=1 or len(digests)!=1 or len(whole_recipes)!=1 or len(datasets)!=1:
        raise ValueError('Mixed datasets or incompatible vector spaces')
    for version,point in parents.items():
        if set(point['payload']['component_ids'])!=set(per_parent[version]) or len(per_parent[version])!=len(set(per_parent[version])):
            raise ValueError('Whole component inventory is incomplete or duplicated')
        for field in ('selling_points','product_traits','visual_elements','style'):
            for feature in point['payload']['structured_features'][field]:
                if not set(feature['evidence_part_ids'])<=set(per_parent[version]):raise ValueError('Whole feature cites foreign component')
    return {'dimensions':next(iter(dimensions)),'model_digest':next(iter(digests)),
            'whole_recipe':next(iter(whole_recipes)),'dataset_id':next(iter(datasets))}


def write_jsonl(path,values):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as handle:
        for value in values:handle.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+'\n')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset_filter(dataset_id):
    from qdrant_client.models import Filter,FieldCondition,MatchValue
    return Filter(must=[FieldCondition(key='dataset_id',match=MatchValue(value=dataset_id))])


def export_dataset(wholes,components,output,store_path,collections=None):
    """预校验后分别写两个集合，核对成功才生成ready清单；不删除历史集合或数据。"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams,Distance,PointStruct
    output=Path(output);store_path=Path(store_path).resolve()
    names=collections or {'whole':WHOLE_COLLECTION,'component':COMPONENT_COLLECTION}
    if set(names)!={'whole','component'} or len(set(names.values()))!=2 or any(not isinstance(n,str) or not n for n in names.values()):
        raise ValueError('Need distinct whole/component collection names')
    if output.exists():raise ValueError('Use a new collection-export directory')
    meta=validate_points(wholes,components)
    output.mkdir(parents=True)
    paths={'whole':'collections/whole_records.jsonl','component':'collections/component_records.jsonl'}
    hashes={kind:write_jsonl(output/paths[kind],items) for kind,items in [('whole',wholes),('component',components)]}
    client=QdrantClient(path=str(store_path))
    try:
        for name,items in [(names['whole'],wholes),(names['component'],components)]:
            if not client.collection_exists(name):
                client.create_collection(name,vectors_config=VectorParams(size=meta['dimensions'],distance=Distance.COSINE))
            else:
                params=client.get_collection(name).config.params.vectors
                if params.size!=meta['dimensions'] or params.distance!=Distance.COSINE:raise ValueError('Existing collection has incompatible dimensions/distance')
            ready=[p for p in items if p['vector'] is not None]
            for start in range(0,len(ready),64):
                client.upsert(name,points=[PointStruct(**p) for p in ready[start:start+64]],wait=True)
            count=client.count(name,count_filter=dataset_filter(meta['dataset_id']),exact=True).count
            if count!=len(ready):raise ValueError('Stored vector count mismatch')
    finally:
        client.close()
    manifest={'schema':SCHEMA,'status':'ready_pending_operator_review',**meta,
        'storage':{'mode':'qdrant_local','path':str(store_path),'whole_collection':names['whole'],'component_collection':names['component']},
        'records':paths,'record_sha256':hashes,'counts':{'wholes':len(wholes),'components':len(components),
            'whole_vectors':len(wholes),'component_vectors':sum(p['vector'] is not None for p in components),
            'retrievable_components':sum(p['vector'] is not None and p['payload']['controls']['retrieve'] for p in components)},
        'linkage':'component.parent_listing_version_id -> whole.listing_version_id',
        'retrieval_order':['whole_listing','components_within_confirmed_wholes_during_generation_planning'],
        'media_storage':'original_asset_paths_only_no_media_bytes_in_vector_store'}
    target=output/'library_index.json'
    target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def read_dataset(manifest_path):
    """从实际Qdrant两个集合读取。JSONL作校验/补全未编码来源，不冒充数据库。"""
    from qdrant_client import QdrantClient
    path=Path(manifest_path).resolve();manifest=json.loads(path.read_bytes())
    if manifest.get('schema')!=SCHEMA or manifest.get('status')!='ready_pending_operator_review':raise ValueError('Dataset not ready')
    for kind,relative in manifest['records'].items():
        record_path=(path.parent/relative).resolve()
        if not record_path.is_relative_to(path.parent):raise ValueError('Collection record escapes directory')
        if hashlib.sha256(record_path.read_bytes()).hexdigest()!=manifest['record_sha256'][kind]:raise ValueError('Collection audit records changed')
    store=Path(manifest['storage']['path'])
    if not store.is_dir():raise ValueError('Local vector database not found')
    client=QdrantClient(path=str(store));values={}
    try:
        for kind in ('whole','component'):
            name=manifest['storage'][kind+'_collection'];items=[];offset=None
            while True:
                batch,offset=client.scroll(name,scroll_filter=dataset_filter(manifest['dataset_id']),limit=128,offset=offset,with_payload=True,with_vectors=True)
                items.extend({'id':str(p.id),'vector':p.vector,'payload':p.payload} for p in batch)
                if offset is None:break
            expected=manifest['counts'][kind+'_vectors']
            if len(items)!=expected:raise ValueError('Database vectors do not match manifest')
            values[kind]=items
    finally:
        client.close()
    for line in (path.parent/manifest['records']['component']).read_text(encoding='utf-8').splitlines():
        record=json.loads(line)
        if record['vector'] is None:values['component'].append(record)
    validate_points(values['whole'],values['component'])
    return manifest,values['whole'],values['component']


def query_collection(manifest_path,vector,limit=5,listing_version_ids=None):
    """真实向量查询；提供父版本时只查其活动组件，否则只查整体集合。"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter,FieldCondition,MatchAny,MatchValue
    manifest=json.loads(Path(manifest_path).read_bytes())
    if manifest.get('schema')!=SCHEMA:raise ValueError('Unknown collection manifest')
    if len(vector)!=manifest['dimensions'] or not all(math.isfinite(x) for x in vector):raise ValueError('Query dimensions mismatch')
    filters=dataset_filter(manifest['dataset_id']).must
    component_mode=listing_version_ids is not None
    if component_mode:
        if not listing_version_ids:return []
        filters.extend([FieldCondition(key='parent_listing_version_id',match=MatchAny(any=listing_version_ids)),
                        FieldCondition(key='controls.enabled',match=MatchValue(value=True)),
                        FieldCondition(key='controls.retrieve',match=MatchValue(value=True)),
                        FieldCondition(key='controls.generation_reference',match=MatchValue(value=True))])
    name=manifest['storage']['component_collection' if component_mode else 'whole_collection']
    client=QdrantClient(path=manifest['storage']['path'])
    try:
        points=client.query_points(name,query=list(vector),query_filter=Filter(must=filters),limit=limit,with_payload=True).points
        return [{'id':str(p.id),'score':p.score,'payload':p.payload} for p in points]
    finally:client.close()
