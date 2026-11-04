# 文件用途：将第一阶段报告生成逐商品待分析任务；不会虚构特征或创建向量。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Prepare evidence-linked analysis tasks for all captured products; no fake features."""
import argparse
import hashlib
import json
from pathlib import Path
from .settings import ROOT
from .storage import write
from .listing_bundles import segment


# 功能及输出：输入第一阶段报告路径和输出目录；写逐商品analysis_task.json及索引，返回任务路径列表；不会执行分析。
# 参数：path（文件路径）；output（输出目录）。
def prepare(path, output):
    raw = path.read_bytes()
    report = json.loads(raw)
    config = report['config']
    country = segment(config.get('country_code', config['marketplace']))
    site = segment(config.get('site_id', 'amazon'))
    category = segment(config.get('category_id', 'toppers' if str(config.get('category_node')) == '8521807011' else 'node-'+str(config.get('category_node'))))
    tasks = []
    for product in report['products']:
        parsed = product.get('parsed', {})
        pid = segment(parsed.get('product_id') or parsed['asin'])
        relative = Path(country,site,category,pid,segment(product['snapshot_id']),'analysis_task.json')
        task = {'schema_version': 2, 'status': 'pending_analysis', 'identity': {'country_code':country,'site_id':site,'category_id':category,'product_id':pid,'snapshot_id':product['snapshot_id']}, 'source_id':report['source_id'], 'source_report':str(path), 'source_report_sha256':hashlib.sha256(raw).hexdigest(), 'original_copy':parsed, 'media':product.get('media',[]), 'required_output':'Reviewed per-part features plus product-level narrative; no vector until analyzed', 'whole_listing_vector':None}
        write(output/relative,task)
        tasks.append({'identity':task['identity'],'path':relative.as_posix(),'status':'pending_analysis'})
    write(output/'analysis_tasks.json',{'source_report_sha256':hashlib.sha256(raw).hexdigest(),'tasks':tasks})
    return tasks


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'data/analysis_tasks')
    a=p.parse_args()
    print(json.dumps({'pending_tasks':len(prepare(a.report,a.output)),'directory':str(a.output)},ensure_ascii=False))
