"""单视频续传：无总时限，保留单次网络等待上限和可恢复状态。"""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from .storage import _validate_url, DEFAULT_ALLOWED_HOSTS, _process_video


class ValidatedRedirect(HTTPRedirectHandler):
    """跳转前检查媒体白名单，避免向其他地址发起下载。"""
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        _validate_url(newurl,DEFAULT_ALLOWED_HOSTS)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_video(url,archive,max_bytes,progress=None,pause_seconds=1):
    """按URL保存续传检查点，成功返回归档记录；永久HTTP错误退出，暂时错误持续退避。

    参数：url为已确认归属的直接视频；max_bytes仍限制体积，时间不设总限。
    progress接收进度字典。进程中断后再次调用同一URL可继续下载。
    """
    _validate_url(url,DEFAULT_ALLOWED_HOSTS)
    key=hashlib.sha256(url.encode()).hexdigest()
    folder=archive.root/'video_queue';folder.mkdir(exist_ok=True)
    part=folder/(key+'.part');state_path=folder/(key+'.json')
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'url':url}
    if state.get('url')!=url:raise ValueError('Resume URL changed')
    if part.exists() and not state_path.exists():raise ValueError('Missing resume state')
    total=state.get('total');failures=0
    opener=build_opener(ValidatedRedirect())
    def checkpoint(**values):
        state.update(values)
        archive.persist_json(state,state_path.relative_to(archive.root))
        if progress:progress({k:v for k,v in state.items() if k!='url'})
    while total is None or (part.stat().st_size if part.exists() else 0)<total:
        received=part.stat().st_size if part.exists() else 0
        headers={'Range':f'bytes={received}-{received+1048575}','Accept-Encoding':'identity'}
        if received and state.get('validator'):headers['If-Range']=state['validator']
        try:
            with opener.open(Request(url,headers=headers),timeout=60) as response:
                _validate_url(response.url,DEFAULT_ALLOWED_HOSTS)
                validator=response.headers.get('ETag')
                if validator and validator.startswith('W/'):validator=None
                validator=validator or response.headers.get('Last-Modified')
                if response.status==206:
                    m=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not m or int(m[1])!=received or int(m[2])<received:raise ValueError('Invalid video range')
                    observed_total=int(m[3]);expected=int(m[2])-int(m[1])+1
                    if expected>1048576 or int(m[2])>=observed_total:raise ValueError('Invalid range size')
                    if total is not None and total!=observed_total:raise ValueError('Remote size changed; review and restart needed')
                    if received and state.get('validator') and state['validator']!=validator:raise ValueError('Remote version changed')
                    total=observed_total
                    if total>max_bytes:raise ValueError('Video exceeds byte limit')
                    checkpoint(total=total,validator=validator,version_check='etag_or_last_modified' if validator else 'size_only_unverified',status='downloading')
                    data=response.read(expected+1)
                    if len(data)!=expected:raise ConnectionError('Incomplete video range')
                    with part.open('ab') as f:f.write(data);f.flush()
                elif response.status==200:
                    # 服务端不支持Range或版本已变，整文件重新开始，绝不拼接两个版本。
                    length=response.headers.get('Content-Length');total=int(length) if length else None
                    if total is not None and total>max_bytes:raise ValueError('Video exceeds byte limit')
                    checkpoint(total=total,validator=validator,status='restarting_full_stream',version_check='full_stream')
                    size=0
                    with part.open('wb') as f:
                        while True:
                            data=response.read(1048576)
                            if not data:break
                            size+=len(data)
                            if size>max_bytes:raise ValueError('Video exceeds byte limit')
                            f.write(data);f.flush();checkpoint(received=size,total=total)
                    if total is not None and size!=total:raise ConnectionError('Incomplete full video')
                    total=size
                else:raise ValueError('Unexpected video status')
            failures=0
            checkpoint(received=part.stat().st_size,total=total,status='downloaded' if part.stat().st_size==total else 'downloading')
            if pause_seconds:time.sleep(pause_seconds)
        except HTTPError as e:
            if e.code not in {408,425,429,500,502,503,504}:raise RuntimeError('Permanent video HTTP '+str(e.code)) from None
            failures+=1;checkpoint(status='retrying',failures=failures,error_type='HTTP_'+str(e.code));time.sleep(min(failures*5,60))
        except (URLError,TimeoutError,ConnectionError,OSError) as e:
            failures+=1;checkpoint(status='retrying',failures=failures,error_type=type(e).__name__);time.sleep(min(failures*5,60))
    result=_process_video(part,archive)
    result.update(status='stored',kind='video',source_url=url,download_method='resumable_no_total_timeout',version_check=state.get('version_check'))
    checkpoint(status='stored',sha256=result['sha256'])
    part.unlink(missing_ok=True)
    return result
