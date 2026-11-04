# 文件用途：路径常量；ROOT为第二阶段根目录，LEGACY为旧实验根目录，SOURCE_PAYLOAD为冻结数据。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
LEGACY = Path('D:/ListingAnalysis')
SOURCE_PAYLOAD = LEGACY/'data/gpt_top5/payload.json'
