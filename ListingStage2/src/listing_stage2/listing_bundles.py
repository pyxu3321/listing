# 文件用途：共用素材装配及历史v2实验。encode_bundle使用角色加权聚合，仅保留对比；当前整体独立向量用whole_listing.py。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Whole-Listing retrieval units, preserving independently selectable parts."""
from collections import defaultdict
import hashlib
import json
import re
from pathlib import Path
import numpy as np
from .local_encoder import normalized
from .storage import write

RECIPE = 'listing-role-balanced-chunks-v1'
WEIGHTS = {'product': 2, 'main_image': 2, 'gallery': 2, 'bullet': 2, 'title': 1, 'aplus': 1, 'description': 1, 'video': 1}


# 功能及输出：输入可JSON序列化对象；规范排序后计算SHA256，拒绝NaN，用于版本和缓存标识。
# 参数：value（待校验/序列化对象）。
def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


# 功能及输出：输入目录字段；限制字符和Windows保留名，返回安全路径片段。
# 参数：value（待校验/序列化对象）。
def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value) or value.upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        raise ValueError('Unsafe catalogue component')
    return value


# 功能及输出：输入旧特征payload和原报告；按快照归集组件、角色、媒体和证据，返回bundle列表；无模型调用。
# 参数：payload（旧实验结构化数据）；report（采集报告路径或已读取报告）。
def assemble(payload, report):
    config = report['config']
    country = segment(config.get('country_code', config['marketplace']))
    site = segment(config.get('site_id', 'amazon'))
    category = segment(config.get('category_id', 'toppers' if str(config.get('category_node')) == '8521807011' else 'node-' + str(config['category_node'])))
    refs = {r['reference_id']:r for r in payload['references']}
    assets = {a['asset_sha256']:a for a in payload['assets']}
    bundles = []
    for snap in payload['snapshots']:
        source = next(p for p in report['products'] if p['snapshot_id'] == snap['snapshot_id'])
        product = segment(snap.get('product_id') or snap['asin'])
        identity = {'country_code': country, 'site_id': site, 'category_id': category, 'product_id': product, 'snapshot_id': segment(snap['snapshot_id'])}
        parts, documents, excluded = [], defaultdict(list), []
        for feature in sorted((f for f in payload['features'] if f['snapshot_key'] == snap['snapshot_key']), key=lambda f:f['feature_id']):
            data, role = feature['features'], feature['entity_kind']
            ref = refs.get(feature['image_reference_id'])
            scope = data.get('identity_scope')
            eligible = not ref or scope == 'current_or_family'
            media = None
            if ref:
                source_role = {'main':'gallery','secondary':'gallery'}.get(ref['source_role'],ref['source_role'])
                media = next((m for m in source.get('media', []) if m.get('sha256') == ref['asset_sha256'] and m.get('role') == source_role), None)
                role = 'main_image' if media and media.get('is_main_image') else source_role
                if role == 'aplus_dom': role = 'aplus'
            elif role == 'aplus_dom': role = 'aplus'
            text = data.get('semantic_description_en') or feature.get('source_text')
            # The product analysis is the existing reviewed overall narrative.
            # Individual visual records retain exact source pointers and cautions.
            part = {'part_id': feature['feature_id'], 'role': role, 'entity_kind': feature['entity_kind'], 'source_text': feature.get('source_text'), 'features': data, 'reference': ref, 'asset': assets.get(ref['asset_sha256']) if ref else None, 'is_main_image': role == 'main_image', 'eligible_for_aggregate': eligible, 'module_placements': media.get('placements', []) if media else []}
            parts.append(part)
            if eligible and text:
                documents[role].append({'part_id': part['part_id'], 'text': ' '.join(text.split())})
            else:
                excluded.append(part['part_id'])
        recipe_input = {'identity': identity, 'documents': dict(documents), 'recipe': RECIPE, 'weights': WEIGHTS}
        bundle = {'schema_version': 2, 'bundle_id': digest(recipe_input), 'identity': identity, 'source_id': report['source_id'], 'source_url': snap['source_url'], 'snapshot_key': snap['snapshot_key'], 'title': snap['original_copy'].get('title'), 'parts': parts, 'aggregate_documents': dict(documents), 'excluded_part_ids': excluded, 'source_inventory': {'media': source.get('media', []), 'original_copy': snap['original_copy']}, 'coverage': {'source_stored_media': sum(m.get('status') == 'stored' for m in source.get('media', [])), 'reviewed_media': sum(bool(p['reference']) for p in parts), 'video_status': 'pending_analysis' if any(m.get('kind') == 'video' for m in source.get('media', [])) else 'skipped_no_input'}, 'approval_status': 'pending_review', 'quality_score': None, 'vector_kind': 'listing_feature_text', 'recipe': RECIPE, 'weights': WEIGHTS, 'rank_is_quality': False}
        bundles.append(bundle)
    return bundles


