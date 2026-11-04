"""第三阶段命令行入口：读取用户需求和特征库，输出候选参考包。"""
import argparse
import json
from pathlib import Path
from .library import read,load
from .encoder import create
from .matcher import match,request_query
from .output import write


def main():
    """--plan只校验需求及库，不访问模型；正常运行仅使用本地Ollama。"""
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--plan',action='store_true')
    a=p.parse_args();request=read(a.request);config=read(a.config)
    request_query(request);listings,inventory=load(config['library_indexes'],config['encoder']['stage2_project'])
    if a.plan:
        print(json.dumps({'listings':len(listings),'component_records':sum(len(x['components']) for x in listings),'no_model_call':True}));return
    if a.output.exists() and any(a.output.iterdir()):raise ValueError('Use a new empty output directory')
    result=match(request,listings,config['retrieval'],create(config['encoder']))
    write(a.output,result,inventory)
    print(json.dumps({'status':result['status'],'whole_candidates':len(result['whole_candidates']),'viewer':str(a.output/'index.html')},ensure_ascii=False))


if __name__=='__main__':main()
