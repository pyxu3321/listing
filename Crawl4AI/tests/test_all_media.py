"""全量配置、断点下载及锁的离线测试，不访问真实网站。"""
import hashlib
import asyncio
import io
import json
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import pytest
from listing_ingest.runner import PROJECT,load_config
from listing_ingest.content import select_image_candidates
from listing_ingest.storage import LocalArchive
from listing_ingest.resumable_video import fetch_video
from listing_ingest.backfill_media import worker_lock


def test_resume_preserves_completed_hls_representation(tmp_path):
    """已核对的HLS替代表示恢复后仍完成，不再降回link_only或重复请求。"""
    from listing_ingest.backfill_media import execute
    url='https://m.media-amazon.com/media-task/main.m3u8'
    key=hashlib.sha256(('snapshot'+url).encode()).hexdigest()
    report={'run_id':'run','config':{},'status':'success','products':[{'requested_asin':'ASIN','snapshot_id':'snapshot','listing_rank':1,'parsed':{'videos':[{'kind':'manifest','url':url}]},'media':[]}],
            'media_backfill':{'images_completed':['snapshot'],'videos':{key:{'status':'covered_by_saved_representation'}}}}
    archive=LocalArchive(tmp_path);state=tmp_path/'runs/state'
    with patch('listing_ingest.backfill_media.prepare',return_value=(report,archive)),patch('listing_ingest.backfill_media.export_products',return_value={}),patch('listing_ingest.backfill_media.render_report'),patch('listing_ingest.backfill_media.fetch_video') as fetch:
        asyncio.run(execute(tmp_path/'source.json',{'max_video_bytes':100},state))
    fetch.assert_not_called()
    assert report['status']=='success'
    assert report['media_backfill']['videos'][key]['status']=='covered_by_saved_representation'


def test_all_roles_have_no_quantity_truncation():
    c=load_config(PROJECT/'config/topper-us.json')
    images=[{'role':r,'url':str(i)} for r in ('gallery','description','aplus') for i in range(100)]
    selected,budgets=select_image_candidates({'images':images},c)
    assert len(selected)==300
    assert all(x['truncated']==0 for x in budgets.values())
    assert c['max_videos_per_product'] is None and c['video_total_timeout_seconds'] is None


class Response(io.BytesIO):
    """模拟直接视频Range响应。"""
    def __init__(self,data,start,total,etag='"v1"'):
        super().__init__(data);self.status=206;self.url='https://m.media-amazon.com/test.mp4'
        self.headers={'Content-Range':f'bytes {start}-{start+len(data)-1}/{total}','ETag':etag}


def test_video_resumes_from_disk_and_keeps_validator(tmp_path):
    archive=LocalArchive(tmp_path);url='https://m.media-amazon.com/test.mp4'
    key=hashlib.sha256(url.encode()).hexdigest();folder=tmp_path/'video_queue';folder.mkdir()
    (folder/(key+'.part')).write_bytes(b'abc')
    (folder/(key+'.json')).write_text(json.dumps({'url':url,'total':6,'validator':'"v1"'}))
    class Opener:
        def open(self,request,timeout):
            assert request.get_header('Range').startswith('bytes=3-')
            assert request.get_header('If-range')=='"v1"'
            return Response(b'def',3,6)
    with patch('listing_ingest.resumable_video.build_opener',return_value=Opener()),patch('listing_ingest.resumable_video._process_video',side_effect=lambda p,a:a.persist_file(p,'video','mp4')):
        result=fetch_video(url,archive,100,pause_seconds=0)
    assert Path(result['path']).read_bytes()==b'abcdef'
    assert result['version_check']=='etag_or_last_modified'


def test_video_changed_version_is_not_concatenated(tmp_path):
    archive=LocalArchive(tmp_path);url='https://m.media-amazon.com/test.mp4';key=hashlib.sha256(url.encode()).hexdigest()
    folder=tmp_path/'video_queue';folder.mkdir();part=folder/(key+'.part');part.write_bytes(b'abc')
    (folder/(key+'.json')).write_text(json.dumps({'url':url,'total':6,'validator':'"v1"'}))
    with patch('listing_ingest.resumable_video.build_opener') as opener:
        opener.return_value.open.return_value=Response(b'def',3,6,etag='"v2"')
        with pytest.raises(ValueError,match='version changed'):fetch_video(url,archive,100,pause_seconds=0)
    assert part.read_bytes()==b'abc'


def test_permanent_http_does_not_retry_forever(tmp_path):
    with patch('listing_ingest.resumable_video.build_opener') as opener:
        opener.return_value.open.side_effect=HTTPError('https://m.media-amazon.com/test.mp4',404,'missing',{},None)
        with pytest.raises(RuntimeError,match='404'):fetch_video('https://m.media-amazon.com/test.mp4',LocalArchive(tmp_path),100,pause_seconds=0)
        assert opener.return_value.open.call_count==1


def test_total_video_size_cap_remains(tmp_path):
    with patch('listing_ingest.resumable_video.build_opener') as opener:
        opener.return_value.open.return_value=Response(b'abcdef',0,6)
        with pytest.raises(ValueError,match='byte limit'):fetch_video('https://m.media-amazon.com/test.mp4',LocalArchive(tmp_path),3,pause_seconds=0)


def test_worker_lock_prevents_duplicate_process(tmp_path):
    with worker_lock(tmp_path):
        with pytest.raises((OSError,IOError)):
            with worker_lock(tmp_path):pass


def test_range_ignored_restarts_instead_of_appending(tmp_path):
    """服务端返回200时重新下载，不将新响应拼到旧部分文件。"""
    archive=LocalArchive(tmp_path);url='https://m.media-amazon.com/test.mp4'
    key=hashlib.sha256(url.encode()).hexdigest();folder=tmp_path/'video_queue';folder.mkdir()
    (folder/(key+'.part')).write_bytes(b'old')
    (folder/(key+'.json')).write_text(json.dumps({'url':url,'total':6,'validator':'"v1"'}))
    response=Response(b'newnew',0,6,etag='"v2"');response.status=200;response.headers={'Content-Length':'6','ETag':'"v2"'}
    with patch('listing_ingest.resumable_video.build_opener') as opener,patch('listing_ingest.resumable_video._process_video',side_effect=lambda p,a:a.persist_file(p,'video','mp4')):
        opener.return_value.open.return_value=response
        result=fetch_video(url,archive,100,pause_seconds=0)
    assert Path(result['path']).read_bytes()==b'newnew'


def test_transient_failure_retries_without_total_deadline(tmp_path):
    """暂时限流后继续同一个视频，不因任务已运行很久而跳过。"""
    with patch('listing_ingest.resumable_video.build_opener') as opener,patch('listing_ingest.resumable_video.time.sleep') as sleep,patch('listing_ingest.resumable_video._process_video',side_effect=lambda p,a:a.persist_file(p,'video','mp4')):
        opener.return_value.open.side_effect=[HTTPError('https://m.media-amazon.com/test.mp4',429,'busy',{},None),Response(b'abc',0,3)]
        result=fetch_video('https://m.media-amazon.com/test.mp4',LocalArchive(tmp_path),100,pause_seconds=0)
        assert result['status']=='stored'
        assert opener.return_value.open.call_count==2
        sleep.assert_called_once()
