# 文件用途：测试模块：test_reference_library，所有远程调用均由模拟对象替代，不使用真实API密钥。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import copy
import tempfile
import unittest
from pathlib import Path
from listing_stage2.reference_library import compile_listing, export_library, validate_recipe


# 功能及输出：生成独立测试样本，供校验和异常分支断言使用。
def bundle():
    e={'model':'test','model_digest':'test-digest','recipe':'whole-v3','dimensions':2,'vector':[1.,0.], 'derived_from':'explicit_reviewed_whole_listing_narrative'}
    return {'schema_version':3,'bundle_id':'version-one','identity':dict(country_code='US',site_id='amazon',category_id='toppers',product_id='P1',snapshot_id='S1'),
            'embedding':e,'overall_features':{'selling_points':[{'evidence_part_ids':['main']} ]},
            'parts':[{'part_id':'main','role':'main','features':{},'embedding':{**e,'recipe':'part-v1'}}]}


# 功能及输出：生成独立测试样本，供校验和异常分支断言使用。
def recipe():
    return dict(recipe_id='main-composition',version='1',listing_version_id='version-one',reference_part_ids=['main'],
                reference_roles={'main':'expression_reference'},goal='product composition',template='Use own product photo',
                variables=['own_product_photo'],product_constraints=['keep real structure'],acceptance_checks=['identity'],
                applicability={'category':'toppers'},status='draft',validation_trials=[])


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class ReferenceLibraryTests(unittest.TestCase):
    # 功能及输出：验证：单独关闭检索不使整体失效；断言失败即表示回归问题。
    def test_retrieval_only_does_not_invalidate_whole(self):
        policy={'schema_version':1,'listings':{'version-one':{'main':{'retrieve':False}}}}
        with tempfile.TemporaryDirectory() as d:
            x=export_library([bundle()],d,policy=policy)
            self.assertEqual(len(x['whole_index']),1)
            self.assertEqual(len(x['component_index']),0)

    # 功能及输出：验证：关闭组件编码不改变整体依据；断言失败即表示回归问题。
    def test_embedding_disabled_does_not_change_overall_basis(self):
        p={'schema_version':1,'roles':{'main':{'embed':False}}}
        r=compile_listing(bundle(),policy=p)
        self.assertNotIn('embedding',r['components'][0])
        self.assertFalse(r['components'][0]['controls']['retrieve'])
        self.assertEqual(r['overall_status'],'source_review_unchanged')

    # 功能及输出：验证：移除整体依据后暂停索引与相关模板；断言失败即表示回归问题。
    def test_overall_removal_blocks_indexes_and_recipe(self):
        p={'schema_version':1,'roles':{'main':{'enabled':False}}}
        r=compile_listing(bundle(),[recipe()],p)
        self.assertEqual(len(r['components']),1)
        self.assertEqual(r['overall_status'],'requires_review_and_reencode')
        self.assertEqual(r['generation_recipes'][0]['blocked_part_ids'],['main'])
        with tempfile.TemporaryDirectory() as d:
            x=export_library([bundle()],d,[recipe()],p)
            self.assertEqual(x['whole_index'],[])
            self.assertEqual(x['component_index'],[])

    # 功能及输出：验证：单项覆盖和类型数量限制；断言失败即表示回归问题。
    def test_component_override_and_role_limit(self):
        b=bundle();p=copy.deepcopy(b['parts'][0]);p['part_id']='main2';b['parts'].append(p)
        config={'schema_version':1,'roles':{'main':{'retrieve':False,'max_components':1}},
                'listings':{'version-one':{'main':{'retrieve':True}}}}
        r=compile_listing(b,policy=config)
        self.assertTrue(r['components'][0]['controls']['retrieve'])
        self.assertFalse(r['components'][1]['controls']['enabled'])

    # 功能及输出：验证：拒绝未知版本组件和非法配置；断言失败即表示回归问题。
    def test_unknown_scope_and_invalid_flag_are_rejected(self):
        for policy in [
            {'schema_version':1,'listings':{'foreign':{}}},
            {'schema_version':1,'listings':{'version-one':{'foreign':{}}}},
            {'schema_version':1,'defaults':{'retrieve':'false'}},
            {'schema_version':1,'roles':{'main':{'max_components':-1}}}]:
            with self.assertRaises(ValueError):export_library([bundle()],'.',policy=policy)

    # 功能及输出：验证：策略变更保留历史投影；断言失败即表示回归问题。
    def test_policy_revision_keeps_old_projection(self):
        with tempfile.TemporaryDirectory() as d:
            a=export_library([bundle()],d)
            b=export_library([bundle()],d,policy={'schema_version':1,'defaults':{'retrieve':False}})
            self.assertNotEqual(a['records'],b['records'])
            self.assertTrue((Path(d)/a['records'][0]).is_file())
            self.assertTrue((Path(d)/b['records'][0]).is_file())

    # 功能及输出：验证：整体与组件检索空间分开；断言失败即表示回归问题。
    def test_whole_and_part_are_separate_spaces(self):
        r=compile_listing(bundle(),[recipe()])
        self.assertNotEqual(r['overall_embedding']['index_space_id'],r['components'][0]['embedding']['index_space_id'])
        self.assertEqual(r['components'][0]['listing_version_id'],'version-one')

    # 功能及输出：验证：拒绝外来证据或旧版本；断言失败即表示回归问题。
    def test_wrong_evidence_and_version_rejected(self):
        b=bundle();b['overall_features']['selling_points'][0]['evidence_part_ids']=['foreign']
        with self.assertRaises(ValueError):compile_listing(b)
        r=recipe();r['listing_version_id']='stale-version'
        with self.assertRaises(ValueError):validate_recipe(r,bundle())
        r=recipe();r['reference_part_ids']=['foreign']
        with self.assertRaises(ValueError):validate_recipe(r,bundle())

    # 功能及输出：验证：未验证或失败试验不得晋升validated；断言失败即表示回归问题。
    def test_cannot_promote_unverified_trials(self):
        r=recipe();r['status']='validated'
        with self.assertRaises(ValueError):validate_recipe(r,bundle())
        r.update(validation_scope='same model and prompt',review_record={'approved_version':'1'})
        r['validation_trials']=[dict(trial_id=str(i),prompt_sha256='p',reference_sha256=['a'],model='m',output_sha256='o'+str(i),check_results={'identity':'unverified'},reviewer='human') for i in range(3)]
        with self.assertRaises(ValueError):validate_recipe(r,bundle())
        for t in r['validation_trials']:t['check_results']['identity']='pass'
        self.assertEqual(validate_recipe(r,bundle())['status'],'validated')

    # 功能及输出：验证：无效批次不写结果；断言失败即表示回归问题。
    def test_invalid_batch_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            b=bundle();b['identity']['category_id']='../escape'
            with self.assertRaises(ValueError):export_library([bundle(),b],d)
            self.assertFalse(list(Path(d).rglob('*')))

    # 功能及输出：验证：导出保留原始记录与元数据；断言失败即表示回归问题。
    def test_export_preserves_original_and_metadata(self):
        b=bundle();original=copy.deepcopy(b)
        with tempfile.TemporaryDirectory() as d:
            x=export_library([b],d,[recipe()])
            self.assertEqual(len(x['whole_index']),1)
            self.assertEqual(len(x['component_index']),1)
            self.assertTrue((Path(d)/x['records'][0]).is_file())
            self.assertEqual(b,original)

    # 功能及输出：验证：拒绝非有限向量；断言失败即表示回归问题。
    def test_bad_vector_is_rejected(self):
        b=bundle();b['parts'][0]['embedding']['vector']=[float('nan'),0.]
        with self.assertRaises(ValueError):compile_listing(b)


if __name__=='__main__':unittest.main()
