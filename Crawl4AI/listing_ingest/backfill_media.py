"""按保留快照补齐全部已发现图片及直接视频，另存报告，不改原快照。"""
import argparse
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
import aiohttp
from .runner import load_config,render_report
from .storage import LocalArchive
from .media_collect import collect_product_media
from .export_products import export_products
from .resumable_video import fetch_video


@contextmanager
def worker_lock(folder):
    """同一补采目录只允许一个进程；进程退出后操作系统释放锁。"""
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'worker.lock').open('a+b') as f:
        f.seek(0);f.write(b'0');f.flush();f.seek(0)
        import os
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def prepare(source,config,state):
    """新建或恢复补采报告，校验原报告哈希；返回报告与归档器。"""
    raw=source.read_bytes();source_sha=hashlib.sha256(raw).hexdigest()
    archive=LocalArchive(source.resolve().parents[2])
    target=state/'report.json'
    if target.exists():
        report=json.loads(target.read_text(encoding='utf-8'))
        if report['source_report_sha256']!=source_sha:raise ValueError('Source report changed')
        if report['config']!=config:raise ValueError('Config changed; use a new state directory')
    else:
        report=deepcopy(json.loads(raw));report['source_run_id']=report['run_id']
        report['run_id']='media_all_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
        report['source_report_sha256']=source_sha;report['source_report']=str(source.resolve())
        report['config']=config;report['status']='running';report.pop('product_exports',None)
        report['media_backfill']={'images_completed':[],'videos':{},'note':'Only observed source media; no fresh ranking observation'}
    report['media_backfill']['worker_implementation_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    return report,archive


async def execute(source,config,state):
    """先补全部图片，再逐个下载视频。写独立进度、报告和商品导出。"""
    report,archive=prepare(source,config,state)
    task=report['media_backfill'];shared={}
    for p in report['products']:
        for m in p.get('media',[]):
            if m.get('status')=='stored':shared[(m['kind'],m['source_url'])]=m
    last_checkpoint=0.0
    def checkpoint(**progress):
        nonlocal last_checkpoint
        if not progress and time.monotonic()-last_checkpoint<2:return
        counts={'stored_images':sum(m.get('kind')=='image' and m.get('status')=='stored' for p in report['products'] for m in p.get('media',[])),
                'videos_stored':sum(v.get('status')=='stored' for v in task['videos'].values()),
                'videos_failed':sum(v.get('status')=='failed' for v in task['videos'].values()),
                'image_products_done':len(task['images_completed']),'products':len(report['products'])}
        task.update(counts);task.update(progress)
        report['summary']={**report.get('summary',{}),'stored_images':counts['stored_images'],
                           'stored_media':sum(m.get('status')=='stored' for p in report['products'] for m in p.get('media',[])),
                           'stored_videos':sum(m.get('kind')=='video' and m.get('status')=='stored' for p in report['products'] for m in p.get('media',[]))}
        archive.persist_json(report,(state/'report.json').relative_to(archive.root))
        archive.persist_json({'status':report['status'],'run_id':report['run_id'],**task},(state/'progress.json').relative_to(archive.root))
        last_checkpoint=time.monotonic()
    checkpoint(phase='images')
    async with aiohttp.ClientSession(trust_env=True) as session:
        for p in sorted(report['products'],key=lambda p:p.get('listing_rank') or 99999):
            if p['snapshot_id'] in task['images_completed']:continue
            checkpoint(current_product=p['requested_asin'],current_rank=p.get('listing_rank'))
            await collect_product_media(p,{**report['config'],'max_videos_per_product':0},archive,session,checkpoint=checkpoint,shared_downloads=shared)
            # 图片失败允许重启后再试，不能把partial直接记为完成。
            if not any(m.get('kind')=='image' and m.get('status')=='failed' for m in p.get('media',[])):task['images_completed'].append(p['snapshot_id'])
            checkpoint()
    report['product_exports']=export_products(report,archive.root);checkpoint(phase='videos')
    # 接入此前成功下载的独立视频，不重复传输同一URL。
    for path in (archive.root/'products').rglob('视频下载记录.json'):
        v=json.loads(path.read_text(encoding='utf-8'))
        if v.get('status')=='stored':shared[('video',v['source_url'])]=v
    for p in sorted(report['products'],key=lambda p:p.get('listing_rank') or 99999):
        for seq,candidate in enumerate(p['parsed'].get('videos',[]),1):
            url=candidate['url'];key=hashlib.sha256((p['snapshot_id']+url).encode()).hexdigest()
            # 补充归并已验证同任务MP4/HLS替代表示，恢复时保留完成状态。
            if task['videos'].get(key,{}).get('status') in {'stored','link_only','covered_by_saved_representation'}:continue
            checkpoint(current_product=p['requested_asin'],current_rank=p.get('listing_rank'),video_sequence=seq)
            try:
                if candidate['kind']!='direct':
                    task['videos'][key]={'status':'link_only','source_url':url,'product_id':p['requested_asin'],'reason':'playlist_or_blob_requires_adapter'}
                    checkpoint();continue
                old=shared.get(('video',url))
                if old:
                    path=Path(old.get('path') or old.get('export_path',''))
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=old.get('sha256'):old=None
                if old:
                    result={k:v for k,v in old.items() if k not in {'identity','snapshot_id','asin','export_path','source_report','source_report_sha256'}}
                    result.update(status='stored',kind='video',path=str(path))
                else:
                    def update(v):checkpoint(video_progress=v)
                    result=await asyncio.to_thread(fetch_video,url,archive,config['max_video_bytes'],update,config.get('video_chunk_pause_seconds',1))
                result.update(media_id=uuid.uuid4().hex,snapshot_id=p['snapshot_id'],asin=p['requested_asin'],role='video',sequence=seq,
                              linked_at=datetime.now(timezone.utc).isoformat(),
                              downloaded_at=result.get('downloaded_at') or datetime.now(timezone.utc).isoformat(),reused_existing_object=bool(old))
                p['media']=[m for m in p.get('media',[]) if not (m.get('kind')=='video' and m.get('source_url')==url)]+[result]
                shared[('video',url)]=result
                task['videos'][key]={'status':'stored','source_url':url,'sha256':result['sha256'],'product_id':p['requested_asin']}
                if sum(x.get('status')=='stored' for x in task['videos'].values())%5==0:
                    report['product_exports']=export_products(report,archive.root)
            except Exception as e:
                task['videos'][key]={'status':'failed','product_id':p['requested_asin'],'error_type':type(e).__name__,'error':str(e)}
            checkpoint()
    report['status']='partial' if task.get('videos_failed') or len(task['images_completed'])<len(report['products']) or any(x.get('status')=='link_only' for x in task['videos'].values()) else 'success'
    report['product_exports']=export_products(report,archive.root)
    checkpoint(phase='finished');render_report(report,state,archive.root)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True);p.add_argument('--plan',action='store_true')
    a=p.parse_args();config=load_config(a.config)
    root=a.report.resolve().parents[2]
    if not a.state.resolve().is_relative_to(root):raise ValueError('State directory must be inside source library')
    if a.plan:
        r=json.loads(a.report.read_text(encoding='utf-8'));print(json.dumps({'products':len(r['products']),'images':sum(len(x['parsed'].get('images',[])) for x in r['products']),'direct_video_occurrences':sum(v['kind']=='direct' for x in r['products'] for v in x['parsed'].get('videos',[]))}));return
    with worker_lock(a.state):asyncio.run(execute(a.report,config,a.state))


if __name__=='__main__':main()
