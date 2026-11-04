# 文件用途：测试模块：test_listing_bundles，所有远程调用均由模拟对象替代，不使用真实API密钥。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import copy
import hashlib
import json
import unittest
from pathlib import Path
import numpy as np
from listing_stage2.phase1_reader import load
from listing_stage2.listing_bundles import assemble, encode_bundle, match, select_parts


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class Encoder:
    model='test'
    digest='fixed-test-model'
    # 功能及输出：测试编码器：从输入文本确定性构建向量；用于断言，不调用真实模型。
    def encode(self,text,query=False):
        values=np.frombuffer(hashlib.sha256(text.encode()).digest(),dtype=np.uint8).astype(float)+1
        return values/np.linalg.norm(values)


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class ListingTests(unittest.TestCase):
    @classmethod
    # 功能及输出：为整组测试读取公共样本/审阅数据；避免每个测试重复构建。
    def setUpClass(cls):
        cls.payload=load()
        cls.report=json.loads(Path(cls.payload['provenance']['source_report']).read_text(encoding='utf-8'))
        cls.bundles=assemble(cls.payload,cls.report)

    # 功能及输出：验证：一快照一整体并保留组件；断言失败即表示回归问题。
    def test_one_listing_per_snapshot_and_parts_preserved(self):
        self.assertEqual(len(self.bundles),5)
        self.assertEqual(sum(len(b['parts']) for b in self.bundles),107)
        for b in self.bundles:
            self.assertTrue(any(p['role']=='main_image' for p in b['parts']))
            self.assertTrue(any(p['role']=='bullet' for p in b['parts']))
            self.assertEqual(b['identity']['site_id'],'amazon')
            self.assertEqual(b['identity']['category_id'],'toppers')

    # 功能及输出：验证：排名变化不改变内容向量；断言失败即表示回归问题。
    def test_ranking_does_not_change_aggregate(self):
        other=copy.deepcopy(self.report)
        for p in other['products']:p['listing_rank']=999
        self.assertEqual([b['bundle_id'] for b in assemble(self.payload,other)],[b['bundle_id'] for b in self.bundles])

    # 功能及输出：验证：内容变化使版本与向量变化；断言失败即表示回归问题。
    def test_part_change_invalidates_bundle_and_vector(self):
        p=copy.deepcopy(self.payload)
        image=next(f for f in p['features'] if f['entity_kind']=='image' and f['features']['identity_scope']=='current_or_family')
        image['features']['semantic_description_en']='new hand pressing soft foam scene'
        changed=assemble(p,self.report)
        self.assertNotEqual(changed[0]['bundle_id'],self.bundles[0]['bundle_id'])
        a=encode_bundle(self.bundles[0],Encoder())
        b=encode_bundle(changed[0],Encoder())
        self.assertFalse(np.allclose(a['embedding']['vector'],b['embedding']['vector']))
        self.assertAlmostEqual(np.linalg.norm(a['embedding']['vector']),1)

    # 功能及输出：验证：整体检索过滤及排序；断言失败即表示回归问题。
    def test_search_returns_whole_bundle_and_filters(self):
        b=encode_bundle(self.bundles[0],Encoder())
        self.assertEqual(match([b],'soft',Encoder(),'US','toppers'),[])
        result=match([b],'soft',Encoder(),'US','toppers',include_pending=True)
        self.assertEqual(len(result[0]['parts']),len(b['parts']))
        self.assertEqual(match([b],'soft',Encoder(),'DE','toppers',include_pending=True),[])
        wrong=Encoder();wrong.digest='another-model'
        with self.assertRaises(ValueError):match([b],'soft',wrong,'US','toppers',include_pending=True)

    # 功能及输出：验证：跨Listing选组件仍保留来源；断言失败即表示回归问题。
    def test_cross_listing_selection_retains_sources(self):
        selections=[{'bundle_id':b['bundle_id'],'part_id':b['parts'][0]['part_id'],'planned_use':use} for b,use in zip(self.bundles,['main_image','bullet'])]
        result=select_parts(self.bundles,selections)
        self.assertEqual(len(result['selections']),2)
        self.assertNotEqual(result['selections'][0]['identity']['product_id'],result['selections'][1]['identity']['product_id'])
        self.assertEqual(result['status'],'draft_pending_review')

if __name__=='__main__':unittest.main()
