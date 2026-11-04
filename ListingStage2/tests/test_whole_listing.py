# 文件用途：测试模块：test_whole_listing，所有远程调用均由模拟对象替代，不使用真实API密钥。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import copy
import json
import unittest
from pathlib import Path
from test_listing_bundles import Encoder
from listing_stage2.rank1_experiment import REVIEW,source_bundle
from listing_stage2.whole_listing import build as build_current,input_fingerprint

def build(*args,**kwargs):
    """本文件保留历史v3独立摘要配方的回归；v4见test_whole_document。"""
    return build_current(*args,**kwargs,full_evidence=False)


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class WholeListingTests(unittest.TestCase):
    # 功能及输出：验证：关闭组件编码仍保留整体向量；断言失败即表示回归问题。
    def test_component_encoding_can_be_disabled_without_changing_whole(self):
        result=build(self.bundle,self.review,Encoder(),component_ids=set())
        self.assertTrue(result['embedding']['vector'])
        self.assertFalse(any('embedding' in p for p in result['parts']))

    @classmethod
    # 功能及输出：为整组测试读取公共样本/审阅数据；避免每个测试重复构建。
    def setUpClass(cls):
        cls.review=json.loads(REVIEW.read_text(encoding='utf-8'))
        cls.bundle=source_bundle(cls.review)

    # 功能及输出：验证：整体与组件分别编码；断言失败即表示回归问题。
    def test_two_independent_levels(self):
        result=build(self.bundle,self.review,Encoder())
        self.assertEqual(len(result['parts']),18)
        self.assertEqual(result['embedding']['vector'],Encoder().encode(self.review['overall_features']['embedding_text_en']).tolist())
        self.assertTrue(all(p['embedding_status']=='ready' for p in result['parts']))
        self.assertEqual(sum(p['role']=='video' for p in result['parts']),1)
        self.assertNotIn('weights',result)

    # 功能及输出：验证：来源改变必须重新审阅；断言失败即表示回归问题。
    def test_source_change_requires_new_review(self):
        b=copy.deepcopy(self.bundle)
        b['parts'][0]['features']['new_observation']='changed'
        with self.assertRaises(ValueError):build(b,self.review,Encoder())

    # 功能及输出：验证：整体叙述变化更新向量及版本；断言失败即表示回归问题。
    def test_summary_changes_whole_vector_and_version(self):
        review=copy.deepcopy(self.review)
        review['overall_features']['embedding_text_en']='A completely different whole Listing narrative'
        a=build(self.bundle,self.review,Encoder());b=build(self.bundle,review,Encoder())
        self.assertNotEqual(a['bundle_id'],b['bundle_id'])
        self.assertNotEqual(a['embedding']['vector'],b['embedding']['vector'])
        self.assertEqual(a['parts'][0]['embedding'],b['parts'][0]['embedding'])

    # 功能及输出：验证：拒绝不属于当前包的卖点证据；断言失败即表示回归问题。
    def test_foreign_evidence_is_rejected(self):
        review=copy.deepcopy(self.review)
        review['overall_features']['selling_points'][0]['evidence_part_ids']=['foreign-part']
        with self.assertRaises(ValueError):build(self.bundle,review,Encoder())

if __name__=='__main__':unittest.main()
