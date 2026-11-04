# 文件用途：独立单商品视频工具：顺序Range分块、断点续传、无总时限；与常规下载器的超时/重试策略不同。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
# 特别注意：本独立工具没有总超时，网络失败可能持续重试；停止需由操作者中断。
"""Resumable single-product MP4 download, without an overall time limit."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen
from .storage import LocalArchive, _process_video, _validate_url, DEFAULT_ALLOWED_HOSTS


# 功能及输出：按报告历史排名选择直接视频链接，Range断点续传并归档；网络错误无限重试/退避，单请求60秒且文件上限100MiB，无总时限；不更新原报告。
# 参数：report_path（保留报告路径）；rank（报告中的历史排名）。
def download(report_path, rank=1):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    product = next(p for p in report['products'] if p.get('listing_rank') == rank)
    candidate = next(v for v in product['parsed']['videos'] if v['kind'] == 'direct')
    url = _validate_url(candidate['url'], DEFAULT_ALLOWED_HOSTS)
    root = report_path.resolve().parents[2]
    from .catalog import product_identity
    identity = product_identity(report['config'],product)
    folder = root/'products'/identity['country_code']/identity['site_id']/identity['category_id']/identity['product_id']/report['run_id']/'视频'
    folder.mkdir(parents=True, exist_ok=True)
    part = folder/'01_视频.mp4.part'
    state = folder/'download_state.json'
    if state.exists():
        old = json.loads(state.read_text(encoding='utf-8'))
        if old['url'] != url:
            raise ValueError('Resume source differs')
    elif part.exists():
        raise ValueError('Partial file has no source manifest')
    state.write_text(json.dumps({'url':url,'identity':identity,'no_total_timeout':True},ensure_ascii=False,indent=2),encoding='utf-8')
    received = part.stat().st_size if part.exists() else 0
    total = None
    start = time.monotonic()
    initial = received
    failures = 0
    # 独立视频工具无总超时：网络失败退避后续传，需人为中断才能提前停止。
    while total is None or received < total:
        end = min(received+1024*1024-1,total-1) if total else received+1024*1024-1
        try:
            request = Request(url,headers={'Range':f'bytes={received}-{end}','Accept-Encoding':'identity'})
            with urlopen(request,timeout=60) as response:
                _validate_url(response.url,DEFAULT_ALLOWED_HOSTS)
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                if response.status != 206 or not match or int(match[1]) != received:
                    raise ValueError('Invalid byte-range response')
                current_total=int(match[3])
                if total is not None and total != current_total:
                    raise ValueError('Remote video size changed')
                # 此工具固定100MiB上限，不读取常规max_video_bytes配置；续传只复核总长度，未校验ETag。
                if current_total > 100*1024*1024:
                    raise ValueError('Video exceeds configured 100 MB byte limit')
                total=current_total
                expected=int(match[2])-int(match[1])+1
                data=response.read(expected+1)
                if len(data)!=expected:
                    raise ValueError('Incomplete byte range')
                with part.open('ab') as handle:
                    handle.write(data)
                received+=len(data)
                failures=0
                elapsed=time.monotonic()-start
                print(json.dumps({'downloaded_mb':round(received/1048576,2),'total_mb':round(total/1048576,2),'percent':round(received/total*100,1),'elapsed_seconds':round(elapsed,1),'average_kb_s':round((received-initial)/1024/max(elapsed,.001),1)},ensure_ascii=False),flush=True)
        except ValueError:
            raise
        except Exception as exc:
            failures+=1
            print(json.dumps({'status':'retrying','error_type':type(exc).__name__,'resume_bytes':received,'attempt':failures}),flush=True)
            time.sleep(min(5*failures,30))
    result = _process_video(part,LocalArchive(root))
    destination=folder/'01_视频.mp4'
    part.replace(destination)
    result.update(identity=identity,status='stored',source_url=url,source_report=str(report_path),source_report_sha256=hashlib.sha256(raw).hexdigest(),snapshot_id=product['snapshot_id'],downloaded_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=round(time.monotonic()-start,2),export_path=str(destination),download_method='sequential_validated_ranges_no_total_timeout')
    if hashlib.sha256(report_path.read_bytes()).hexdigest()!=result['source_report_sha256']:
        raise ValueError('Original report changed')
    (folder/'视频下载记录.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    state.unlink()
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--rank',type=int,default=1)
    args=parser.parse_args()
    download(args.report,args.rank)
