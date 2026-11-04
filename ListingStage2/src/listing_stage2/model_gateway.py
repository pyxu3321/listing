# 文件用途：Chat Completions兼容图文网关：环境变量密钥、Base64图片、JSON解析和请求上限；无自动重试。
# 核对说明：本轮仅增加中文注释，保持原有语句、数据、调用及异常处理不变。
# 费用边界：只有显式执行且配置启用才调用API；失败可能已计费，无自动重试。
"""Small Chat Completions-compatible JSON/vision gateway, standard library only."""
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener


# 类职责：禁止HTTP自动重定向的处理器。
class NoRedirect(HTTPRedirectHandler):
    # 功能及输出：拒绝自动HTTP跳转，返回None，避免向其他地址转发认证头。
    def redirect_request(self, *args, **kwargs): return None


# 功能及输出：输入JSON配置路径；返回经校验的配置，不读取密钥、不联网；不接受明文api_key字段。
# 参数：path（文件路径）。
def load_config(path):
    config=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if 'api_key' in config:raise ValueError('Store API keys in environment variables, not config')
    if config.get('schema_version') != 1 or config.get('protocol') != 'chat_completions':
        raise ValueError('Expected schema_version=1 and protocol=chat_completions')
    url=urlsplit(config['base_url'])
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError('base_url must not contain credentials, query or fragment')
    if url.scheme != 'https' and not (url.scheme=='http' and url.hostname in {'localhost','127.0.0.1','::1'}):
        raise ValueError('Use HTTPS, or local loopback HTTP for testing')
    for k in ('model','api_key_env'):
        if not isinstance(config.get(k),str) or not config[k].strip(): raise ValueError('Missing '+k)
    if type(config.get('enabled')) is not bool: raise ValueError('enabled must be boolean')
    for k in ('timeout_seconds','max_calls','max_image_bytes','max_output_tokens'):
        if type(config.get(k)) is not int or config[k]<=0: raise ValueError('Invalid '+k)
    if config.get('token_parameter') not in ('max_tokens','max_completion_tokens'):
        raise ValueError('Invalid token_parameter')
    if config.get('json_mode') not in ('json_object','prompt_only'): raise ValueError('Invalid json_mode')
    if config.get('embedding',{}).get('provider','ollama_local')!='ollama_local':raise ValueError('Only local Ollama embeddings are implemented')
    return config


# 类职责：单次运行的模型请求对象；维护调用次数，配置与密钥分离。
class Gateway:
    # 功能及输出：保存配置并初始化本次尝试计数；不发送请求。
    # 参数：config（运行配置，不含明文密钥）。
    def __init__(self,config):
        self.config=config
        self.calls=0

    # 功能及输出：输入system提示、任务提示及可选本地图片；成功返回JSON对象与模型/用量元数据；最多一次HTTP请求，可能计费，失败不自动重试。
    # 参数：system（系统提示词）；prompt（本次分析提示词）；image（可选本地图片路径）。
    def complete(self,system,prompt,image=None):
        c=self.config
        if not c['enabled']: raise ValueError('API disabled in configuration')
        if c['model'].startswith('REPLACE_'): raise ValueError('Configure an actual model ID')
        key=os.environ.get(c['api_key_env'])
        if not key: raise ValueError('Missing API-key environment variable: '+c['api_key_env'])
        if '\r' in key or '\n' in key:raise ValueError('Invalid API-key value')
        if self.calls>=c['max_calls']: raise ValueError('API call limit reached')
        content=[{'type':'text','text':prompt}]
        if image:
            p=Path(image);raw=p.read_bytes()
            from PIL import Image
            with Image.open(p) as im:
                im.verify()
                mime={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}.get(im.format)
            if not mime or len(raw)>c['max_image_bytes']: raise ValueError('Unsupported or oversized image')
            content.append({'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(raw).decode()}})
        body={'model':c['model'],'messages':[{'role':'system','content':system},{'role':'user','content':content}],c['token_parameter']:c['max_output_tokens']}
        if c['json_mode']=='json_object':body['response_format']={'type':'json_object'}
        request=Request(c['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        # 尝试请求即计次；网络超时不代表供应商未计费，不自动重试。
        self.calls+=1
        try:
            with build_opener(NoRedirect()).open(request,timeout=c['timeout_seconds']) as response:
                raw=response.read(12*1024*1024+1)
                if len(raw)>12*1024*1024:raise ValueError('API response too large')
                envelope=json.loads(raw)
                request_id=response.headers.get('x-request-id')
        except HTTPError as error:
            raise RuntimeError('Model API HTTP '+str(error.code)+'; no automatic retry') from None
        except (URLError,TimeoutError,OSError):
            raise RuntimeError('Model API connection failed or timed out; billing state unknown; no automatic retry') from None
        choice=envelope['choices'][0]
        if choice.get('finish_reason')!='stop':raise ValueError('Model response incomplete or refused')
        text=choice['message'].get('content')
        if not isinstance(text,str):raise ValueError('Expected JSON text content')
        result=json.loads(text)  # Fail rather than repairing truncated/fenced JSON.
        if not isinstance(result,dict):raise ValueError('Expected JSON object')
        return result,{'requested_model':c['model'],'reported_model':envelope.get('model'),
                       'request_id':request_id,'usage':envelope.get('usage'),'protocol':c['protocol']}
