"""验证新版提取的角色归属、精确证据和向量版本；不以关键词判断业务语义。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

from listing_stage2.detailed_extraction import (SCHEMA, load_catalog, validate_review, compile_review,
                                               whole_text, vocabulary, image_text)
from listing_stage2.structured_whole import source_fingerprint
from listing_stage2.listing_bundles import digest
from listing_stage2.detailed_batch import run
from listing_stage2.detailed_model_review import create_review, plan


class Encoder:
    model='fake';digest='fake-digest'
    def __init__(self):self.calls=[]
    def encode(self,text,query=False):
        self.calls.append(text)
        return np.array([1.,2. if 'purple' in text else 0.])


def fixture():
    catalog=load_catalog()
    parts=[{'part_id':'title','role':'title','entity_kind':'text','source_text':'Soft foam topper with washable cover.',
            'features':{},'asset':None,'eligible_for_aggregate':True}]
    images=[]
    for i,color in enumerate(('purple','white')):
        pid='image'+str(i)
        parts.append({'part_id':pid,'role':'main_image' if not i else 'gallery','entity_kind':'image','source_text':None,
                      'features':{'identity_scope':'current_or_family'},'eligible_for_aggregate':True,
                      'asset':{'local_path':'unused.png','asset_sha256':'hash'+str(i)}})
        colors={role:{'status':'not_visible','values_en':[]} for role in catalog['color_roles']}
        colors['product_surface']={'status':'observed','values_en':[color]}
        colors['text']={'status':'observed','values_en':['blue']}
        images.append({'part_id':pid,'asset_sha256':'hash'+str(i),'colors':colors,
                       'composition_en':'Product photograph '+str(i),'scene_en':'Studio','expression_methods':['material closeup']})
    bundle={'bundle_id':'bundle','identity':dict(country_code='US',site_id='amazon',category_id='toppers',product_id='one',snapshot_id='snap'),
            'parts':parts,'overall_features':{'historical_rank':1,'product_form':'foam'},'coverage':{}}
    attrs=[{'feature_id':'soft','field':'firmness','object':'whole_product','value_en':'soft','text_en':'soft',
            'label_zh':'柔软','scope':'selected','status':'positive','conditions':[],
            'evidence':[{'part_id':'title','basis':'source_text','quote':'Soft'}]},
           {'feature_id':'color','field':'product_color','object':'surface','value_en':'purple','text_en':'purple',
            'label_zh':'紫色','scope':'main image','status':'positive','conditions':[],
            'evidence':[{'part_id':'image0','basis':'image_pixels','asset_sha256':'hash0','region':'product_surface'}]}]
    review={'schema':SCHEMA,'source_bundle_id':'bundle','source_fingerprint':source_fingerprint(bundle),
            'catalog_sha256':digest(catalog),'reviewed_source_text_part_ids':['title'],
            'summary_en':'A soft foam reference.','attributes':attrs,'image_reviews':images}
    return bundle,review,catalog


class DetailedTests(unittest.TestCase):
    def test_requires_separate_review_for_every_image(self):
        b,r,c=fixture();r['image_reviews'].pop()
        with self.assertRaises(ValueError):validate_review(r,b,c)

    def test_product_color_cannot_use_blue_text_region(self):
        b,r,c=fixture();a=r['attributes'][1]
        a['value_en']='blue';a['evidence'][0]['region']='text'
        with self.assertRaises(ValueError):validate_review(r,b,c)
        a['evidence'][0]['region']='product_surface'
        with self.assertRaises(ValueError):validate_review(r,b,c)

    def test_text_color_is_supported_when_object_and_region_agree(self):
        b,r,c=fixture();a=r['attributes'][1]
        a.update(field='text_color',object='text',value_en='blue')
        a['evidence'][0]['region']='text'
        self.assertIs(validate_review(r,b,c),r)

    def test_visual_color_cannot_cite_title(self):
        b,r,c=fixture();r['attributes'][1]['evidence']=[{'part_id':'title','basis':'source_text','quote':'Soft'}]
        with self.assertRaises(ValueError):validate_review(r,b,c)

    def test_quotes_must_exist_and_hashes_bind_source(self):
        b,r,c=fixture();bad=deepcopy(r);bad['attributes'][0]['evidence'][0]['quote']='invented'
        with self.assertRaises(ValueError):validate_review(bad,b,c)
        bad=deepcopy(r);bad['image_reviews'][0]['asset_sha256']='wrong'
        with self.assertRaises(ValueError):validate_review(bad,b,c)
        b['parts'][0]['source_text']='Changed'
        with self.assertRaises(ValueError):validate_review(r,b,c)

    def test_catalog_and_complete_text_coverage_checked(self):
        b,r,c=fixture();bad=deepcopy(r);bad['reviewed_source_text_part_ids']=[]
        with self.assertRaises(ValueError):validate_review(bad,b,c)
        bad=deepcopy(r);bad['catalog_sha256']='other'
        with self.assertRaises(ValueError):validate_review(bad,b,c)

    def test_unknown_does_not_become_observed(self):
        b,r,c=fixture();r['image_reviews'][0]['colors']['product_core']={'status':'not_assessed','values_en':['blue']}
        with self.assertRaises(ValueError):validate_review(r,b,c)

    def test_independent_images_and_whole_encode_once_without_source_mutation(self):
        b,r,c=fixture();before=deepcopy(b);encoder=Encoder();whole,projected=compile_review(b,r,encoder,c)
        self.assertEqual(len(encoder.calls),3)  # 两张图各一次，整体单独一次。
        self.assertNotEqual(projected['parts'][1]['embedding']['vector'],projected['parts'][2]['embedding']['vector'])
        self.assertEqual(b,before)
        self.assertNotIn('components',whole)
        self.assertIn('product surface colors: purple',encoder.calls[0])
        self.assertIn('text colors: blue',encoder.calls[0])

    def test_negative_and_conflicting_are_metadata_not_positive_vectors(self):
        b,r,c=fixture()
        for status in ('negative','conflicting','unknown'):
            item=deepcopy(r['attributes'][0]);item.update(feature_id=status,status=status,value_en='storage',text_en='long term folding')
            r['attributes'].append(item)
        whole,projected=compile_review(b,r,Encoder(),c)
        self.assertNotIn('long term folding',whole['embedding']['input_text'])
        self.assertEqual(len(whole['structured_features']['attribute_features']),5)

    def test_vocabulary_records_actual_objects_and_allows_unknown_values(self):
        b,r,c=fixture();whole,_=compile_review(b,r,Encoder(),c);v=vocabulary([whole],c)
        self.assertFalse(v['is_exhaustive_allowed_universe'])
        self.assertTrue(any(x['object']=='surface' and x['value_en']=='purple' for x in v['values']))

    def test_query_contract_and_constraints_come_from_same_catalog(self):
        from listing_stage2.query_contract import contract
        b,r,c=fixture();item=deepcopy(r['attributes'][0]);item.update(feature_id='negative',status='negative')
        r['attributes'].append(item)
        whole,_=compile_review(b,r,Encoder(),c);v=vocabulary([whole],c)
        self.assertEqual(v['constraints'][0]['status'],'negative')
        self.assertIn('conditions',v['values'][0]['observations'][0])
        fields=contract(c)['properties']['clauses']['items']['properties']['possible_fields']['items']['enum']
        self.assertEqual(set(fields),set(c['fields']))

    def test_incomplete_batch_rejected_before_encoding(self):
        b,r,c=fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'source/rank1').mkdir(parents=True);(root/'reviews').mkdir()
            (root/'source/rank1/listing_features.json').write_text(json.dumps(b),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'Incomplete reviews'):
                run(root/'source',root/'reviews',root/'release',root/'db')
            self.assertFalse((root/'release').exists())

    def test_future_api_sends_each_image_and_full_text_without_live_call(self):
        b,r,c=fixture()
        with tempfile.TemporaryDirectory() as temp:
            for i,p in enumerate(b['parts'][1:]):
                path=Path(temp)/f'{i}.png';path.write_bytes(b'fake-'+str(i).encode())
                p['asset'].update(local_path=str(path),asset_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                r['image_reviews'][i]['asset_sha256']=p['asset']['asset_sha256']
            r['attributes'][1]['evidence'][0]['asset_sha256']=b['parts'][1]['asset']['asset_sha256']
            b['parts'][0]['source_text']+=' '+'end of full text '*100+'TAIL_TOKEN'
            class FakeGateway:
                def __init__(self):self.calls=[]
                def complete(self,system,prompt,image=None):
                    self.calls.append((prompt,image))
                    value=r['image_reviews'][len(self.calls)-1] if image else {'summary_en':r['summary_en'],'attributes':r['attributes']}
                    return deepcopy(value),{'model':'fake_no_network'}
            gateway=FakeGateway();config={'max_calls':3,'max_image_bytes':100}
            review=create_review(b,config,gateway,c)
            self.assertEqual(len(gateway.calls),3)
            self.assertTrue(all(image is not None for prompt,image in gateway.calls[:2]))
            self.assertIn('TAIL_TOKEN',gateway.calls[-1][0])
            self.assertEqual(review['source_fingerprint'],source_fingerprint(b))
            with self.assertRaises(ValueError):plan(b,{'max_calls':2,'max_image_bytes':100},c)


if __name__=='__main__':unittest.main()
