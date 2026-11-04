# 文件用途：历史v2第三阶段匹配/组件选择预览；新特征库索引尚未接入此入口。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Whole-Listing search and traceable component selection for stage-three trials."""
import argparse
import json
from pathlib import Path
from .settings import ROOT
from .local_encoder import LocalEncoder
from .listing_bundles import match, select_parts
from .storage import write


# 功能及输出：读取历史listing_index，执行查询或组件组合并写预览；查询使用本地Ollama，默认不返回待审阅候选。
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory', type=Path)
    p.add_argument('--query')
    p.add_argument('--country', default='US')
    p.add_argument('--category', default='toppers')
    p.add_argument('--include-pending', action='store_true')
    p.add_argument('--selections', type=Path, help='JSON array of bundle_id,part_id,planned_use')
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    directory = args.directory or Path(json.loads((ROOT/'outputs/latest.json').read_text(encoding='utf-8'))['directory'])
    index = json.loads((directory/'listing_index.json').read_text(encoding='utf-8'))
    bundles = [json.loads((directory/x['path']).read_text(encoding='utf-8')) for x in index['listings']]
    if args.selections:
        result = select_parts(bundles, json.loads(args.selections.read_text(encoding='utf-8')))
    elif args.query:
        result = {'query': args.query, 'status': 'preview_not_approval', 'retrieval_unit': 'whole_listing', 'results': match(bundles,args.query,LocalEncoder(ROOT/'data/listing_embedding_cache'),args.country,args.category,include_pending=args.include_pending)}
    else:
        p.error('Provide --query or --selections')
    output = args.output or directory/'match_preview.json'
    write(output,result)
    print(json.dumps({'output': str(output), 'count':len(result.get('results',result.get('selections',[])))},ensure_ascii=False))


if __name__ == '__main__':
    main()
