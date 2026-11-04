# 文件用途：将已分析v3装配为参考库：独立整体索引/组件索引、配置投影版本、生成方案证据与暂停检查。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Versioned reference-library export over reviewed v3 Listing bundles.

No model calls or database writes. Whole and component indexes remain distinct.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path

from .listing_bundles import digest
from .storage import write
from .component_policy import resolve, validate_policy

SCHEMA = 'listing-reference-library-v1.1'


# 功能及输出：输入向量记录及可选配方；校验维度、数值、范数和模型标识，返回包含独立检索空间ID的副本。
# 参数：value（待校验/序列化对象）；default_recipe（缺少时使用的配方）。
def checked_embedding(value, default_recipe=None):
    e = deepcopy(value)
    vector = e.get('vector', [])
    if not vector or len(vector) != e.get('dimensions'):
        raise ValueError('Embedding dimension mismatch')
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
        raise ValueError('Non-finite or nonnumeric embedding')
    if abs(sum(x*x for x in vector) ** .5 - 1) > 1e-4:
        raise ValueError('Embedding must be normalized')
    if not e.get('model_digest') or not e.get('model'):
        raise ValueError('Embedding model identity required')
    e['recipe'] = e.get('recipe') or default_recipe
    if not e['recipe']:
        raise ValueError('Embedding recipe required')
    # Explicit, disjoint spaces for whole/part search; adapters must not compare
    # vectors only because their dimensions match.
    e['index_space_id'] = digest([e['model_digest'], e['recipe'], e['dimensions']])
    return e


# 功能及输出：输入生成方案及所属Listing；校验证据/版本、试验项和validated条件，返回副本；不验证试验记录真实性。
# 参数：recipe（生成方案记录）；bundle（一个Listing快照及组件）。
def validate_recipe(recipe, bundle):
    """Validate source binding and evidence without promoting test results."""
    if recipe.get('listing_version_id') != bundle['bundle_id']:
        raise ValueError('Recipe belongs to another Listing version')
    parts = {p['part_id']: p for p in bundle['parts']}
    ids = recipe.get('reference_part_ids', [])
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= parts.keys():
        raise ValueError('Recipe has missing, duplicate or foreign parts')
    for key in ('recipe_id', 'version', 'goal', 'template', 'variables',
                'reference_roles', 'product_constraints', 'acceptance_checks',
                'applicability', 'status', 'validation_trials'):
        if key not in recipe:
            raise ValueError('Missing recipe field: ' + key)
    if not recipe['template'].strip() or not recipe['acceptance_checks']:
        raise ValueError('Recipe needs instructions and acceptance checks')
    roles = recipe['reference_roles']
    if set(roles) != set(ids) or any(v != 'expression_reference' for v in roles.values()):
        raise ValueError('Competitor references may define expression only')
    if recipe['status'] not in ('draft', 'experimental', 'validated', 'retired'):
        raise ValueError('Unknown recipe status')
    for trial in recipe['validation_trials']:
        for key in ('trial_id', 'prompt_sha256', 'reference_sha256', 'model',
                    'output_sha256', 'check_results', 'reviewer'):
            if key not in trial:
                raise ValueError('Incomplete validation trial: ' + key)
        if set(trial['check_results']) != set(recipe['acceptance_checks']):
            raise ValueError('Trial must report every acceptance check')
        if any(v not in ('pass', 'fail', 'unverified') for v in trial['check_results'].values()):
            raise ValueError('Invalid check result')
    if recipe['status'] == 'validated':
        trials = recipe['validation_trials']
        if len({t['trial_id'] for t in trials}) < 3:
            raise ValueError('Validated recipe needs at least three distinct trials')
        if any(v != 'pass' for t in trials for v in t['check_results'].values()):
            raise ValueError('Failed or unverified checks cannot be called validated')
        signatures = {digest([t['prompt_sha256'], t['reference_sha256'], t['model']]) for t in trials}
        if len(signatures) != 1 or not recipe.get('validation_scope'):
            raise ValueError('Validated scope requires identical test conditions')
        if not recipe.get('review_record', {}).get('approved_version') == recipe['version']:
            raise ValueError('Validation review must bind the recipe version')
    return deepcopy(recipe)


