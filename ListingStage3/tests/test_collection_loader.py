"""双集合读取适配：验证真实读取结果的版本映射、组件顺序和启用状态。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ListingStage2'/'src'))
from listing_stage3.library import load_collections


class CollectionLoaderTests(unittest.TestCase):
    def test_parent_hydration_preserves_declared_component_order(self):
        meta={'model':'test','model_digest':'digest','recipe':'reviewed-structured-whole-v5','dimensions':2}
        identity=dict(country_code='US',site_id='amazon',category_id='toppers',product_id='P',snapshot_id='S')
        whole={'id':'whole-id','vector':[1.,0.],'payload':{'listing_version_id':'v','identity':identity,
            'embedding_meta':meta,'component_ids':['second','first'],'overall_features':{'product_form':'foam'},'structured_features':{}}}
        parts=[]
        for pid,enabled in [('first',True),('second',False)]:
            parts.append({'id':pid,'vector':[0.,1.],'payload':{'part_id':pid,'listing_version_id':'v','parent_listing_version_id':'v',
                'embedding_meta':{**meta,'recipe':'component-semantic-text-v1'},
                'controls':{'enabled':True,'retrieve':enabled,'generation_reference':True}}})
        manifest={'dataset_id':'dataset','storage':{'path':'local-db'},'records':{'whole':'wholes.jsonl'},'record_sha256':{'whole':'hash'}}
        with patch('listing_stage2.collection_store.read_dataset',return_value=(manifest,[whole],parts)):
            records,inventory=load_collections(Path('D:/example/library_index.json'))
        record=records[0]
        self.assertEqual([p['part_id'] for p in record['components']],['second','first'])
        self.assertFalse(record['components'][0]['index_enabled'])
        self.assertTrue(record['components'][1]['index_enabled'])
        self.assertEqual(record['overall_embedding']['vector'],[1.,0.])
        self.assertEqual(record['library_source']['whole_point_id'],'whole-id')
        self.assertEqual(inventory['storage'],'qdrant_local')


if __name__=='__main__':unittest.main()
