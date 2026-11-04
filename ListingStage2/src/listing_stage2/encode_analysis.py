# 文件用途：读取已完成的API分析结果，单独调用本地Ollama编码，不重复请求付费图文模型。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Encode existing API analysis without repeating paid feature-extraction calls."""
import argparse
import json
from pathlib import Path
from .model_gateway import load_config
from .local_encoder import LocalEncoder
from .whole_listing import build
from .storage import write
from .settings import ROOT


# 功能及输出：输入已分析目录与配置；核对计划/输入指纹，使用本地模型生成v4完整证据文件和encoding.json；返回向量数量，不调用远程图文API。
# 参数：directory（已有分析结果目录）；config（运行配置，不含明文密钥）。
def encode(directory,config):
    directory=Path(directory)
    read=lambda name:json.loads((directory/name).read_text(encoding='utf-8'))
    bundle,review,plan=read('analyzed_bundle.json'),read('review.json'),read('plan.json')
    if bundle['identity']!=plan['identity'] or bundle['bundle_id']!=plan['task_version_id']:
        raise ValueError('Analysis plan does not match source task')
    settings=config.get('embedding',{})
    encoder=LocalEncoder(ROOT/'data/listing_embedding_cache',url=settings.get('url','http://127.0.0.1:11434'),model=settings.get('model','nomic-embed-text:latest'))
    ids={pid for pid,v in plan['controls'].items() if v['embed'] and v['enabled']}
    result=build(bundle,review,encoder,component_ids=ids)
    write(directory/'listing_features.json',result)
    status={'status':'ready_pending_review','overall_vectors':1,'component_vectors':sum('embedding' in p for p in result['parts'])}
    write(directory/'encoding.json',status)
    return status


# 功能及输出：读取--input与--config，执行已有分析的本地编码并打印摘要。
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    a=p.parse_args();print(json.dumps(encode(a.input,load_config(a.config))))


if __name__=='__main__':main()