# 功能及输出：输入v3包、方案和策略；返回完整来源记录及活动视图，标记整体失效和模板暂停，不执行模型或数据库操作。
# 参数：bundle（一个Listing快照及组件）；recipes（生成方案集合）；policy（可选组件策略）。
def compile_listing(bundle, recipes=(), policy=None):
    validate_policy(policy, [bundle])
    valid_derivation={3:'explicit_reviewed_whole_listing_narrative',4:'explicit_full_listing_document_chunks'}
    if bundle.get('schema_version') not in valid_derivation or bundle.get('embedding',{}).get('derived_from')!=valid_derivation[bundle['schema_version']]:
        raise ValueError('Use reviewed whole narrative or full-evidence document, not component averages')
    identity = bundle['identity']
    for key in ('country_code', 'site_id', 'category_id', 'product_id', 'snapshot_id'):
        value = identity.get(key)
        if not isinstance(value, str) or not value or any(c in value for c in ('/', '\\', ':')) or value in ('.', '..'):
            raise ValueError('Unsafe or missing classification field: ' + key)
    if len({p['part_id'] for p in bundle['parts']}) != len(bundle['parts']):
        raise ValueError('Duplicate component ID')
    part_ids = {p['part_id'] for p in bundle['parts']}
    for point in bundle['overall_features'].get('selling_points', []):
        evidence = point.get('evidence_part_ids', [])
        if not evidence or not set(evidence) <= part_ids:
            raise ValueError('Broken selling-point evidence')
    whole = checked_embedding(bundle['embedding'])
    controls = resolve(bundle, policy)
    baseline = {p['part_id'] for p in bundle['parts'] if p.get('eligible_for_aggregate', True)}
    selected = {pid for pid, control in controls.items() if control['include_in_overall']}
    # 整体依据改变使旧向量失效；只改检索/生成开关不影响整体依据。
    overall_changed = selected != baseline
    components = []
    for p in bundle['parts']:
        component = deepcopy(p)
        component['listing_version_id'] = bundle['bundle_id']
        component['identity_scope'] = p.get('features', {}).get('identity_scope', 'unknown')
        component['usage_boundary'] = 'expression_reference_only_not_own_product_facts'
        component['retrieval_status'] = 'pending_review'
        component['controls'] = controls[p['part_id']]
        if not component['controls']['embed']:
            component.pop('embedding', None)
            component['embedding_status'] = 'disabled_source_preserved'
        elif p.get('embedding'):
            component['embedding'] = checked_embedding(p['embedding'])
        if not component['controls']['retrieve']:
            component['retrieval_status'] = 'disabled'
        components.append(component)
    checked = [validate_recipe(r, bundle) for r in recipes]
    if len({(r['recipe_id'], r['version']) for r in checked}) != len(checked):
        raise ValueError('Duplicate recipe version')
    for recipe in checked:
        blocked = [pid for pid in recipe['reference_part_ids'] if not controls[pid]['generation_reference']]
        # 可用性与生命周期分开：禁用引用会暂停模板，不篡改原验证状态。
        recipe['availability'] = 'blocked_reference_disabled' if blocked else 'pending_review'
        recipe['blocked_part_ids'] = blocked
    return {'schema': SCHEMA, 'listing_version_id': bundle['bundle_id'],
            'projection_version_id': digest([digest(bundle), controls, checked]),
            'component_policy': controls,
            'overall_status': 'requires_review_and_reencode' if overall_changed else 'source_review_unchanged',
            'overall_basis': {'source_part_ids':sorted(baseline),'selected_part_ids':sorted(selected)},
            'source_bundle_sha256': digest(bundle), 'identity': deepcopy(identity),
            'overall_features': deepcopy(bundle['overall_features']),
            'overall_embedding': whole, 'components': components,
            'generation_recipes': checked, 'coverage': deepcopy(bundle.get('coverage', {})),
            'approval_status': bundle.get('approval_status', 'pending_operator_review'),
            'quality_score': bundle.get('quality_score'),
            'usage_boundary': 'reference_library_not_verified_own_product_facts'}


