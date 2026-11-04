# 文件用途：测试模块：test_api_analysis，所有远程调用均由模拟对象替代，不使用真实API密钥。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from listing_stage2.api_analysis import analyze, prepare
from listing_stage2.component_policy import resolve
from listing_stage2.features import validate_part, validate_whole
from listing_stage2.model_gateway import Gateway, load_config

ROOT=Path(__file__).resolve().parents[1]


# 功能及输出：生成独立测试样本，供校验和异常分支断言使用。
def part_result():
    return {'semantic_description_en':'MOCK TEST ONLY: source title describing a foam topper.',
            'identity_scope':'current_or_family','composition':'unknown','palette':[],
            'scene':'unknown','themes':[],'claims':[],'limitations':['mock output, not real analysis']}


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class FakeGateway:
    calls=0
    # 功能及输出：模拟模型响应或模拟故障；不发送真实HTTP请求、不产生API费用。
    def complete(self,system,prompt,image=None):
        self.calls+=1
        if 'Analyzed components:\n' in prompt:
            parts=json.loads(prompt.split('Analyzed components:\n')[1])['parts']
            return {'keywords':[],'audience':[],'scenes':[],'style':[],'information_order':[],
                    'limitations':['mock'],'selling_points':[{'text':'mock selling point','evidence_part_ids':[parts[0]['part_id']]}],
                    'embedding_text_en':'MOCK TEST ONLY coherent whole Listing narrative.'},{'reported_model':'mock'}
        return part_result(),{'reported_model':'mock'}


