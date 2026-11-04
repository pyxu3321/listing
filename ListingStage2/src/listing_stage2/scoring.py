# 文件用途：评分尚未校准，输出null分数和待审阅原则，不能把历史排名当质量分。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
# 功能及输出：输入旧payload；返回每个特征的未校准评分记录，total_score保持None。
# 参数：payload（旧实验结构化数据）。
def assess(payload):
    return [{'feature_id':f['feature_id'],'total_score':None,'status':'uncalibrated','reason':'Awaiting approved rubric and human anchor samples'} for f in payload['features']]

# 功能及输出：输入旧payload；提取商品级候选分析及证据，不宣称已验证高分。
# 参数：payload（旧实验结构化数据）。
def principles(payload):
    return [{'feature_id':f['feature_id'],'status':'candidate_pending_review','evidence':f['snapshot_key'],'product_analysis':f['features'],'high_score_claim':False} for f in payload['features'] if f['entity_kind']=='product']
