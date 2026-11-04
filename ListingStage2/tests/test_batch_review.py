"""批量审阅的绑定回归：换商品、快照或原件后不得套用旧审阅，不访问模型。"""
from copy import deepcopy
import unittest
from listing_stage2.batch_review import signature


class BatchReviewTests(unittest.TestCase):
    """使用最小真实字段结构验证审阅身份与证据边界。"""
    def setUp(self):
        self.bundle={'identity':{'product_id':'a','snapshot_id':'s'},'parts':[{'part_id':'p','role':'main_image','source_text':None,'asset':{'asset_sha256':'one','local_path':'one.jpg'},'reference':{'snapshot_id':'s'},'module_placements':[]}]}

    def test_another_product_or_snapshot_invalidates_review(self):
        for field in ['product_id','snapshot_id']:
            changed=deepcopy(self.bundle);changed['identity'][field]='another'
            self.assertNotEqual(signature(changed),signature(self.bundle))

    def test_changed_image_or_text_invalidates_review(self):
        changed=deepcopy(self.bundle);changed['parts'][0]['asset']['asset_sha256']='two'
        self.assertNotEqual(signature(changed),signature(self.bundle))
        changed=deepcopy(self.bundle);changed['parts'][0]['source_text']='different'
        self.assertNotEqual(signature(changed),signature(self.bundle))

    def test_source_binding_and_component_order_are_bound(self):
        changed=deepcopy(self.bundle);changed['parts'][0]['reference']['snapshot_id']='other'
        self.assertNotEqual(signature(changed),signature(self.bundle))
        changed=deepcopy(self.bundle);changed['parts'].append({**changed['parts'][0],'part_id':'second'})
        a=signature(changed);changed['parts'].reverse()
        self.assertNotEqual(a,signature(changed))


if __name__=='__main__':unittest.main()
