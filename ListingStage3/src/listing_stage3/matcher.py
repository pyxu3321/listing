"""先检索整体，再从候选整体中匹配组件；分数是相似度，不是质量或销量。"""
import json
import math
from pathlib import Path

WHOLE_RECIPE='reviewed-whole-listing-summary-v3'
WHOLE_RECIPES={WHOLE_RECIPE,'whole-listing-full-evidence-v4','reviewed-structured-whole-v5'}
PART_RECIPE='component-semantic-text-v1'
ROLES={'main':'main_image','secondary':'gallery','aplus_image':'aplus'}


def request_query(request):
    """保留用户原始卖点，附可配置双语检索词，不把它们写成已核验参数。"""
    # 元数据是可选筛选项；不补默认国家、品类或产品描述，也不拼入查询。
    for key in ('country_code','category_id','product_description','style'):
        if request.get(key) is not None and not isinstance(request[key],str):raise ValueError('Invalid '+key)
    for key in ('site_ids','retrieval_terms','own_images'):
        if key in request and (not isinstance(request[key],list) or not all(isinstance(x,str) for x in request[key])):raise ValueError('Invalid '+key)
    if not isinstance(request.get('product_facts',{}),dict):raise ValueError('product_facts must be an object')
    if request.get('product_form') is not None and not isinstance(request['product_form'],str):raise ValueError('Invalid product_form')
    if not isinstance(request.get('selling_points',[]),list) or not all(isinstance(x,str) for x in request.get('selling_points',[])):raise ValueError('selling_points must be strings')
    if not isinstance(request.get('reference_needs',[]),list):raise ValueError('reference_needs must be a list')
    for n in request.get('reference_needs',[]):
        if not isinstance(n,dict) or not isinstance(n.get('role'),str) or not isinstance(n.get('purpose'),str):raise ValueError('Invalid reference need')
        if n.get('entity_kind') is not None and n['entity_kind'] not in {'image','text','video'}:
            raise ValueError('Invalid reference entity_kind')
        if 'preferred_themes' in n and (not isinstance(n['preferred_themes'],list) or not all(isinstance(t,str) and t.strip() for t in n['preferred_themes'])):
            raise ValueError('preferred_themes must be nonempty strings')
    content=[request.get('product_description') or '',*request.get('selling_points',[]),*request.get('retrieval_terms',[])]
    if not any(x.strip() for x in content):raise ValueError('Provide selling points, a product description or retrieval terms')
    parts=[request.get('product_description') or '',*request.get('selling_points',[]),request.get('style') or '',*request.get('retrieval_terms',[])]
    if not all(isinstance(x,str) for x in parts):raise ValueError('Query fields must be text')
    text='; '.join(x.strip() for x in parts if x.strip())
    if not text or len(text)>6000:raise ValueError('Query empty or too long')
    return text


def similarity(text,e,encoder,recipe,cache):
    """查询沿用同一模型摘要和配方，禁止v2/v3或不同模型混合打分。"""
    if e['model_digest']!=encoder.digest or e['recipe']!=recipe:raise ValueError('Incompatible query model or recipe')
    key=(recipe,text)
    if key not in cache:
        q=list(encoder.encode(text,query=True))
        if len(q)!=e['dimensions'] or any(not math.isfinite(float(x)) for x in q):raise ValueError('Bad query vector')
        norm=math.sqrt(sum(float(x)**2 for x in q))
        if not norm:raise ValueError('Zero query vector')
        cache[key]=[float(x)/norm for x in q]
    q=cache[key]
    if len(q)!=e['dimensions']:raise ValueError('Inconsistent embedding dimensions')
    return sum(a*b for a,b in zip(q,e['vector']))