# 类职责：测试夹具或模拟对象，具体场景见其方法注释。
class APIAnalysisTests(unittest.TestCase):
    # 功能及输出：验证：读取配置无需密钥或网络；断言失败即表示回归问题。
    def test_config_does_not_require_key(self):
        c=load_config(ROOT/'config/model-api.example.json')
        self.assertFalse(c['enabled'])

    # 功能及输出：验证：禁用API时不发请求；断言失败即表示回归问题。
    def test_disabled_gateway_never_opens_network(self):
        c=load_config(ROOT/'config/model-api.example.json')
        with patch('listing_stage2.model_gateway.build_opener') as opener:
            with self.assertRaises(ValueError):Gateway(c).complete('s','p')
            opener.assert_not_called()

    # 功能及输出：验证：兼容请求路径和JSON响应结构；断言失败即表示回归问题。
    def test_real_adapter_request_and_response_shape(self):
        c=load_config(ROOT/'config/model-api.example.json');c.update(enabled=True,model='mock-model')
        # 类职责：测试夹具或模拟对象，具体场景见其方法注释。
        class Response:
            headers={'x-request-id':'test-request'}
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def __enter__(self):return self
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def __exit__(self,*args):pass
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def read(self,n):return json.dumps({'model':'mock-model','choices':[{'finish_reason':'stop','message':{'content':json.dumps(part_result())}}]}).encode()
        with patch.dict(os.environ,{c['api_key_env']:'test-secret'}),patch('listing_stage2.model_gateway.build_opener') as opener:
            opener.return_value.open.return_value=Response()
            result,meta=Gateway(c).complete('system','JSON please')
            request=opener.return_value.open.call_args.args[0]
            self.assertTrue(request.full_url.endswith('/v1/chat/completions'))
            self.assertNotIn(b'test-secret',request.data)
            self.assertEqual(json.loads(request.data)['response_format']['type'],'json_object')
            self.assertEqual(meta['request_id'],'test-request')
            self.assertEqual(result['identity_scope'],'current_or_family')

    # 功能及输出：验证：拒绝错误证据和声明依据；断言失败即表示回归问题。
    def test_strict_evidence_and_claim_validation(self):
        x=part_result();x['claims']=[{'text':'certified','basis':'verified_by_model'}]
        with self.assertRaises(ValueError):validate_part(x)
        x=FakeGateway().complete('', 'Analyzed components:\n'+json.dumps({'parts':[{'part_id':'a'}]}))[0]
        with self.assertRaises(ValueError):validate_whole(x,{'foreign'})

    # 功能及输出：验证：报告预检和模拟分析完整流程；断言失败即表示回归问题。
    def test_plan_and_mock_analysis_from_report(self):
        report={'config':{'marketplace':'US','category_id':'toppers'},'products':[{'listing_rank':1,'requested_asin':'P1',
                'requested_url':'https://example.com/p','snapshot_id':'S1','parsed':{'title':'Foam topper','bullets':['First claim']},'media':[]}]}
        c=load_config(ROOT/'config/model-api.example.json')
        with tempfile.TemporaryDirectory() as d:
            r=Path(d)/'report.json';r.write_text(json.dumps(report),encoding='utf-8')
            b,controls,plan=prepare(r,1,c)
            self.assertEqual(plan['planned_api_calls'],3)
            self.assertEqual(plan['paid_calls'],0)
            original=copy.deepcopy(b)
            analyzed,review=analyze(b,controls,c,Path(d)/'result',FakeGateway())
            self.assertEqual(b,original)
            self.assertEqual(len(review['model_calls']),3)
            self.assertEqual(review['producer'],'api_generated_pending_operator_review')
            self.assertTrue((Path(d)/'result/review.json').exists())
            c['max_calls']=1
            with self.assertRaises(ValueError):prepare(r,1,c)

    # 功能及输出：验证：失败留下失败状态而非成功；断言失败即表示回归问题。
    def test_failure_leaves_failure_status_not_success(self):
        b={'bundle_id':'test','parts':[{'part_id':'a','role':'title','entity_kind':'text','source_text':'t','asset':None}], 'identity':{},'coverage':{}}
        # 类职责：测试夹具或模拟对象，具体场景见其方法注释。
        class Broken:
            calls=1
            # 功能及输出：模拟模型响应或模拟故障；不发送真实HTTP请求、不产生API费用。
            def complete(self,*a):raise RuntimeError('simulated failure')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):analyze(b,resolve(b),{},d,Broken())
            status=json.loads((Path(d)/'run.json').read_text())
            self.assertEqual(status['status'],'failed_no_automatic_retry')

    # 功能及输出：验证：已有结果编码不重调特征API；断言失败即表示回归问题。
    def test_saved_analysis_encodes_without_feature_api(self):
        import numpy as np
        from types import SimpleNamespace
        from listing_stage2.encode_analysis import encode
        from listing_stage2.whole_listing import input_fingerprint
        b={'bundle_id':'test','identity':{'product_id':'p'},'parts':[{'part_id':'a','role':'title','features':part_result(),'source_text':'text'}]}
        whole=FakeGateway().complete('', 'Analyzed components:\n'+json.dumps({'parts':[{'part_id':'a'}]}))[0]
        review={'input_fingerprint':input_fingerprint(b),'overall_features':whole}
        plan={'identity':b['identity'],'task_version_id':b['bundle_id'],'controls':{'a':{'embed':False,'enabled':True}}}
        c=load_config(ROOT/'config/model-api.example.json')
        with tempfile.TemporaryDirectory() as d:
            for name,value in [('analyzed_bundle.json',b),('review.json',review),('plan.json',plan)]:
                (Path(d)/name).write_text(json.dumps(value),encoding='utf-8')
            encoder=SimpleNamespace(model='mock',digest='mock-digest',encode=lambda text:np.array([1.,0.]))
            with patch('listing_stage2.encode_analysis.LocalEncoder',return_value=encoder):
                result=encode(d,c)
            self.assertEqual(result['overall_vectors'],1)
            self.assertEqual(result['component_vectors'],0)

    # 功能及输出：验证：本地图片按Base64格式进入请求；断言失败即表示回归问题。
    def test_gateway_attaches_local_image_as_data_url(self):
        from PIL import Image
        c=load_config(ROOT/'config/model-api.example.json');c.update(enabled=True,model='mock-model')
        # 类职责：测试夹具或模拟对象，具体场景见其方法注释。
        class Response:
            headers={}
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def __enter__(self):return self
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def __exit__(self,*a):pass
            # 功能及输出：模拟HTTP上下文/响应体供网关协议测试使用。
            def read(self,n):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode()
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'fixture.png';Image.new('RGB',(2,2)).save(image)
            with patch.dict(os.environ,{c['api_key_env']:'test-secret'}),patch('listing_stage2.model_gateway.build_opener') as opener:
                opener.return_value.open.return_value=Response()
                Gateway(c).complete('system','JSON please',image)
                body=json.loads(opener.return_value.open.call_args.args[0].data)
                self.assertTrue(body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))


if __name__=='__main__':unittest.main()
