# 文件用途：组件策略：合并类型与单项配置、限制数量、处理开关依赖；不删除素材或自动重编码。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Resolve component usage without deleting source assets or recomputing vectors."""
from copy import deepcopy

# 四个独立用途；enabled是总开关，max_components仅用于类型规则。
FLAGS = ('include_in_overall', 'embed', 'retrieve', 'generation_reference')
RULE_KEYS = set(FLAGS) | {'enabled'}
ROLES = {'main','main_image','gallery','aplus','aplus_image','title','bullet','description','aplus_text','aplus_dom','video'}


# 功能及输出：输入规则字典及允许字段；检查布尔值、非负数量上限；失败抛ValueError，无返回业务数据。
# 参数：rule（规则字典）；allowed（允许字段集合）。
def _check(rule, allowed):
    if not isinstance(rule, dict) or set(rule) - allowed:
        raise ValueError('Invalid component policy fields')
    for k, v in rule.items():
        if k == 'max_components':
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError('max_components must be null or nonnegative integer')
        elif type(v) is not bool:
            raise ValueError('Component switches must be booleans')


# 功能及输出：输入策略与当前批次Listing；拒绝未知版本、组件和字段；不自动修正错误配置。
# 参数：policy（可选组件策略）；bundles（当前批次Listing集合）。
def validate_policy(policy, bundles):
    if policy is None: return
    if not isinstance(policy, dict) or set(policy) - {'schema_version','defaults','roles','listings'} or policy.get('schema_version') != 1:
        raise ValueError('Unknown component policy schema')
    _check(policy.get('defaults', {}), RULE_KEYS)
    roles = policy.get('roles', {})
    known_roles = ROLES | {p['role'] for b in bundles for p in b['parts']}
    if not isinstance(roles, dict) or set(roles) - known_roles:
        raise ValueError('Unknown component role')
    for rule in roles.values(): _check(rule, RULE_KEYS | {'max_components'})
    by_version = {b['bundle_id']: b for b in bundles}
    overrides = policy.get('listings', {})
    if not isinstance(overrides, dict) or set(overrides) - by_version.keys():
        raise ValueError('Policy references unknown Listing version')
    for version, parts in overrides.items():
        ids = {p['part_id'] for p in by_version[version]['parts']}
        if not isinstance(parts, dict) or set(parts) - ids:
            raise ValueError('Policy references unknown component')
        for rule in parts.values(): _check(rule, RULE_KEYS)


# 功能及输出：输入一个Listing和可选策略；返回part_id到最终开关/原因的映射；先继承源状态，再应用默认、类型、单项及数量上限。
# 参数：bundle（一个Listing快照及组件）；policy（可选组件策略）。
def resolve(bundle, policy=None):
    policy = policy or {}
    overrides = policy.get('listings', {}).get(bundle['bundle_id'], {})
    counts, resolved = {}, {}
    for p in bundle['parts']:
        role = policy.get('roles', {}).get(p['role'], {})
        value = {'enabled': True, 'include_in_overall':p.get('eligible_for_aggregate', True),
                 'embed':True, 'retrieve':True, 'generation_reference':True}
        # 优先级：源分析状态→全局默认→类型规则→具体版本内的单项覆盖。
        value.update({k:v for k,v in p.get('analysis_controls',{}).items() if k in RULE_KEYS})
        value.update(policy.get('defaults', {}))
        value.update({k:v for k,v in role.items() if k != 'max_components'})
        value.update(overrides.get(p['part_id'], {}))
        reasons = []
        count = counts.get(p['role'], 0)
        maximum = role.get('max_components')
        if value['enabled']:
            if maximum is not None and count >= maximum:
                value['enabled'] = False
                reasons.append('role_limit')
            else: counts[p['role']] = count + 1
        # 软禁用保留原图原文；类型数量上限在单项覆盖之后执行。
        if not value['enabled']:
            value.update({k:False for k in FLAGS})
            reasons.append('disabled_preserved_in_source')
        if not value['embed'] and value['retrieve']:
            value['retrieve'] = False
            reasons.append('retrieval_requires_component_embedding')
        resolved[p['part_id']] = {**deepcopy(value), 'reasons':reasons}
    return resolved
