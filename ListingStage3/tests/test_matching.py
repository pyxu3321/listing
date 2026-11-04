"""第三阶段离线回归：使用二维固定向量，不访问真实模型或网站。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from listing_stage3.library import load
from listing_stage3.matcher import match


class Encoder:
    """固定测试编码器，只验证排序与过滤逻辑。"""
    digest='test-model'
    def encode(self,text,query=False):return [1.,0.]


def record(version='one',vector=None):
    """构造一套包含两个图组件的已分析测试记录。"""
    e={'model':'test','model_digest':'test-model','recipe':'reviewed-whole-listing-summary-v3','dimensions':2,'vector':vector or [1.,0.]}
    parts=[{'part_id':version+'-'+role,'listing_version_id':version,'role':role,'features':{'semantic_description_en':'soft touch'},
            'embedding':{**e,'recipe':'component-semantic-text-v1'},'asset':{'local_path':'not-present.jpg'},
            'identity_scope':'current_or_family','controls':{'retrieve':True,'generation_reference':True,'enabled':True},'index_enabled':True} for role in ('main_image','gallery')]
    return {'schema':'listing-reference-library-v1.1','listing_version_id':version,'identity':{'country_code':'US','site_id':'amazon','category_id':'toppers','product_id':version,'snapshot_id':'s'},
            'overall_embedding':e,'overall_features':{'product_form':'foam'},'components':parts,
            'approval_status':'pending_operator_review','library_source':{'record':'test'},'generation_recipes':[]}


REQUEST={'country_code':'US','category_id':'toppers','product_description':'foam topper','selling_points':['soft'],
         'reference_needs':[{'role':'gallery','purpose':'soft touch'}]}
SETTINGS={'whole_top_k':5,'components_per_need':3,'minimum_similarity':.25,'include_pending':True,'match_components':True}


class MatchTests(unittest.TestCase):
    def test_selling_points_only_has_no_added_product_context(self):
        from listing_stage3.matcher import request_query
        request={'selling_points':['soft','lightweight']}
        self.assertEqual(request_query(request),'soft; lightweight')
        result=match(request,[record()],{**SETTINGS,'match_components':False},Encoder())
        self.assertEqual(result['product_query'],'soft; lightweight')
        self.assertIsNone(result['search_scope']['country_code'])
        self.assertEqual(len(result['whole_candidates']),1)

    def test_optional_metadata_does_not_impose_default_country_or_category(self):
        a=record('foreign');a['identity'].update(country_code='UK',category_id='pillows')
        q={'selling_points':['soft'],'country_code':None,'category_id':' ','product_description':''}
        self.assertEqual(len(match(q,[a],SETTINGS,Encoder())['whole_candidates']),1)
        self.assertEqual(match({**q,'country_code':'US'},[a],SETTINGS,Encoder())['whole_candidates'],[])

    def test_blank_query_rejected_before_encoding(self):
        class NoCall(Encoder):
            def encode(self,*args,**kwargs):raise AssertionError('Should not encode an empty query')
        for q in [{},{'selling_points':[]},{'country_code':'US','selling_points':[' ']},{'style':'bright'}]:
            with self.assertRaises(ValueError):match(q,[],SETTINGS,NoCall())

    def test_whole_first_limits_component_scope(self):
        a=record('a');b=record('b',[.8,.6]);s={**SETTINGS,'whole_top_k':1}
        r=match(REQUEST,[a,b],s,Encoder())
        self.assertEqual(len(r['whole_candidates']),1)
        self.assertTrue(all(x['listing_version_id']=='a' for x in r['reference_needs'][0]['candidates']))

    def test_disabled_references_are_not_selected(self):
        for key in ('retrieve','generation_reference','enabled'):
            a=record();a['components'][1]['controls'][key]=False
            self.assertEqual(match(REQUEST,[a],SETTINGS,Encoder())['reference_needs'][0]['candidates'],[])

    def test_country_and_form_are_hard_filters(self):
        for request in [{**REQUEST,'country_code':'UK'},{**REQUEST,'product_form':'pillow_top'}]:
            self.assertEqual(match(request,[record()],SETTINGS,Encoder())['status'],'no_whole_match')

    def test_pending_is_explicit_opt_in(self):
        self.assertEqual(match(REQUEST,[record()],{**SETTINGS,'include_pending':False},Encoder())['whole_candidates'],[])

    def test_no_forced_match_and_missing_own_facts(self):
        result=match(REQUEST,[record(vector=[0.,1.])],SETTINGS,Encoder())
        self.assertEqual(result['whole_candidates'],[])
        self.assertEqual(len(result['missing_generation_inputs']),2)
        self.assertFalse(result['generation_ready'])

    def test_model_mismatch_fails_instead_of_mixing(self):
        a=record();a['overall_embedding']['model_digest']='different'
        with self.assertRaises(ValueError):match(REQUEST,[a],SETTINGS,Encoder())

    def test_related_product_image_not_used(self):
        a=record();a['components'][1]['identity_scope']='related_product'
        self.assertEqual(match(REQUEST,[a],SETTINGS,Encoder())['reference_needs'][0]['candidates'],[])

    def test_request_list_types_are_checked(self):
        with self.assertRaises(ValueError):match({**REQUEST,'retrieval_terms':'bad'},[],SETTINGS,Encoder())

    def test_aplus_image_need_does_not_return_text_component(self):
        a=record();image=a['components'][1];image.update(role='aplus',entity_kind='image')
        text=deepcopy(image);text.update(part_id='aplus-faq',entity_kind='text',asset=None)
        a['components'].append(text)
        request={**REQUEST,'reference_needs':[{'role':'aplus','purpose':'bright bedroom','entity_kind':'image'}]}
        items=match(request,[a],SETTINGS,Encoder())['reference_needs'][0]['candidates']
        self.assertEqual([x['part_id'] for x in items],[image['part_id']])
        with self.assertRaises(ValueError):
            match({**request,'reference_needs':[{'role':'aplus','purpose':'x','entity_kind':'audio'}]},[a],SETTINGS,Encoder())

    def test_preferred_theme_reranks_without_replacing_cosine_score(self):
        a=record();generic=a['components'][1];generic['features']['themes']=['bedroom']
        touch=deepcopy(generic);touch['part_id']='touch';touch['features']['themes']=['hand press']
        touch['embedding']['vector']=[.95,(1-.95**2)**.5]
        a['components'].append(touch)
        request={**REQUEST,'reference_needs':[{'role':'gallery','purpose':'soft touch','preferred_themes':['hand press']}]}
        items=match(request,[a],SETTINGS,Encoder())['reference_needs'][0]['candidates']
        self.assertEqual(items[0]['part_id'],'touch')
        self.assertEqual(items[0]['similarity'],.95)
        self.assertEqual(items[0]['theme_matches'],['hand press'])
        # 相似度阈值是硬门槛，不能被标签得分挽救。
        items=match(request,[a],{**SETTINGS,'minimum_similarity':.99},Encoder())['reference_needs'][0]['candidates']
        self.assertEqual([x['part_id'] for x in items],[generic['part_id']])

    def test_unreadable_own_image_and_bad_pending_flag(self):
        result=match({**REQUEST,'own_images':['does-not-exist.jpg']},[record()],SETTINGS,Encoder())
        self.assertIn('自有产品图片路径不可读取',result['missing_generation_inputs'])
        with self.assertRaises(ValueError):match(REQUEST,[record()],{**SETTINGS,'include_pending':'false'},Encoder())

    def test_style_can_promote_listing_but_cannot_bypass_product_threshold(self):
        class SplitEncoder(Encoder):
            def encode(self,text,query=False):return [0.,1.] if text=='dark hotel' else [1.,0.]
        a=record('product-best');b=record('style-best',[.8,.6]);bad=record('unrelated',[0.,1.])
        for r,v in [(a,[1.,0.]),(b,[0.,1.]),(bad,[0.,1.])]:
            for p in r['components']:p['entity_kind']='image';p['embedding']['vector']=v
        result=match({**REQUEST,'style':'dark hotel'},[a,b,bad],SETTINGS,SplitEncoder())
        top=result['whole_candidates'][0]
        self.assertEqual(top['listing_version_id'],'style-best')
        self.assertEqual(top['product_similarity'],.8)
        self.assertEqual(top['style_similarity'],1.)
        self.assertAlmostEqual(top['relevance_score'],.87)
        self.assertEqual(len(top['style_evidence']),2)
        self.assertNotIn('unrelated',[x['listing_version_id'] for x in result['whole_candidates']])
        self.assertNotIn('dark hotel',result['product_query'])

    def test_style_missing_and_disabled_images_do_not_fabricate_score(self):
        a=record()
        for p in a['components']:p['entity_kind']='image';p['controls']['enabled']=False
        top=match({**REQUEST,'style':'dark hotel'},[a],SETTINGS,Encoder())['whole_candidates'][0]
        self.assertIsNone(top['style_similarity'])
        self.assertEqual(top['style_status'],'no_eligible_images')
        self.assertEqual(top['weights'],{'product':1.,'style':0.})
        self.assertEqual(top['style_evidence'],[])
        self.assertEqual(match(REQUEST,[record()],SETTINGS,Encoder())['whole_candidates'][0]['style_status'],'not_requested')

    def test_invalid_score_settings_are_rejected(self):
        for extra in [{'whole_score_weights':{'product':-1,'style':2}},
                      {'whole_score_weights':{'product':1,'style':float('nan')}},
                      {'style_evidence_top_n':0}]:
            with self.assertRaises(ValueError):match(REQUEST,[],{**SETTINGS,**extra},Encoder())

    def test_close_scores_use_capture_rank_without_changing_selection(self):
        items=[]
        for rank,score in [(1,.6372),(41,.627661),(5,.62239),(2,.61)]:
            r=record(str(rank),[score,(1-score**2)**.5]);r['overall_features']['historical_rank']=rank;items.append(r)
        result=match(REQUEST,items,{**SETTINGS,'whole_top_k':3},Encoder())
        self.assertEqual([x['overall_features']['historical_rank'] for x in result['whole_candidates']],[1,5,41])
        self.assertEqual([x['similarity'] for x in result['whole_candidates']],[.6372,.62239,.627661])
        exact=match(REQUEST,items,{**SETTINGS,'whole_top_k':3,'rank_tiebreak_tolerance':0},Encoder())
        self.assertEqual([x['overall_features']['historical_rank'] for x in exact['whole_candidates']],[1,41,5])

    def test_rank_group_does_not_chain_or_cross_large_score_gap(self):
        items=[]
        for rank,score in [(40,.9),(30,.885),(1,.87)]:
            r=record(str(rank),[score,(1-score**2)**.5]);r['overall_features']['historical_rank']=rank;items.append(r)
        result=match(REQUEST,items,SETTINGS,Encoder())
        self.assertEqual([x['overall_features']['historical_rank'] for x in result['whole_candidates']],[30,40,1])

    def test_deferred_components_are_empty_and_reference_needs_optional(self):
        q={k:v for k,v in REQUEST.items() if k!='reference_needs'}
        settings={k:v for k,v in SETTINGS.items() if k!='match_components'}
        result=match(q,[record()],settings,Encoder())
        self.assertEqual(len(result['whole_candidates']),1)
        self.assertEqual(result['reference_needs'],[])
        self.assertEqual(result['component_matching']['status'],'deferred_to_generation_planning')
        self.assertFalse(result['generation_ready'])
        for extra in [{'rank_tiebreak_tolerance':-1},{'rank_tiebreak_tolerance':float('nan')},{'match_components':'no'}]:
            with self.assertRaises(ValueError):match(q,[],{**settings,**extra},Encoder())

    def test_capture_rank_unknown_and_cross_site_do_not_override_relevance(self):
        a=record('a');b=record('b',[.99,(1-.99**2)**.5]);b['overall_features']['historical_rank']=1
        result=match(REQUEST,[a,b],SETTINGS,Encoder())
        self.assertEqual(result['whole_candidates'][0]['identity']['product_id'],'b')
        b['identity']['site_id']='independent'
        result=match(REQUEST,[a,b],SETTINGS,Encoder())
        self.assertEqual(result['whole_candidates'][0]['identity']['product_id'],'a')

    def test_full_evidence_whole_recipe_is_supported_but_not_mixed(self):
        a=record('full');a['overall_embedding']['recipe']='whole-listing-full-evidence-v4'
        result=match(REQUEST,[a],SETTINGS,Encoder())
        self.assertEqual(result['whole_candidates'][0]['listing_version_id'],'full')
        with self.assertRaises(ValueError):match(REQUEST,[a,record('legacy')],SETTINGS,Encoder())

    def test_library_paths_and_index_integrity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);r=record();r.pop('library_source')
            (root/'record.json').write_text(json.dumps(r))
            idx={'schema':'listing-reference-library-v1.1','whole_index':[{'record_path':'record.json','metadata':{'listing_version_id':'one'},'embedding':r['overall_embedding']}],
                 'component_index':[{'record_path':'record.json','part_id':p['part_id']} for p in r['components']]}
            (root/'index.json').write_text(json.dumps(idx))
            loaded,_=load([root/'index.json']);self.assertEqual(len(loaded),1)
            idx['whole_index'][0]['record_path']='../escape.json';(root/'index.json').write_text(json.dumps(idx))
            with self.assertRaises(ValueError):load([root/'index.json'])

    def test_first_projection_wins_without_reenabling_parts(self):
        with tempfile.TemporaryDirectory() as d:
            paths=[]
            for n,active in enumerate([False,True]):
                folder=Path(d)/str(n);folder.mkdir();r=record()
                (folder/'r.json').write_text(json.dumps(r))
                idx={'schema':r['schema'],'whole_index':[{'record_path':'r.json','metadata':{'listing_version_id':'one'},'embedding':r['overall_embedding']}],
                     'component_index':[{'record_path':'r.json','part_id':p['part_id']} for p in r['components']] if active else []}
                (folder/'i.json').write_text(json.dumps(idx));paths.append(folder/'i.json')
            records,_=load(paths)
            self.assertEqual(len(records),1)
            self.assertFalse(any(p['index_enabled'] for p in records[0]['components']))


if __name__=='__main__':unittest.main()
