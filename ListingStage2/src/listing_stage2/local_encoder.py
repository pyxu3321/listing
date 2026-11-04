# 文件用途：本地Ollama文本编码与内容缓存；仅允许本机地址，不允许静默截断输入。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
"""Local-only text encoder with content-addressed cache; no silent truncation."""
import hashlib
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import numpy as np
from .storage import write


# 功能及输出：输入数值向量；拒绝非一维、零向量和非有限值，返回L2归一化NumPy向量。
# 参数：vector（数值向量）。
def normalized(vector):
    v = np.asarray(vector, dtype=float)
    if v.ndim != 1 or not len(v) or not np.isfinite(v).all() or np.linalg.norm(v) == 0:
        raise ValueError('Invalid embedding')
    return v / np.linalg.norm(v)


# 类职责：绑定本地模型摘要和缓存的文本向量编码器。
class LocalEncoder:
    # 功能及输出：输入缓存目录、本机服务URL及模型名；查询本地Ollama模型清单，记录模型摘要；不会安装模型。
    # 参数：cache（向量缓存目录）；url（本机服务地址）；model（模型ID）。
    def __init__(self, cache, url='http://127.0.0.1:11434', model='nomic-embed-text:latest'):
        address = urlsplit(url)
        if address.scheme != 'http' or address.hostname not in {'localhost', '127.0.0.1', '::1'} or address.username or address.password:
            raise ValueError('Only a local Ollama endpoint is allowed')
        self.url, self.model, self.cache = url.rstrip('/'), model, cache
        with urlopen(self.url + '/api/tags', timeout=10) as response:
            models = json.load(response)['models']
        item = next((x for x in models if x['name'] == model), None)
        if item is None:
            raise ValueError('Install the configured local model first')
        self.digest = item['digest']
        self.dimensions = None

    # 功能及输出：输入文本和query开关；添加查询/文档前缀，命中缓存则读缓存，否则调用本地模型并写缓存；返回归一化向量。
    # 参数：text（待编码文本）；query（查询文本或查询模式开关）。
    def encode(self, text, query=False):
        body = ('search_query: ' if query else 'search_document: ') + text
        key = hashlib.sha256((self.digest + 'listing-chunk-v1:' + body).encode()).hexdigest()
        path = self.cache / (key + '.json')
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record['input_sha256'] != hashlib.sha256(body.encode()).hexdigest() or record['model_digest'] != self.digest:
                raise ValueError('Stale encoder cache')
            vector = normalized(record['vector'])
        else:
            request = Request(self.url + '/api/embed', data=json.dumps({'model': self.model, 'input': body, 'truncate': False}).encode(), headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=120) as response:
                values = json.load(response)['embeddings']
            if len(values) != 1:
                raise ValueError('Unexpected embedding count')
            vector = normalized(values[0])
            write(path, {'model_digest': self.digest, 'input_sha256': hashlib.sha256(body.encode()).hexdigest(), 'vector': vector.tolist()})
        if self.dimensions is not None and self.dimensions != len(vector):
            raise ValueError('Mixed vector dimensions')
        self.dimensions = len(vector)
        return vector
