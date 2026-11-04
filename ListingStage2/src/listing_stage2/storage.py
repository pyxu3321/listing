# 文件用途：写入JSON时先写临时文件再替换；提供MySQL浮点读回比较，不实现数据库连接或跨系统事务。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
import json, os
from pathlib import Path

# 功能及输出：输入目标路径和JSON值；创建目录、写同名.tmp再原子替换目标，拒绝非有限JSON数值；会写磁盘。
# 参数：path（文件路径）；value（待校验/序列化对象）。
def write(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(tmp,path)


# 功能及输出：递归比较JSON值；只有浮点数使用1e-12容差，其他字段必须精确相同；用于数据库读回。
# 参数：a（左侧值）；b（右侧值）。
def equivalent(a, b):
    """MySQL JSON may round IEEE floats in serialization; other fields stay exact."""
    import math
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if isinstance(a,float) and isinstance(b,(float,int)):
        return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    if isinstance(b,float) and isinstance(a,int):
        return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    return a == b
