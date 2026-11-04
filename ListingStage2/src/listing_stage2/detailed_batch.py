"""新版细粒度特征的任务准备、审阅校验及双集合发布。默认要求整批完整。"""
import argparse
import json
import hashlib
from pathlib import Path

from .detailed_extraction import SCHEMA, load_catalog, eligible_images, compile_review, vocabulary
from .structured_whole import source_fingerprint
from .collection_store import export_dataset, point_records, read_dataset
from .listing_bundles import digest
from .local_encoder import LocalEncoder
from .storage import write
from .component_policy import resolve
from .query_contract import contract, SYSTEM as QUERY_SYSTEM


def source_paths(source):
    paths = sorted(Path(source).glob('rank*/listing_features.json'), key=lambda p:int(p.parent.name[4:]))
    if not paths:
        raise ValueError('No source bundles')
    return paths


def prepare(source, output, catalog=None):
    """输出完整文字与逐图任务；旧组件描述不是新像素审阅的替代品。"""
    catalog = catalog or load_catalog()
    output = Path(output)
    if output.exists():
        raise ValueError('Use a new task directory')
    output.mkdir(parents=True)
    tasks = []
    for path in source_paths(source):
        bundle = json.loads(path.read_bytes())
        controls = resolve(bundle)
        texts = [{'part_id':p['part_id'], 'role':p['role'], 'source_text':p['source_text']}
                 for p in bundle['parts'] if controls[p['part_id']]['include_in_overall'] and p.get('source_text')]
        images = [{'part_id':p['part_id'], 'role':p['role'], 'asset':p['asset']} for p in eligible_images(bundle)]
        task = {'schema':SCHEMA, 'status':'pending_new_pixel_and_text_review', 'source_bundle_id':bundle['bundle_id'],
                'source_fingerprint':source_fingerprint(bundle), 'catalog_sha256':digest(catalog), 'identity':bundle['identity'],
                'complete_text_components':texts, 'image_tasks':images,
                'video_analysis_status':'not_reanalysed_do_not_infer_from_thumbnail', 'catalog':catalog}
        target = output / (path.parent.name + '.json')
        write(target, task)
        tasks.append({'capture_rank':bundle['overall_features']['historical_rank'], 'task':str(target),
                      'images':len(images), 'text_components':len(texts)})
    write(output/'tasks.json', {'status':'pending_reviews', 'tasks':tasks, 'paid_api_calls':0})
    return tasks


def run(source, reviews, output, store_path, allow_partial=False, catalog=None):
    catalog = catalog or load_catalog()
    output, reviews = Path(output), Path(reviews)
    if output.exists():
        raise ValueError('Use a new release directory')
    paths = source_paths(source)
    missing = [p.parent.name for p in paths if not (reviews/(p.parent.name+'.json')).exists()]
    if missing and not allow_partial:
        raise ValueError('Incomplete reviews; explicitly use --allow-partial for a pilot: '+', '.join(missing))
    pairs = []
    for path in paths:
        review_path = reviews/(path.parent.name+'.json')
        if review_path.exists():
            pairs.append((json.loads(path.read_bytes()), json.loads(review_path.read_bytes())))
    if not pairs:
        raise ValueError('No detailed reviews supplied')
    # 全部审阅先校验，再调用本地编码器或创建数据库。
    from .detailed_extraction import validate_review
    for bundle, review in pairs:
        validate_review(review, bundle, catalog)
        for part in eligible_images(bundle):
            if hashlib.sha256(Path(part['asset']['local_path']).read_bytes()).hexdigest()!=part['asset']['asset_sha256']:
                raise ValueError('Reviewed media file changed; review original pixels again')
    encoder = LocalEncoder(Path(__file__).resolve().parents[2]/'data/listing_embedding_cache')
    built = [compile_review(b, r, encoder, catalog) for b,r in pairs]
    dataset = digest(['detailed-v6', [w['listing_version_id'] for w,b in built]])
    wholes, components = [], []
    for whole, bundle in built:
        w, c = point_records(whole, bundle, dataset)
        wholes.append(w); components.extend(c)
    output.mkdir(parents=True)
    manifest = export_dataset(wholes, components, output/'library', store_path,
                              collections={'whole':'listing_wholes_v6','component':'listing_components_v6'})
    stored, actual_wholes, actual_components = read_dataset(output/'library/library_index.json')
    import numpy as np
    expected = {p['id']:p for p in wholes+components}
    for actual in actual_wholes+actual_components:
        before = expected[actual['id']]
        if before['payload'] != actual['payload']:
            raise ValueError('Stored feature payload differs')
        if before['vector'] is not None and not np.allclose(before['vector'],actual['vector'],atol=1e-6):
            raise ValueError('Stored vector differs')
    write(output/'feature-vocabulary.json', vocabulary([w for w,b in built],catalog))
    write(output/'query-contract.json',contract(catalog))
    (output/'query-system-prompt.txt').write_text(QUERY_SYSTEM,encoding='utf-8')
    write(output/'verification.json', {'status':'passed','counts':manifest['counts'], 'missing_review_ranks':missing,
           'partial_pilot':bool(missing),
           'image_role_records':sum(len(r['image_reviews']) for b,r in pairs),
           'newly_reviewed_images':sum(i.get('fresh_pixel_review',True) for b,r in pairs for i in r['image_reviews']),
           'legacy_caption_only_images':sum(i.get('fresh_pixel_review') is False for b,r in pairs for i in r['image_reviews']),
           'image_records_with_unassessed_colors':sum(any(c['status']=='not_assessed' for c in i['colors'].values()) for b,r in pairs for i in r['image_reviews']),
           'atomic_attributes':sum(len(r['attributes']) for b,r in pairs), 'paid_api_calls':0,
           'semantic_approval':'pending_operator_review', 'database_roundtrip_verified':True,
           'video_reanalysed':False, 'original_v5_library_replaced':False})
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reviews',type=Path);p.add_argument('--store-path',type=Path)
    p.add_argument('--catalog',type=Path);p.add_argument('--prepare',action='store_true')
    p.add_argument('--allow-partial',action='store_true')
    a=p.parse_args();catalog=load_catalog(a.catalog)
    if a.prepare:
        result={'tasks':len(prepare(a.source,a.output,catalog)),'model_calls':0}
    else:
        if not a.reviews or not a.store_path:p.error('--reviews and --store-path required')
        result=run(a.source,a.reviews,a.output,a.store_path,a.allow_partial,catalog)['counts']
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