# 功能及输出：输入一批v3包、输出目录、方案和策略；先校验数据，再写分类记录和双索引，返回索引清单；整体待重审时暂停索引。
# 参数：bundles（当前批次Listing集合）；output（输出目录）；recipes（生成方案集合）；policy（可选组件策略）。
def export_library(bundles, output, recipes=(), policy=None):
    bundles = list(bundles)
    validate_policy(policy, bundles)
    versions = [b['bundle_id'] for b in bundles]
    if len(versions) != len(set(versions)):
        raise ValueError('Duplicate Listing version')
    if any(r.get('listing_version_id') not in versions for r in recipes):
        raise ValueError('Orphan recipe')
    # Validate the entire batch before creating any output records.
    records = [compile_listing(b, [r for r in recipes if r['listing_version_id'] == b['bundle_id']],
               {**policy,'listings':{b['bundle_id']:policy.get('listings',{}).get(b['bundle_id'],{})}} if policy is not None else None) for b in bundles]
    whole_index, component_index, paths = [], [], []
    for record in records:
        i = record['identity']
        # Short directory hashes avoid Windows MAX_PATH; full IDs remain in JSON.
        relative = Path('catalog', *(i[k] for k in ('country_code','site_id','category_id','product_id','snapshot_id')), digest(record['listing_version_id'])[:20],record['projection_version_id'][:20], 'reference_listing.json')
        target = Path(output)/relative
        if target.exists():
            old = json.loads(target.read_text(encoding='utf-8'))
            if old['projection_version_id'] != record['projection_version_id']:
                raise ValueError('Projection path hash collision')
        write(Path(output)/relative, record)
        path = relative.as_posix(); paths.append(path)
        metadata = {'listing_version_id': record['listing_version_id'], **i,
                    'projection_version_id':record['projection_version_id'],
                    'approval_status': record['approval_status'], 'usage_boundary':record['usage_boundary']}
        # 失效向量可保留作审计，但不能进入活动索引。
        if record['overall_status'] == 'source_review_unchanged':
            whole_index.append({'id':record['projection_version_id'], 'record_path':path,
                                'embedding':record['overall_embedding'], 'metadata':metadata})
        for p in record['components']:
            if not p.get('embedding') or not p['controls']['retrieve'] or record['overall_status'] != 'source_review_unchanged': continue
            component_index.append({'id':digest([record['projection_version_id'],p['part_id']]),
                'record_path':path, 'part_id':p['part_id'], 'embedding':p['embedding'],
                'metadata':{**metadata,'role':p['role'],'identity_scope':p['identity_scope'],
                            'eligible_for_aggregate':p.get('eligible_for_aggregate',False)}})
    manifest={'schema':SCHEMA,'retrieval_order':['whole_listing','components_within_selected_listings'],
              'records':paths,'whole_index':whole_index,'component_index':component_index,
              'policy_report':[{'listing_version_id':r['listing_version_id'],'projection_version_id':r['projection_version_id'],
                               'overall_status':r['overall_status'],'source_components':len(r['components']),
                               'active_embeddings':sum(bool(p.get('embedding')) for p in r['components']),
                               'blocked_recipes':sum(bool(x['blocked_part_ids']) for x in r['generation_recipes'])} for r in records],
              'status':'preview_pending_review','database_sync':'not_executed'}
    write(Path(output)/'library_index.json',manifest)
    return manifest


# 功能及输出：CLI支持重复--bundle及可选--recipes/--policy；只导出本地JSON，不同步Qdrant或数据库。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,action='append',required=True)
    parser.add_argument('--recipes',type=Path)
    parser.add_argument('--policy',type=Path,help='Component type rules and version-scoped overrides')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    result=export_library([read(p) for p in args.bundle],args.output,read(args.recipes) if args.recipes else [],read(args.policy) if args.policy else None)
    print(json.dumps({'listings':len(result['whole_index']),'components':len(result['component_index']),
                      'output':str(args.output),'database_sync':result['database_sync']},ensure_ascii=False))


if __name__=='__main__':main()
