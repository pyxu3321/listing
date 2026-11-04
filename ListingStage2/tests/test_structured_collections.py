"""结构化整体独立编码、父子外键及真实本地Qdrant持久化回归。"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
import numpy as np
from listing_stage2.structured_whole import SCHEMA,source_fingerprint,validate_review,build_whole
from listing_stage2.collection_store import point_records,validate_points,export_dataset,read_dataset,query_collection


class Encoder:
    model='test';digest='test-model'
    def __init__(self):self.calls=[]
    def encode(self,text,query=False):
        self.calls.append(text)
        return np.array([1.,2. if 'lightweight' in text else 0.])


def fixture(name='one'):
    e={'model':'test','model_digest':'test-model','recipe':'component-semantic-text-v1','dimensions':2,'vector':[1.,0.]}
    identity=dict(country_code='US',site_id='amazon',category_id='toppers',product_id=name,snapshot_id='snap')
    parts=[dict(part_id=name+'-title',role='title',entity_kind='text',source_text='Foam topper',features={},asset=None,reference={'snapshot_id':'snap'},eligible_for_aggregate=True,embedding=deepcopy(e)),
           dict(part_id=name+'-bullet',role='bullet',entity_kind='text',source_text='A lightweight soft layer for the two-inch source variant.',features={},asset=None,reference={'snapshot_id':'snap'},eligible_for_aggregate=True,embedding=deepcopy(e)),
           dict(part_id=name+'-image',role='main_image',entity_kind='image',source_text=None,features={'identity_scope':'current_or_family','semantic_description_en':'Blue foam product hero'},asset={'local_path':'missing.jpg','asset_sha256':'hash'},reference={'snapshot_id':'snap'},eligible_for_aggregate=True,embedding=deepcopy(e))]
    bundle={'bundle_id':name,'identity':identity,'parts':parts,'coverage':{},'overall_features':{'product_form':'foam','historical_rank':1}}
    def f(text,pid,basis='source_claim',conditions=None):
        return {'text_en':text,'label_zh':text,'basis':basis,'subject':'source_product_or_qualified_variant' if basis=='source_claim' else 'captured_product_appearance','conditions':conditions or [],'evidence_part_ids':[pid]}
    review={'schema':SCHEMA,'source_bundle_id':name,'source_fingerprint':source_fingerprint(bundle),
       'reviewed_source_text_part_ids':[p['part_id'] for p in parts[:2]],'features':{'summary_en':'A soft foam reference.',
       'selling_points':[f('A lightweight soft comfort layer',parts[1]['part_id'],conditions=['Only the two-inch source variant.'])],
       'product_traits':[f('Foam construction',parts[0]['part_id'])],
       'visual_elements':[f('Blue foam hero',parts[2]['part_id'],'reviewed_visual_observation')],
       'style':[],'expression_sequence':[],'limitations':['Source claim, not verified own facts.']}}
    return bundle,review


class StructuredCollectionTests(unittest.TestCase):
    def test_whole_encoded_once_without_raw_text_or_component_average(self):
        b,r=fixture();e=Encoder();whole=build_whole(b,r,e)
        self.assertEqual(len(e.calls),1)
        self.assertIn('Only the two-inch source variant.',e.calls[0])
        self.assertNotIn(b['parts'][1]['source_text'],e.calls[0])
        self.assertNotIn('components',whole)
        self.assertNotIn('parts',whole)
        b2=deepcopy(b)
        for p in b2['parts']:p['embedding']['vector']=[0.,1.]
        r2=deepcopy(r);r2['source_fingerprint']=source_fingerprint(b2)
        other=build_whole(b2,r2,Encoder())
        self.assertEqual(whole['embedding']['vector'],other['embedding']['vector'])

    def test_background_exclusions_are_not_positive_retrieval_text(self):
        b,r=fixture();r['features']['summary_en']='A soft topper. A smartphone accessory and waterproof protector are not included.'
        r['features']['limitations']=['No smartphone control is established.']
        e=Encoder();whole=build_whole(b,r,e)
        self.assertNotIn('smartphone',e.calls[0])
        self.assertNotIn('waterproof',e.calls[0])
        self.assertIn('smartphone',whole['structured_features']['summary_en'])
        self.assertIn('Only the two-inch source variant.',e.calls[0])

    def test_stale_foreign_excluded_and_incomplete_review_rejected(self):
        b,r=fixture()
        changed=deepcopy(b);changed['parts'][1]['source_text']='Changed source'
        with self.assertRaises(ValueError):validate_review(r,changed)
        foreign=deepcopy(r);foreign['features']['selling_points'][0]['evidence_part_ids']=['elsewhere']
        with self.assertRaises(ValueError):validate_review(foreign,b)
        missing=deepcopy(r);missing['reviewed_source_text_part_ids']=[]
        with self.assertRaises(ValueError):validate_review(missing,b)
        b['parts'][1]['analysis_controls']={'include_in_overall':False}
        r['source_fingerprint']=source_fingerprint(b);r['reviewed_source_text_part_ids']=[b['parts'][0]['part_id']]
        with self.assertRaises(ValueError):validate_review(r,b)

    def test_parent_link_and_separate_component_vectors(self):
        b,r=fixture();w=build_whole(b,r,Encoder());whole,parts=point_records(w,b,'dataset')
        self.assertEqual(len(parts),3)
        self.assertNotIn('components',whole['payload'])
        for p,old in zip(parts,b['parts']):
            self.assertEqual(p['vector'],old['embedding']['vector'])
            self.assertEqual(p['payload']['parent_listing_version_id'],w['listing_version_id'])
        validate_points([whole],parts)
        parts[0]['payload']['parent_listing_version_id']='foreign'
        with self.assertRaises(ValueError):validate_points([whole],parts)

    def test_qdrant_roundtrip_and_component_parent_filter(self):
        wholes=[];components=[];versions=[]
        for name in ('one','two'):
            b,r=fixture(name);w=build_whole(b,r,Encoder());versions.append(w['listing_version_id'])
            whole,parts=point_records(w,b,'dataset');wholes.append(whole);components.extend(parts)
        components[1]['payload']['controls']['generation_reference']=False
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=export_dataset(wholes,components,root/'export',root/'db')
            path=root/'export/library_index.json';stored,w,p=read_dataset(path)
            self.assertEqual(len(w),2);self.assertEqual(len(p),6)
            hits=query_collection(path,[1.,0.],limit=20,listing_version_ids=[versions[0]])
            self.assertEqual(len(hits),2)
            self.assertTrue(all(x['payload']['parent_listing_version_id']==versions[0] for x in hits))
            self.assertEqual(query_collection(path,[1.,0.],listing_version_ids=[]),[])
            self.assertEqual(len(query_collection(path,[1.,0.],limit=20)),2)
            target=root/'export/collections/whole_records.jsonl'
            target.write_text(target.read_text(encoding='utf-8')+' ',encoding='utf-8')
            with self.assertRaises(ValueError):read_dataset(path)

    def test_multiple_dataset_publications_do_not_overwrite_membership(self):
        b,r=fixture();w=build_whole(b,r,Encoder())
        first,a=point_records(w,b,'publication-one');second,c=point_records(w,b,'publication-two')
        self.assertNotEqual(first['id'],second['id'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            export_dataset([first],a,root/'one',root/'db')
            export_dataset([second],c,root/'two',root/'db')
            self.assertEqual(len(read_dataset(root/'one/library_index.json')[1]),1)
            self.assertEqual(len(read_dataset(root/'two/library_index.json')[1]),1)

    def test_future_model_review_sends_full_source_and_checks_response(self):
        from listing_stage2.structured_model_review import create_review
        b,r=fixture();b['parts'][1]['source_text']='Intro '*60+'TAIL_FULL_SOURCE'
        class FakeGateway:
            def __init__(self,features):self.features=features;self.prompts=[]
            def complete(self,system,prompt):
                self.prompts.append(prompt)
                return {'features':self.features},{'model':'fake-no-network'}
        gateway=FakeGateway(r['features'])
        review=create_review(b,{},gateway)
        self.assertEqual(len(gateway.prompts),1)
        self.assertIn('TAIL_FULL_SOURCE',gateway.prompts[0])
        self.assertEqual(review['source_fingerprint'],source_fingerprint(b))
        self.assertEqual(review['approval_status'],'pending_operator_review')
        bad=deepcopy(r['features']);bad['selling_points'][0]['evidence_part_ids']=['foreign']
        with self.assertRaises(ValueError):create_review(b,{},FakeGateway(bad))


if __name__=='__main__':unittest.main()
