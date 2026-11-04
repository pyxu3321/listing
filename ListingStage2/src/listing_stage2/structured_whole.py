"""经语义审阅的整体特征：独立编码一次，不拼入原文或平均组件向量。"""
from copy import deepcopy
import hashlib
from .listing_bundles import digest
from .component_policy import resolve
from .local_encoder import normalized

RECIPE = 'reviewed-structured-whole-v5'
FIELDS = ('selling_points', 'product_traits', 'visual_elements', 'style')
SCHEMA = 'listing-structured-review-v1'


def source_fingerprint(bundle):
    """绑定完整输入，包含原文、既有视觉审阅、组件向量和启用策略。"""
    return digest(bundle)


def validate_review(review, bundle):
    """只验证格式、快照与证据归属；语义和限定条件由审阅者负责，不按关键词判别。"""
    if review.get('schema') != SCHEMA:
        raise ValueError('Expected structured whole review')
    if review.get('source_bundle_id') != bundle['bundle_id'] or review.get('source_fingerprint') != source_fingerprint(bundle):
        raise ValueError('Structured review is stale or belongs to another source version')
    parts = {p['part_id']: p for p in bundle['parts']}
    controls = resolve(bundle)
    eligible = {pid for pid, value in controls.items() if value['include_in_overall']}
    expected_text = {p['part_id'] for p in bundle['parts'] if p.get('source_text') and p['part_id'] in eligible}
    if set(review.get('reviewed_source_text_part_ids', [])) != expected_text:
        raise ValueError('Review must account for every eligible complete source-text component')
    features = review.get('features')
    if not isinstance(features, dict):
        raise ValueError('Missing structured features')
    summary = features.get('summary_en')
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('Missing independently synthesized summary')
    for field in FIELDS:
        values = features.get(field)
        if not isinstance(values, list):
            raise ValueError('Invalid structured field: ' + field)
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('text_en'), str) or not item['text_en'].strip():
                raise ValueError('Feature requires normalized text_en')
            if item.get('basis') not in {'source_claim', 'reviewed_visual_observation'}:
                raise ValueError('Feature requires an explicit evidence basis')
            if item.get('subject') not in {'source_product_or_qualified_variant', 'captured_product_appearance'}:
                raise ValueError('Unsupported positive-feature subject; accessories belong in limitations')
            refs = item.get('evidence_part_ids')
            if not isinstance(refs, list) or not refs or len(set(refs)) != len(refs) or not set(refs) <= eligible:
                raise ValueError('Feature evidence is missing, excluded or foreign')
            if not isinstance(item.get('conditions'), list) or not all(isinstance(x, str) and x.strip() for x in item['conditions']):
                raise ValueError('conditions must be explicit strings, or an empty list')
            if item['basis'] == 'source_claim' and not any(parts[pid].get('source_text') for pid in refs):
                raise ValueError('Source claim must reference captured text')
            if item['basis'] == 'reviewed_visual_observation' and not any(parts[pid].get('asset') for pid in refs):
                raise ValueError('Visual feature must cite reviewed media')
    if not features['selling_points'] or not features['product_traits'] or not features['visual_elements']:
        raise ValueError('Need whole selling points, product traits and visual expression')
    for key in ('limitations', 'expression_sequence'):
        if not isinstance(features.get(key), list) or not all(isinstance(x, str) for x in features[key]):
            raise ValueError('Invalid ' + key)
    return review


def embedding_text(features):
    """按结构组织审阅后的含义；条件紧随对应特征，原始材料留在组件与证据中。"""
    # 展示摘要可能讨论未成立的卖点/配件，不把这些背景解释带入正向检索向量。
    # 归纳摘要、排除项和信息顺序仍完整保存在数据库元数据中供LLM复核。
    lines = []
    for key in FIELDS:
        lines.append('\n' + key.replace('_', ' ').title() + ':')
        for item in features[key]:
            text = item['text_en']
            if item['conditions']:
                text += ' Conditions: ' + ' '.join(item['conditions'])
            lines.append('- ' + text)
    text = '\n'.join(lines)
    if len(text) > 6000:
        raise ValueError('Structured retrieval description too long; revise the semantic synthesis, never truncate')
    return text


def build_whole(bundle, review, encoder):
    """返回独立整体记录；没有components字段，不读取或汇聚任何组件向量数值。"""
    validate_review(review, bundle)
    features = deepcopy(review['features'])
    text = embedding_text(features)
    vector = normalized(encoder.encode(text)).tolist()
    version = digest([SCHEMA, source_fingerprint(bundle), review, encoder.digest, RECIPE, hashlib.sha256(text.encode()).hexdigest()])
    compatible = {
        'keywords': [x.get('label_zh') or x['text_en'] for x in features['selling_points']],
        'selling_points': [{'text': x.get('label_zh') or x['text_en'], 'text_en': x['text_en'],
                            'conditions': x['conditions'], 'basis': x['basis'], 'subject': x['subject'],
                            'evidence_part_ids': x['evidence_part_ids']} for x in features['selling_points']],
        'product_traits': features['product_traits'], 'visual_elements': features['visual_elements'],
        'style': [x['text_en'] for x in features['style']], 'scenes': [], 'audience': [],
        'information_order': features['expression_sequence'], 'limitations': features['limitations'],
        'embedding_text_en': text, 'product_form': bundle['overall_features'].get('product_form'),
        'historical_rank': bundle['overall_features'].get('historical_rank'),
    }
    return {
        'record_type': 'whole_listing', 'listing_version_id': version, 'identity': deepcopy(bundle['identity']),
        'source_bundle_id': bundle['bundle_id'], 'structured_features': features,
        'overall_features': compatible,
        'embedding': {'model': encoder.model, 'model_digest': encoder.digest, 'recipe': RECIPE,
            'dimensions': len(vector), 'input_text': text, 'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'vector': vector, 'derived_from': 'independent_reviewed_structured_features_single_encode'},
        'component_ids': [p['part_id'] for p in bundle['parts']],
        'review_provenance': {k: deepcopy(v) for k, v in review.items() if k != 'features'},
        'coverage': deepcopy(bundle.get('coverage', {})), 'approval_status': 'pending_operator_review',
        'quality_score': None, 'usage_boundary': 'expression_reference_not_verified_own_product_facts',
    }