def style_evidence(record, style, encoder, cache, top_n):
    """只用可用于生成参考的商品图片评估风格，保留命中的图片作为证据。

    当前复用图片视觉描述的文本向量，并非原生图像向量；取最接近的若干张均值，
    避免整套文案淹没少量场景图，也避免只凭一张偶然相似的图片代表整套风格。
    不使用销量排名、文字组件、视频缩略图或已禁用的图片。
    """
    hits=[]
    for p in record['components']:
        controls=p.get('controls',{})
        if not p.get('index_enabled') or any(not controls.get(k,True) for k in ('enabled','retrieve','generation_reference')):continue
        if p.get('entity_kind')!='image' or not p.get('asset') or not p.get('embedding'):continue
        if p.get('identity_scope',p.get('features',{}).get('identity_scope'))!='current_or_family':continue
        score=similarity(style,p['embedding'],encoder,PART_RECIPE,cache)
        hits.append({'part_id':p['part_id'],'source_role':p['role'],'similarity':round(score,6),
                     'description':p.get('features',{}).get('semantic_description_en',''),
                     'asset':p['asset'],'reference':p.get('reference'), '_raw_score':score})
    hits.sort(key=lambda x:(-x['_raw_score'],x['part_id']))
    selected=hits[:top_n]
    score=sum(x['_raw_score'] for x in selected)/len(selected) if selected else None
    for x in selected:x.pop('_raw_score')
    return score,selected


def order_close_candidates(candidates, tolerance):
    """已按综合分截取前N套后，仅在接近分数组内参考采集排名。

    每组以该组最高分为锚点，最大分差不超过tolerance，不做相邻差的链式扩张。
    仅同国家、站点、品类的组内比较历史排名；跨站点时保持语义顺序。
    未知排名排在该组已知排名后，原始相似度保留，不加销量权重。
    """
    ordered=[];remaining=list(candidates);group_id=0
    while remaining:
        anchor=remaining[0][0];group=[]
        while remaining and anchor-remaining[0][0]<=tolerance:
            group.append(remaining.pop(0))
        group_id+=1
        scopes={(x[1]['identity']['country_code'],x[1]['identity']['site_id'],x[1]['identity']['category_id']) for x in group}
        comparable=len(scopes)==1
        def rank_key(x):
            rank=x[1]['overall_features'].get('historical_rank')
            return (rank if type(rank) is int and rank>0 else math.inf,-x[0],x[1]['listing_version_id'])
        if tolerance>0 and comparable:group.sort(key=rank_key)
        for score,record,details in group:
            details.update(proximity_group=group_id,group_anchor_score=round(anchor,6),
                           capture_rank_tiebreak_applied=tolerance>0 and comparable and len(group)>1)
        ordered.extend(group)
    return ordered


