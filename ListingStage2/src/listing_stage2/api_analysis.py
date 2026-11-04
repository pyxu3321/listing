# 文件用途：新API分析编排：报告组装→组件策略→预检→逐组件分析→整体综合→可选编码。只有 --execute 才调用远程模型。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
# 费用边界：只有显式执行且配置启用才调用API；失败可能已计费，无自动重试。
"""Opt-in API analysis from a captured report; no model calls in dry-run mode."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from .features import from_report,validate_part,validate_whole,PART_SYSTEM,PART_REQUEST,WHOLE_SYSTEM,WHOLE_REQUEST
from .component_policy import validate_policy,resolve,FLAGS
from .model_gateway import Gateway,load_config
from .listing_bundles import digest
from .whole_listing import build,input_fingerprint
from .storage import write


# 功能及输出：输入报告路径、历史排名、API配置和可选策略；校验图片与调用上限，返回原任务、有效开关和无联网计划。
# 参数：report（采集报告路径或已读取报告）；rank（报告中的历史排名，非当前实时排名）；config（运行配置，不含明文密钥）；policy（可选组件策略）。
def prepare(report,rank,config,policy=None):
    bundle=from_report(report,rank)
    validate_policy(policy,[bundle])
    controls=resolve(bundle,policy)
    # 四个用途只要有一个启用，仍需分析；仅关闭embed不能省去整体所需的图文调用。
    active=[p for p in bundle['parts'] if any(controls[p['part_id']][k] for k in FLAGS)]
    if not active or not any(controls[p['part_id']]['include_in_overall'] for p in active):
        raise ValueError('Need analyzed components contributing to the whole narrative')
    images=[]
    for p in active:
        if p.get('asset'):
            path=Path(p['asset']['local_path']);raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=p['asset']['asset_sha256']:raise ValueError('Source image hash mismatch')
            if len(raw)>config['max_image_bytes']:raise ValueError('Source image exceeds max_image_bytes')
            from PIL import Image
            with Image.open(path) as im:
                im.verify()
                if im.format not in {'JPEG','PNG','WEBP'}:raise ValueError('Unsupported image format')
            images.append(p['part_id'])
    # 每个活动组件一次，最后整体一次；这是次数预估，不是金额承诺。
    calls=len(active)+1
    if calls>config['max_calls']:raise ValueError('Planned calls exceed configured max_calls; reduce active components')
    return bundle,controls,{'status':'dry_run_no_network','task_version_id':bundle['bundle_id'],'identity':bundle['identity'],
          'source_components':len(bundle['parts']),'analyzed_components':len(active),'image_inputs':len(images),
          'planned_api_calls':calls,'component_ids':[p['part_id'] for p in active],
          'controls':controls,'config_fingerprint':digest(config),'video_status':bundle['coverage']['video_status'],
          'embedding':'local_ollama_only_when_encode_requested','paid_calls':0}


# 功能及输出：输入任务、开关、配置及输出目录；调用组件/整体模型，逐项校验并写检查点；返回分析包和整体审阅记录，失败写run.json后抛错。
# 参数：bundle（一个Listing快照及组件）；controls（见功能说明及调用处）；config（运行配置，不含明文密钥）；output（输出目录）；gateway（可注入模型网关，测试可替换为模拟对象）。
def analyze(bundle,controls,config,output,gateway=None):
    gateway=gateway or Gateway(config)
    bundle=deepcopy(bundle)
    # 四个用途只要有一个启用，仍需分析；仅关闭embed不能省去整体所需的图文调用。
    active=[p for p in bundle['parts'] if any(controls[p['part_id']][k] for k in FLAGS)]
    call_log=[]
    try:
        for p in active:
            context={'identity':bundle['identity'],'part_id':p['part_id'],'role':p['role'],
                     'source_title_claim_not_visual_proof':bundle.get('source_title'),
                     'source_text':p.get('source_text'),'scope_note':'competitor source, not own-product fact'}
            prompt=PART_REQUEST+'\nEvidence:\n'+json.dumps(context,ensure_ascii=False)
            if len(prompt)>120000:raise ValueError('Component input too long; split it explicitly')
            result,meta=gateway.complete(PART_SYSTEM,prompt,p['asset']['local_path'] if p.get('asset') else None)
            features=validate_part(result)
            p['features']=features
            # 关联商品或未知身份图片仍保留，但不自动纳入当前商品整体证据。
            p['eligible_for_aggregate']=bool(controls[p['part_id']]['include_in_overall'] and
                    (p['entity_kind']=='text' or features['identity_scope']=='current_or_family'))
            call_log.append({'part_id':p['part_id'],'prompt_sha256':digest([PART_SYSTEM,prompt]),
                             'image_sha256':p['asset']['asset_sha256'] if p.get('asset') else None,**meta})
            write(Path(output)/'component_reviews'/(p['part_id']+'.json'),{'part_id':p['part_id'],'features':features,'provenance':call_log[-1]})
        active_ids={p['part_id'] for p in active}
        for p in bundle['parts']:
            if p['part_id'] not in active_ids:p['eligible_for_aggregate']=False
            p['analysis_controls']={**controls[p['part_id']], 'include_in_overall':p['eligible_for_aggregate']}
        whole_parts=[{'part_id':p['part_id'],'role':p['role'],'features':p['features'],'source_text':p.get('source_text'),'reference':p.get('reference')} for p in active if p['eligible_for_aggregate']]
        if not whole_parts:raise ValueError('No eligible whole evidence after identity analysis')
        prompt=WHOLE_REQUEST+'\nAnalyzed components:\n'+json.dumps({'identity':bundle['identity'],'coverage':bundle['coverage'],'parts':whole_parts},ensure_ascii=False)
        if len(prompt)>120000:raise ValueError('Whole input too long; reduce task explicitly')
        result,meta=gateway.complete(WHOLE_SYSTEM,prompt)
        overall=validate_whole(result,{p['part_id'] for p in whole_parts})
        call_log.append({'scope':'whole_listing','prompt_sha256':digest([WHOLE_SYSTEM,prompt]),**meta})
        # 自动分析只生成待审核记录，不能自动赋予人工批准状态。
        review={'input_fingerprint':input_fingerprint(bundle),'overall_features':overall,
                'producer':'api_generated_pending_operator_review','model_calls':call_log}
        write(Path(output)/'analyzed_bundle.json',bundle)
        write(Path(output)/'review.json',review)
        write(Path(output)/'run.json',{'status':'features_ready_pending_operator_review','api_calls_attempted':gateway.calls,
                                     'calls':call_log,'automatic_approval':False})
        return bundle,review
    except Exception as error:
        write(Path(output)/'run.json',{'status':'failed_no_automatic_retry','api_calls_attempted':gateway.calls,
                  'completed_calls':call_log,'error_type':type(error).__name__,'billing_state':'provider_may_have_charged_failed_attempt'})
        raise


# 功能及输出：读取CLI；强制区分dry-run与execute，拒绝复用非空目录；可选调用独立编码入口。
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--rank',type=int,required=True)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--policy',type=Path)
    p.add_argument('--output',type=Path,required=True)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run',action='store_true');mode.add_argument('--execute',action='store_true')
    p.add_argument('--encode',action='store_true',help='After API analysis, encode with configured local Ollama')
    args=p.parse_args();c=load_config(args.config)
    policy=json.loads(args.policy.read_text(encoding='utf-8-sig')) if args.policy else None
    bundle,controls,plan=prepare(args.report,args.rank,c,policy)
    if args.encode and args.dry_run:raise ValueError('--encode requires --execute')
    if args.output.exists() and any(args.output.iterdir()):raise ValueError('Use an empty output directory for each run')
    if args.execute and not c['enabled']:raise ValueError('Set enabled=true in a local config before execution')
    write(args.output/'plan.json',plan)
    write(args.output/'input_task.json',bundle)
    if args.dry_run:
        print(json.dumps({k:plan[k] for k in ('status','identity','source_components','analyzed_components','image_inputs','planned_api_calls','paid_calls')},ensure_ascii=False,indent=2));return
    bundle,review=analyze(bundle,controls,c,args.output)
    if args.encode:
        from .encode_analysis import encode
        encode(args.output,c)
    print(json.dumps({'status':'completed_pending_review','directory':str(args.output),'api_calls':len(review['model_calls'])}))


if __name__=='__main__':main()
