"""新版提取契约：原子属性、逐图颜色角色、精确证据，以及独立整体/组件向量。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .component_policy import resolve
from .listing_bundles import digest
from .local_encoder import normalized
from .structured_whole import source_fingerprint

SCHEMA = 'listing-detailed-review-v2'
RECIPE = 'reviewed-detailed-whole-v6'
PART_RECIPE = 'component-semantic-text-v1'
COLOR_STATUS = {'observed', 'not_visible', 'not_assessed'}


def load_catalog(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[2] / 'config/feature-schema.json'
    catalog = json.loads(path.read_text(encoding='utf-8-sig'))
    if catalog.get('schema') != 'listing-feature-catalog-v1':
        raise ValueError('Unsupported feature catalog')
    if not catalog.get('fields') or not catalog.get('color_roles'):
        raise ValueError('Feature catalog is empty')
    if set(catalog.get('color_objects', {})) != set(catalog['color_roles']):
        raise ValueError('Color roles require explicit object mappings')
    return catalog


def validate_image(image, part, catalog):
    """一张图一份观察；缺角色与未观察不能伪装成已观察颜色。"""
    if image.get('part_id') != part['part_id'] or image.get('asset_sha256') != part['asset']['asset_sha256']:
        raise ValueError('Image review identity/hash mismatch')
    roles = image.get('colors', {})
    if set(roles) != set(catalog['color_roles']):
        raise ValueError('Missing image color roles')
    for role, color in roles.items():
        values = color.get('values_en')
        if color.get('status') not in COLOR_STATUS or not isinstance(values, list) or not all(isinstance(x, str) and x.strip() for x in values):
            raise ValueError('Invalid image color observation')
        if len(values) != len(set(values)) or (color['status'] == 'observed') != bool(values):
            raise ValueError('Observed colors require distinct values; unknown/absent must be empty')
    for key in ('composition_en', 'scene_en'):
        if not isinstance(image.get(key), str) or not image[key].strip():
            raise ValueError('Each image requires its own composition and scene')
    if not isinstance(image.get('expression_methods'), list) or not all(isinstance(x, str) and x.strip() for x in image['expression_methods']):
        raise ValueError('Invalid visual expression methods')
    return image


def eligible_images(bundle):
    """只重审可纳入整体的当前/家族产品原图；视频与推荐商品不能混入。"""
    controls = resolve(bundle)
    return [p for p in bundle['parts'] if p.get('entity_kind') == 'image'
            and p.get('asset') and controls[p['part_id']]['include_in_overall']
            and p.get('features', {}).get('identity_scope') == 'current_or_family']


def validate_review(review, bundle, catalog=None):
    """检查完整性与证据类型；不会把格式正确误当成语义已被自动证明。"""
    catalog = catalog or load_catalog()
    if review.get('schema') != SCHEMA or review.get('source_bundle_id') != bundle['bundle_id']:
        raise ValueError('Wrong detailed review identity')
    if review.get('source_fingerprint') != source_fingerprint(bundle):
        raise ValueError('Stale detailed review')
    if review.get('catalog_sha256') != digest(catalog):
        raise ValueError('Feature catalog changed; review again')
    parts = {p['part_id']: p for p in bundle['parts']}
    allowed = {pid for pid, c in resolve(bundle).items() if c['include_in_overall']}
    texts = {pid for pid in allowed if parts[pid].get('source_text')}
    if set(review.get('reviewed_source_text_part_ids', [])) != texts:
        raise ValueError('Review every complete eligible source text')
    image_parts = {p['part_id']: p for p in eligible_images(bundle)}
    images = review.get('image_reviews')
    if not isinstance(images, list) or len(images) != len(image_parts) or {i.get('part_id') for i in images} != set(image_parts):
        raise ValueError('Every eligible image needs its own review; do not broadcast a whole palette')
    for image in images:
        part = image_parts[image['part_id']]
        validate_image(image,part,catalog)
    image_reviews = {i['part_id']: i for i in images}
    color_fields = {field: role for role, field in catalog['color_roles'].items()}
    attributes = review.get('attributes')
    if not isinstance(attributes, list) or not attributes:
        raise ValueError('Missing atomic attributes')
    ids = []
    for attribute in attributes:
        ids.append(attribute.get('feature_id'))
        if attribute.get('field') not in catalog['fields'] or attribute.get('object') not in catalog['objects']:
            raise ValueError('Unknown attribute field/object')
        if attribute.get('status') not in catalog['allowed_statuses']:
            raise ValueError('Invalid positive/negative/conflicting/unknown status')
        for key in ('value_en', 'text_en', 'label_zh', 'scope'):
            if not isinstance(attribute.get(key), str) or not attribute[key].strip():
                raise ValueError('Missing attribute ' + key)
        if not isinstance(attribute.get('conditions'), list) or not all(isinstance(x, str) and x.strip() for x in attribute['conditions']):
            raise ValueError('Invalid attribute conditions')
        evidence = attribute.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('Attribute has no evidence')
        for entry in evidence:
            pid = entry.get('part_id')
            if pid not in allowed:
                raise ValueError('Foreign or excluded evidence')
            if entry.get('basis') == 'source_text':
                quote = entry.get('quote')
                if not isinstance(quote, str) or not quote or quote not in (parts[pid].get('source_text') or ''):
                    raise ValueError('Text evidence must contain an exact source quote')
            elif entry.get('basis') == 'image_pixels':
                if pid not in image_parts or entry.get('asset_sha256') != image_parts[pid]['asset']['asset_sha256']:
                    raise ValueError('Visual evidence must cite a reviewed image and hash')
                if entry.get('region') not in {'product_surface', 'product_core', 'scene_background', 'layout_background', 'text', 'icons', 'whole_image'}:
                    raise ValueError('Missing visual evidence region')
            else:
                raise ValueError('Unsupported evidence basis')
            if attribute['field'] in color_fields:
                role = color_fields[attribute['field']]
                if entry['basis'] != 'image_pixels' or entry.get('region') != role or attribute['object'] != catalog['color_objects'][role]:
                    raise ValueError('Color field, object and image region must agree')
                observed = image_reviews[pid]['colors'][role]
                if attribute['status'] == 'positive' and attribute['value_en'] not in observed['values_en']:
                    raise ValueError('Color value was not observed in the cited image region')
    if any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Feature IDs must be distinct')
    if not isinstance(review.get('summary_en'), str) or not review['summary_en'].strip():
        raise ValueError('Missing display summary')
    return review


def image_text(image):
    """角色写入组件编码文本；不再向每张图复制整套描述。"""
    rows = ['Composition: ' + image['composition_en'], 'Scene: ' + image['scene_en']]
    for role, values in image['colors'].items():
        if values['status'] == 'observed':
            rows.append(role.replace('_', ' ') + ' colors: ' + ', '.join(values['values_en']))
    rows.append('Expression methods: ' + '; '.join(image['expression_methods']))
    return '\n'.join(rows)


def whole_text(attributes):
    """整体编码一次；负面、冲突和未知保留为元数据，不作为正向卖点。"""
    rows = []
    for attribute in attributes:
        if attribute['status'] != 'positive':
            continue
        line = f"{attribute['field']} / {attribute['object']}: {attribute['text_en']}"
        if attribute['conditions']:
            line += ' Conditions: ' + ' '.join(attribute['conditions'])
        rows.append(line)
    text = '\n'.join(rows)
    if not text or len(text) > 6000:
        raise ValueError('Revise positive feature synthesis; never truncate detailed attributes')
    return text


def compile_review(bundle, review, encoder, catalog=None):
    """返回一个新整体版本和更新的组件副本；不改源文件或历史数据集。"""
    catalog = catalog or load_catalog()
    validate_review(review, bundle, catalog)
    projected = deepcopy(bundle)
    images = {p['part_id']: p for p in review['image_reviews']}
    for part in projected['parts']:
        image = images.get(part['part_id'])
        if image is None:
            continue
        text = image_text(image)
        vector = normalized(encoder.encode(text)).tolist()
        f = part['features']
        f.update(semantic_description_en=text, visual_review=deepcopy(image),
                 palette=list(dict.fromkeys(c for x in image['colors'].values() for c in x['values_en'])),
                 composition=image['composition_en'],scene=image['scene_en'],themes=list(image['expression_methods']),
                 claims=[],observed_text_claims_verified=False,
                 analysis_method='per_image_review_v2', quality_score=None)
        part['embedding'] = {'model': encoder.model, 'model_digest': encoder.digest, 'recipe': PART_RECIPE,
                             'dimensions': len(vector), 'input_sha256': hashlib.sha256(text.encode()).hexdigest(), 'vector': vector}
    attributes = deepcopy(review['attributes'])
    text = whole_text(attributes)
    vector = normalized(encoder.encode(text)).tolist()
    groups = {key: [] for key in ('selling_points', 'product_traits', 'visual_elements', 'style')}
    for a in attributes:
        if a['status'] != 'positive':
            continue
        refs = list(dict.fromkeys(e['part_id'] for e in a['evidence']))
        groups[catalog['fields'][a['field']]['group']].append({
            'label_zh': a['label_zh'], 'text_en': a['text_en'], 'conditions': a['conditions'],
            'basis': 'source_claim' if a['evidence'][0]['basis'] == 'source_text' else 'reviewed_visual_observation',
            'subject': a['object'], 'evidence_part_ids': refs, 'feature_id': a['feature_id']})
    structured = {**groups, 'schema': SCHEMA, 'summary_en': review['summary_en'],
                  'attribute_features': attributes, 'expression_sequence': review.get('expression_sequence', []),
                  'limitations': []}
    overall = {**groups, 'keywords': [a['label_zh'] for a in attributes if a['status'] == 'positive'],
               'product_form': bundle['overall_features'].get('product_form'),
               'historical_rank': bundle['overall_features'].get('historical_rank'),
               'embedding_text_en': text, 'information_order': structured['expression_sequence'], 'limitations': []}
    projection = digest([p.get('features',{}) for p in projected['parts']])
    version = digest([SCHEMA, source_fingerprint(bundle), review, encoder.digest, text, projection])
    whole = {'record_type': 'whole_listing', 'listing_version_id': version, 'identity': deepcopy(bundle['identity']),
             'source_bundle_id': bundle['bundle_id'], 'structured_features': structured, 'overall_features': overall,
             'embedding': {'model': encoder.model, 'model_digest': encoder.digest, 'recipe': RECIPE,
                           'dimensions': len(vector), 'input_text': text, 'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
                           'vector': vector, 'derived_from': 'independent_detailed_attributes_single_encode'},
             'component_ids': [p['part_id'] for p in bundle['parts']],
             'review_provenance': {k: deepcopy(v) for k, v in review.items() if k not in ('attributes', 'image_reviews')},
             'coverage': deepcopy(bundle.get('coverage', {})), 'approval_status': 'pending_operator_review', 'quality_score': None}
    return whole, projected


def vocabulary(wholes, catalog=None):
    """给未来查询LLM的字段和值域快照。只列实际正向值，未知值允许不命中。"""
    catalog = catalog or load_catalog()
    fields = {}
    constraints = []
    for whole in wholes:
        for a in whole['structured_features']['attribute_features']:
            if a['status'] != 'positive':
                constraints.append({'listing_version_id':whole['listing_version_id'], **deepcopy(a)})
                continue
            key = (a['field'], a['object'], a['value_en'])
            row = fields.setdefault(key, {'field': a['field'], 'object': a['object'], 'value_en': a['value_en'],
                                           'label_zh': a['label_zh'], 'listing_version_ids': [], 'observations': []})
            if whole['listing_version_id'] not in row['listing_version_ids']:
                row['listing_version_ids'].append(whole['listing_version_id'])
            row['observations'].append({'listing_version_id':whole['listing_version_id'],'feature_id':a['feature_id'],
                                         'scope':a['scope'],'conditions':a['conditions'],
                                         'evidence_part_ids':list(dict.fromkeys(e['part_id'] for e in a['evidence']))})
    result = {'schema': 'listing-query-vocabulary-v1', 'catalog': catalog,
              'dataset_listing_versions': [w['listing_version_id'] for w in wholes],
              'values': list(fields.values()), 'constraints':constraints,'is_exhaustive_allowed_universe': False,
              'source': 'observed_positive_features_not_verified_own_product_facts'}
    result['vocabulary_id'] = digest(result)
    return result
