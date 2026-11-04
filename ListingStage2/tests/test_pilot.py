# 文件用途：测试模块：test_pilot，所有远程调用均由模拟对象替代，不使用真实API密钥。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import unittest, copy
from listing_stage2.phase1_reader import load
from listing_stage2.contracts import validate
from listing_stage2.clustering import group
from listing_stage2.scoring import assess

# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class PilotTest(unittest.TestCase):
    @classmethod
    # 功能及输出：为整组测试读取公共样本/审阅数据；避免每个测试重复构建。
    def setUpClass(cls): cls.payload=load()
    # 功能及输出：验证：拒绝重复ID；断言失败即表示回归问题。
    def test_duplicate_rejected(self):
        p=copy.deepcopy(self.payload);p['features'].append(p['features'][0])
        with self.assertRaises(ValueError): validate(p)
    # 功能及输出：验证：拒绝错误向量；断言失败即表示回归问题。
    def test_bad_vector_rejected(self):
        p=copy.deepcopy(self.payload);p['embeddings'][0]['vector'][0]=float('nan')
        with self.assertRaises(ValueError): validate(p)
    # 功能及输出：验证：质量评分不依赖排名；断言失败即表示回归问题。
    def test_rank_independence(self):
        p=copy.deepcopy(self.payload)
        for ref in p['references']: ref['source_metadata']['ranking_position']=999
        self.assertEqual(group(p),group(self.payload))
        self.assertTrue(all(x['total_score'] is None for x in assess(p)))
    # 功能及输出：验证：聚类覆盖全部待分组图片；断言失败即表示回归问题。
    def test_complete_cluster_coverage(self):
        actual=[m['feature_id'] for g in group(self.payload) for m in g['members']]
        expected=[f['feature_id'] for f in self.payload['features'] if f['image_reference_id']]
        self.assertEqual(sorted(actual),sorted(expected))
        self.assertEqual(len(actual),len(set(actual)))
if __name__=='__main__': unittest.main()
