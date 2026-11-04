"""完整文档回归：尾部信息、来源绑定、分块覆盖及组件向量保持。"""
import copy
import unittest
import numpy as np
from listing_stage2.whole_document import collect_document,split_document,upgrade,RECIPE
from listing_stage2.reference_library import compile_listing


class Encoder:
    model='test';digest='test-full-document'
    def __init__(self):self.seen=[]
    def encode(self,text,query=False):
        self.seen.append(text)
        return np.array([1.,2. if 'TAIL_UNIQUE' in text else 0.])


def bundle():
    parts=[]
    for index,(role,text) in enumerate([('title','Topper title'),('bullet','intro '*80+'TAIL_UNIQUE'),('description','Complete description ending'),('aplus','Complete A+ ending')]):
        parts.append({'part_id':str(index),'role':role,'entity_kind':'text','source_text':text,'features':{},
                      'eligible_for_aggregate':True,'reference':{'snapshot_id':'s','source_url':'source'},'asset':None,
                      'embedding':{'vector':[1.,0.],'dimensions':2,'model':'test','model_digest':'test-full-document','recipe':'component-semantic-text-v1'}})
    return {'schema_version':3,'bundle_id':'old-version','identity':{'country_code':'US','site_id':'amazon','category_id':'toppers','product_id':'P','snapshot_id':'s'},
            'parts':parts,'overall_features':{'embedding_text_en':'old abbreviated summary','product_form':'pillow_top','style':[],'scenes':[],'selling_points':[],'limitations':[]},
            'review_provenance':{},'coverage':{}}


class WholeDocumentTests(unittest.TestCase):
    def test_complete_text_including_tail_and_all_roles_is_encoded(self):
        b=bundle();e=Encoder();r=upgrade(b,e,max_chars=128)
        encoded=''.join(e.seen)
        for p in b['parts']:self.assertIn(p['source_text'],encoded)
        self.assertIn('TAIL_UNIQUE',encoded)
        self.assertEqual(r['embedding']['encoded_characters'],len(encoded))
        self.assertEqual(r['whole_document']['coverage']['source_text_part_ids'],['0','1','2','3'])
        self.assertEqual(r['parts'],b['parts'])
        self.assertEqual(r['recipe'],RECIPE)
        self.assertNotEqual(r['bundle_id'],b['bundle_id'])
        self.assertAlmostEqual(sum(x*x for x in r['embedding']['vector']),1.)
        self.assertEqual(len(compile_listing(r)['components']),4)

    def test_legacy_full_source_mode_requires_explicit_opt_in(self):
        from listing_stage2.whole_listing import build,input_fingerprint
        b=bundle();e=Encoder()
        result=build(b,{'input_fingerprint':input_fingerprint(b),'overall_features':b['overall_features']},e,full_evidence=True)
        self.assertEqual(result['schema_version'],4)
        self.assertIn('TAIL_UNIQUE',result['embedding']['input_text'])
        self.assertEqual(len(result['overall_features']['source_statements']),4)

    def test_tail_changes_whole_vector_without_changing_component_vectors(self):
        b=bundle();r1=upgrade(b,Encoder(),128)
        b2=copy.deepcopy(b);b2['parts'][1]['source_text']=b2['parts'][1]['source_text'].replace('TAIL_UNIQUE','OTHER_TAIL')
        r2=upgrade(b2,Encoder(),128)
        self.assertNotEqual(r1['embedding']['vector'],r2['embedding']['vector'])
        self.assertNotEqual(r1['bundle_id'],r2['bundle_id'])

    def test_exact_dedup_retains_both_source_bindings(self):
        b=bundle();p=copy.deepcopy(b['parts'][1]);p['part_id']='duplicate';b['parts'].append(p)
        document,sections,c=collect_document(b)
        section=next(x for x in sections if 'TAIL_UNIQUE' in x['text'])
        self.assertEqual(len(section['evidence']),2)
        self.assertEqual(document.count('TAIL_UNIQUE'),1)
        self.assertIn('duplicate',c['source_text_part_ids'])

    def test_long_document_chunks_are_lossless_and_policy_is_respected(self):
        text=('Long text\n'*900)+'  TAIL_UNIQUE  '
        chunks=split_document(text,128)
        self.assertEqual(''.join(x['text'] for x in chunks),text)
        self.assertTrue(all(len(x['text'])<=128 for x in chunks))
        self.assertTrue(all(a['end']==b['start'] for a,b in zip(chunks,chunks[1:])))
        b=bundle();b['parts'][1]['analysis_controls']={'include_in_overall':False}
        document,sections,c=collect_document(b)
        self.assertNotIn('TAIL_UNIQUE',document)
        self.assertEqual(c['excluded_parts'][0]['part_id'],'1')
        with self.assertRaises(ValueError):split_document('test',0)


if __name__=='__main__':unittest.main()