def match(request,listings,settings,encoder):
    """返回整体候选和按用途分组的组件参考；无合适项时保留空结果，不强配。

    产品参数只能来自request.product_facts，参考声明保留来源，不转移为用户事实。
    """
    query=request_query(request);cache={};candidates=[];whole_recipes=set()
    # 产品与卖点单独编码；风格单独对照图片描述，最后再合成整体排序分。
    product_query=request_query({**request,'style':''})
    style=(request.get('style') or '').strip()
    country=(request.get('country_code') or '').strip()
    category=(request.get('category_id') or '').strip()
    weights=settings.get('whole_score_weights',{'product':0.65,'style':0.35})
    if not isinstance(weights,dict) or set(weights)!={'product','style'}:raise ValueError('Invalid whole_score_weights')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in weights.values()) or weights['product']<=0:raise ValueError('Invalid whole_score_weights')
    total=sum(weights.values());weights={k:v/total for k,v in weights.items()}
    style_top_n=settings.get('style_evidence_top_n',3)
    if type(style_top_n) is not int or style_top_n<1:raise ValueError('Invalid style_evidence_top_n')
    tolerance=settings.get('rank_tiebreak_tolerance',0.02)
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not 0<=tolerance<=2:raise ValueError('Invalid rank_tiebreak_tolerance')
    match_components=settings.get('match_components',False)
    if type(match_components) is not bool:raise ValueError('Invalid match_components')
    limit=settings['whole_top_k'];per_role=settings['components_per_need']
    if type(limit) is not int or limit<1 or type(per_role) is not int or per_role<1:raise ValueError('Invalid result limits')
    minimum=settings['minimum_similarity']
    if type(minimum) not in (int,float) or not -1<=minimum<=1:raise ValueError('Invalid similarity threshold')
    if type(settings.get('include_pending')) is not bool:raise ValueError('include_pending must be boolean')
    for record in listings:
        i=record['identity']
        if country and i['country_code']!=country:continue
        if category and i['category_id']!=category:continue
        if request.get('site_ids') and i['site_id'] not in request['site_ids']:continue
        approved=record.get('approval_status')=='approved'
        if not settings['include_pending'] and not approved:continue
        form=record['overall_features'].get('product_form')
        if isinstance(form,dict):form=form.get('name') or form.get('value')
        if request.get('product_form') and form!=request['product_form']:continue
        recipe=record['overall_embedding']['recipe']
        if recipe not in WHOLE_RECIPES:raise ValueError('Unsupported whole recipe')
        whole_recipes.add(recipe)
        if len(whole_recipes)>1:raise ValueError('Do not mix legacy summaries and full-evidence whole vectors in one ranking')
        product_score=similarity(product_query,record['overall_embedding'],encoder,recipe,cache)
        # 产品相似度先过门槛；风格相似不能挽救产品不相关的记录。
        if product_score<minimum:continue
        style_score,evidence=style_evidence(record,style,encoder,cache,style_top_n) if style else (None,[])
        applied=weights if style_score is not None else {'product':1.,'style':0.}
        score=applied['product']*product_score+applied['style']*(style_score or 0.)
        details={'product_similarity':round(product_score,6),
                 'style_similarity':round(style_score,6) if style_score is not None else None,
                 'weights':applied,'style_status':'scored' if style_score is not None else ('no_eligible_images' if style else 'not_requested'),
                 'style_evidence':evidence,'style_aggregation':'mean_top_n_image_caption_cosine',
                 'ranking_method':'weighted_product_and_visual_style','relevance_score':round(score,6)}
        candidates.append((score,record,details))
    candidates.sort(key=lambda x:(-x[0],x[1]['listing_version_id']));candidates=candidates[:limit]
    candidates=order_close_candidates(candidates,tolerance)
    whole=[{'listing_version_id':r['listing_version_id'],'identity':r['identity'],'similarity':round(score,6),
            **details,'preview_image':next((p['asset'] for p in r['components'] if p['role']=='main_image' and p.get('asset') and p.get('index_enabled') and p.get('controls',{}).get('enabled',True) and p.get('identity_scope',p.get('features',{}).get('identity_scope'))=='current_or_family'),None),'overall_features':r['overall_features'],'structured_features':r.get('structured_features'),'approval_status':r.get('approval_status'),
            'evidence':r['library_source'],'reasons':['已填写的筛选条件通过；未填写条件不限制','产品卖点与视觉风格分开评分，按实际权重综合排序'],
            'limitations':['相似度不是质量分','参考参数与功效声明不构成自有事实']} for score,r,details in candidates]
    needs=[]
    for need in (request.get('reference_needs',[]) if match_components else []):
        role=ROLES.get(need['role'],need['role']);items=[]
        for _,record,_ in candidates:
            for p in record['components']:
                c=p.get('controls',{})
                if not p['index_enabled'] or not c.get('enabled',True) or not c.get('retrieve',True) or not c.get('generation_reference',True):continue
                if ROLES.get(p['role'],p['role'])!=role or not p.get('embedding'):continue
                # A+同时包含文字和图片；指定图片用途时，禁止把FAQ文字当成配图。
                if need.get('entity_kind') and p.get('entity_kind')!=need['entity_kind']:continue
                scope=p.get('identity_scope',p.get('features',{}).get('identity_scope','unknown'))
                ref=p.get('reference') or {}
                # 历史视频挂接器已核对商品快照与文件哈希，但旧审阅未填写identity_scope。
                bound_video=(p['role']=='video' and ref.get('snapshot_id')==record['identity']['snapshot_id'] and
                             ref.get('asset_sha256')==(p.get('asset') or {}).get('asset_sha256') and bool(ref.get('asset_sha256')))
                if p.get('asset') and scope!='current_or_family' and not bound_video:continue
                text='; '.join(x for x in [role+': '+need['purpose'],request.get('style') or '',request.get('product_description') or ''] if x)
                score=similarity(text,p['embedding'],encoder,PART_RECIPE,cache)
                if score<minimum:continue
                # 可选用途标签只调整组件排序：仍先筛整体、再过相似度阈值。
                # 不自动把用户文字变成标签；示例标签由本次实验明确配置。
                preferred={t.strip().casefold() for t in need.get('preferred_themes',[])}
                observed={t.strip().casefold() for t in p.get('features',{}).get('themes',[])}
                hits=sorted(preferred & observed)
                coverage=len(hits)/len(preferred) if preferred else None
                relevance=.85*score+.15*coverage if preferred else score
                items.append({'listing_version_id':record['listing_version_id'],'part_id':p['part_id'],'identity':record['identity'],
                    'source_role':p['role'],'planned_use':need['role'],'purpose':need['purpose'],'similarity':round(score,6),
                    'relevance_score':round(relevance,6),'theme_matches':hits,
                    'ranking_method':'0.85*cosine+0.15*preferred_theme_coverage' if preferred else 'cosine_only',
                    'features':p['features'],'source_text':p.get('source_text'),'asset':p.get('asset'),
                    'reference':p.get('reference'),'module_placements':p.get('module_placements',[]),
                    'reference_role':'expression_reference','limitations':p.get('features',{}).get('limitations',[]),
                    'approval_status':record.get('approval_status'),'available_recipes':[x for x in record.get('generation_recipes',[]) if p['part_id'] in x['reference_part_ids'] and x.get('availability')!='blocked_reference_disabled' and x['status']!='retired']})
        items.sort(key=lambda x:(-x['relevance_score'],-x['similarity'],x['listing_version_id'],x['part_id']))
        needs.append({'role':need['role'],'purpose':need['purpose'],'status':'candidates_pending_confirmation' if items else 'no_compatible_reference','candidates':items[:per_role]})
    missing=[]
    if not request.get('own_images'):missing.append('自有产品实拍图')
    elif not all(Path(p).is_file() for p in request['own_images']):missing.append('自有产品图片路径不可读取')
    if not request.get('product_facts'):missing.append('可核验自有产品事实')
    return {'schema_version':1,'status':'draft_pending_operator_confirmation' if whole else 'no_whole_match',
            'query':query,'product_query':product_query,'style_query':style,'whole_scoring':{'configured_weights':weights,'style_evidence_top_n':style_top_n,'rank_tiebreak_tolerance':tolerance,'rank_basis':'historical_capture_rank_not_current_bsr','selection_order':'score_top_n_then_close_score_groups_by_capture_rank','product_minimum_similarity':minimum,'score_note':'similarity为综合排序分，product_similarity与style_similarity为余弦相似度，均非质量分或概率'},'input_request':request,'whole_candidates':whole,'reference_needs':needs,
            'search_scope':{'country_code':country or None,'category_id':category or None,'scope':'configured_libraries_only'},'missing_generation_inputs':missing,'generation_ready':False,
            'component_matching':{'status':'executed' if match_components else 'deferred_to_generation_planning','enabled':match_components},'selection_policy':'whole_first_then_components','quality_score':None,
            'warning':'用户卖点为输入陈述，竞品内容为表达参考；均不自动成为已核验功效。'}
