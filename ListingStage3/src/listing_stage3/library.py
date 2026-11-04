"""读取第二阶段特征库，校验版本、路径、向量与组件归属。"""
import hashlib
import json
import math
import sys
from copy import deepcopy
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate_vector(e):
    """检查维度、有限值和归一化，拒绝混入损坏向量。"""
    v=e.get('vector',[])
    if not v or type(e.get('dimensions')) is not int or len(v)!=e['dimensions']:raise ValueError('Bad vector dimensions')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in v):raise ValueError('Invalid vector values')
    if abs(math.sqrt(sum(x*x for x in v))-1)>1e-4:raise ValueError('Vector must be normalized')
    if not e.get('model_digest') or not e.get('recipe'):raise ValueError('Missing embedding identity')


def load_collections(path,stage2_project=None):
    """读取实际双集合数据库，在内存中按父版本关联，兼容现有整体匹配流程。"""
    project=Path(stage2_project) if stage2_project else Path(__file__).resolve().parents[3]/'ListingStage2'
    source=project/'src'
    if not source.is_dir():raise ValueError('Stage-two reader source not found')
    if str(source) not in sys.path:sys.path.insert(0,str(source))
    from listing_stage2.collection_store import read_dataset
    manifest,wholes,components=read_dataset(path)
    children={p['payload']['listing_version_id']:[] for p in wholes}
    for point in components:
        p=deepcopy(point['payload']);meta=p.pop('embedding_meta')
        if meta:p['embedding']={**meta,'vector':point['vector']}
        p['index_enabled']=bool(meta and p['controls']['retrieve'] and p['controls']['enabled'])
        if p.get('embedding'):validate_vector(p['embedding'])
        children[p['parent_listing_version_id']].append(p)
    records=[]
    for point in wholes:
        p=deepcopy(point['payload']);meta=p.pop('embedding_meta')
        p['overall_embedding']={**meta,'vector':point['vector']};validate_vector(p['overall_embedding'])
        order={pid:i for i,pid in enumerate(p['component_ids'])}
        p['components']=sorted(children[p['listing_version_id']],key=lambda child:order[child['part_id']])
        p['overall_status']='source_review_unchanged';p['generation_recipes']=[]
        p['library_source']={'index':str(path),'storage':'qdrant_local','database_path':manifest['storage']['path'],
            'whole_point_id':point['id'],'dataset_id':manifest['dataset_id'],
            'record':str(path.parent/manifest['records']['whole']),'record_sha256':manifest['record_sha256']['whole']}
        records.append(p)
    return records,{'path':str(path),'storage':'qdrant_local','active_whole_entries':len(records),
                   'component_records':len(components),'dataset_id':manifest['dataset_id']}


def load(paths,stage2_project=None):
    """输入library_index.json列表，返回可用整体记录；重复Listing以配置中先出现的视图为准。

    不合并不同投影的开关，避免从旧视图恢复已禁用组件。仅加载活动whole_index。
    """
    listings=[];seen=set();inventory=[]
    for name in paths:
        path=Path(name).resolve();index=read(path)
        if index.get('schema')=='listing-reference-collections-v2':
            records,details=load_collections(path,stage2_project)
            for record in records:
                if record['listing_version_id'] not in seen:
                    listings.append(record);seen.add(record['listing_version_id'])
            inventory.append(details)
            continue
        if index.get('schema') not in {'listing-reference-library-v1','listing-reference-library-v1.1'}:raise ValueError('Unsupported stage-two library schema')
        active_parts={(x['record_path'],x['part_id']) for x in index['component_index']}
        for row in index['whole_index']:
            target=(path.parent/row['record_path']).resolve()
            if not target.is_relative_to(path.parent):raise ValueError('Library record escapes its directory')
            record=read(target);version=record['listing_version_id']
            if row['metadata']['listing_version_id']!=version:raise ValueError('Whole index version mismatch')
            if version in seen:continue
            if record.get('overall_status','source_review_unchanged')!='source_review_unchanged':raise ValueError('Stale whole vector in active index')
            validate_vector(record['overall_embedding'])
            if row['embedding']!=record['overall_embedding']:raise ValueError('Whole index does not match record')
            ids=[p['part_id'] for p in record['components']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate component ID')
            for p in record['components']:
                if p.get('listing_version_id',version)!=version:raise ValueError('Foreign component version')
                p['index_enabled']=(row['record_path'],p['part_id']) in active_parts
                if p.get('embedding'):validate_vector(p['embedding'])
            record['library_source']={'index':str(path),'record':str(target),'record_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            listings.append(record);seen.add(version)
        inventory.append({'path':str(path),'active_whole_entries':len(index['whole_index'])})
    return listings,inventory
