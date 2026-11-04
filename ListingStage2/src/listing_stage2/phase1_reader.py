# 文件用途：读取D:/ListingAnalysis的冻结五商品payload；先校验config/pilot.json中的哈希。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import json
from .contracts import validate, sha
from .settings import ROOT, SOURCE_PAYLOAD

# 功能及输出：无参数；校验冻结payload哈希并调用contracts.validate，返回旧试验数据；需旧项目文件存在。
def load():
    expected=json.loads((ROOT/'config/pilot.json').read_text(encoding='utf-8'))['payload_sha256']
    raw=SOURCE_PAYLOAD.read_bytes()
    if sha(raw)!=expected: raise ValueError('Pilot payload changed; explicit refresh required')
    return validate(json.loads(raw))