# 功能及输出：历史v2角色加权聚合：分块编码后按角色平均与加权；返回带聚合向量的bundle，不能当作v3独立整体叙述。
# 参数：bundle（一个Listing快照及组件）；encoder（带模型摘要的编码器）。
def encode_bundle(bundle, encoder):
    channels, evidence = [], []
    for role, records in sorted(bundle['aggregate_documents'].items()):
        vectors = []
        for record in records:
            text = role + ': ' + record['text']
            chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
            # Per-part averaging avoids long text/large galleries drowning out roles.
            vectors.append(normalized(np.mean([encoder.encode(c) for c in chunks], axis=0)))
            evidence.append({'part_id': record['part_id'], 'role': role, 'text_sha256': digest(text), 'chunks': len(chunks)})
        channels.append((WEIGHTS.get(role, 1), normalized(np.mean(vectors, axis=0))))
    if not channels:
        raise ValueError('No analyzed content for whole-Listing embedding')
    vector = normalized(sum(weight*v for weight,v in channels))
    return {**bundle, 'embedding': {'model': encoder.model, 'model_digest': encoder.digest, 'space_id': digest([encoder.digest, RECIPE, WEIGHTS]), 'dimensions': len(vector), 'input_sha256': digest(bundle['aggregate_documents']), 'evidence': evidence, 'vector': vector.tolist()}}


# 功能及输出：输入输出目录与v2包；写分类JSON、listing_index.json和listings.html。
# 参数：out（输出目录）；bundles（当前批次Listing集合）。
def export_bundles(out, bundles):
    import html
    esc = lambda x: html.escape(str(x), quote=True)
    entries = []
    sections = []
    for bundle in bundles:
        i = bundle['identity']
        relative = Path('catalog', i['country_code'], i['site_id'], i['category_id'], i['product_id'], i['snapshot_id'], 'listing_features.json')
        write(out/relative, bundle)
        entries.append({'bundle_id': bundle['bundle_id'], 'identity': i, 'title': bundle['title'], 'path': relative.as_posix(), 'approval_status': bundle['approval_status']})
        cards = []
        for part in bundle['parts']:
            asset = part['asset']
            image = '<img loading="lazy" src="' + esc(Path(asset['local_path']).as_uri()) + '">' if asset else ''
            cards.append('<article>' + image + '<h3>' + esc(part['role']) + '</h3><small>' + esc(part['part_id']) + '</small><pre>' + esc(part['source_text'] or json.dumps(part['features'],ensure_ascii=False,indent=2)) + '</pre></article>')
        sections.append('<section><h2>' + esc(i['product_id']) + ' · ' + esc(bundle['title']) + '</h2><p>' + esc('/'.join(i.values())) + '</p><p>整体向量 ' + str(bundle['embedding']['dimensions']) + ' 维 · 待审核；图片来自已记录的人工分析。</p><a href="' + esc(relative.as_posix()) + '">完整特征包 JSON</a><div class="grid">' + ''.join(cards) + '</div></section>')
    write(out/'listing_index.json', {'schema_version': 2, 'retrieval_unit': 'whole_listing', 'listings': entries})
    (out/'listings.html').write_text('<!doctype html><meta charset="utf-8"><title>整体 Listing 特征库</title><style>body{font:15px system-ui;background:#f4f6f8;padding:24px}section{background:white;padding:20px;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}article{border:1px solid #ddd;padding:12px;min-width:0}img{width:100%;height:200px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{overflow-wrap:anywhere}</style><h1>第二阶段 · 整套 Listing 特征</h1><p>检索单位为完整商品快照；各部分保留以供组合参考。整体向量编码分析文字，未执行新的视觉模型或像素编码。</p>' + ''.join(sections),encoding='utf-8')


# 功能及输出：输入v2候选、查询、编码器、国家/品类和数量；过滤状态并验证空间后返回余弦排序，不自动批准。
# 参数：bundles（当前批次Listing集合）；query（查询文本或查询模式开关）；encoder（带模型摘要的编码器）；country（国家过滤值）；category（品类过滤值）；limit（最多返回数量）；include_pending（是否包含未批准项）。
def match(bundles, query, encoder, country, category, limit=5, include_pending=False):
    q = encoder.encode(query, query=True)
    results = []
    for b in bundles:
        if b['identity']['country_code'] != country or b['identity']['category_id'] != category:
            continue
        if not include_pending and b['approval_status'] != 'approved':
            continue
        e = b['embedding']
        if e['space_id'] != digest([encoder.digest, RECIPE, WEIGHTS]) or e['dimensions'] != len(q):
            raise ValueError('Incompatible whole-Listing vector space')
        results.append({'bundle_id': b['bundle_id'], 'identity': b['identity'], 'score': float(np.dot(q, normalized(e['vector']))), 'title': b['title'], 'parts': b['parts'], 'approval_status': b['approval_status']})
    return sorted(results, key=lambda x:(-x['score'], x['bundle_id']))[:limit]


# 功能及输出：输入候选包与组件选择表；返回保留来源的待审核参考包，选中不等于批准。
# 参数：bundles（当前批次Listing集合）；selections（整体及组件选择记录）。
def select_parts(bundles, selections):
    """Build a traceable draft reference pack; never turns a selection into approval."""
    by_id = {b['bundle_id']:b for b in bundles}
    chosen = []
    for selection in selections:
        bundle = by_id[selection['bundle_id']]
        part = next(p for p in bundle['parts'] if p['part_id'] == selection['part_id'])
        chosen.append({'bundle_id': bundle['bundle_id'], 'identity': bundle['identity'], 'part_id': part['part_id'], 'source_role': part['role'], 'planned_use': selection['planned_use'], 'source_url': bundle['source_url']})
    return {'schema_version': 1, 'status': 'draft_pending_review', 'selections': chosen, 'competitor_claims_are_not_own_product_facts': True}
