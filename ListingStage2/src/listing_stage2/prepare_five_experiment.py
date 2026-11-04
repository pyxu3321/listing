"""冻结前五名实验输入并生成核对图；不调用付费API、不代替视觉分析。

运行后在独立实验目录保存报告副本、组件任务和联系图。视频按8个时间点
抽帧供GPT检查；抽帧不代表已观看连续视频或转录音频。补充HLS记录须匹配
商品、快照与文件哈希，禁止仅按历史排名把其他视频挂到当前商品。
"""
from pathlib import Path
import hashlib
import json
import argparse
from PIL import Image, ImageDraw, ImageOps
import cv2
from .features import from_report
from .listing_bundles import digest
from .storage import write


def prepare(source, output, supplemental=None):
    """冻结报告并整理五套组件；返回每套联系图及待审阅任务的路径。

    source：第一阶段报告；output：未使用的实验目录；supplemental：HLS下载记录。
    原始报告保持不变。输出的source_report.json是明确标注过的实验副本。
    """
    output=Path(output)
    if output.exists():
        raise ValueError('Use a fresh experiment directory')
    raw=Path(source).read_bytes(); report=json.loads(raw)
    report['products']=[p for p in report['products'] if p.get('listing_rank') in range(1,6)]
    if len(report['products'])!=5:
        raise ValueError('Exactly five captured products required')
    report['experiment_provenance']={'original_report':str(source),'original_report_capture_sha256':hashlib.sha256(raw).hexdigest(),'scope':'captured_first_five_with_explicit_supplement'}
    if supplemental:
        record=json.loads(Path(supplemental).read_text(encoding='utf-8'))
        product=next(p for p in report['products'] if p['requested_asin']==record['asin'] and p['snapshot_id']==record['snapshot_id'])
        if hashlib.sha256(Path(record['export_path']).read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('Supplemental video hash mismatch')
        if not any(m.get('sha256')==record['sha256'] for m in product['media']):
            product['media'].append({**record,'supplemental_record':str(supplemental)})
        report['experiment_provenance']['supplemental_record']=str(supplemental)
    write(output/'source_report.json',report)
    result=[]
    for product in sorted(report['products'],key=lambda p:p['listing_rank']):
        rank=product['listing_rank']; directory=output/f'rank{rank}'; directory.mkdir()
        bundle=from_report(output/'source_report.json',rank)
        for m in product['media']:
            if m.get('kind')!='video' or m.get('status')!='stored':continue
            path=Path(m.get('export_path') or m['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=m['sha256']:raise ValueError('Video hash mismatch')
            bundle['parts'].append({'part_id':digest(['video',m['sha256'],bundle['identity']]),'role':'video','entity_kind':'video','source_text':None,'features':{},'reference':{'snapshot_id':product['snapshot_id'],'source_url':m['source_url'],'asset_sha256':m['sha256']},'asset':{'local_path':str(path),'asset_sha256':m['sha256']},'is_main_image':False,'eligible_for_aggregate':True,'module_placements':[]})
        bundle['coverage']['video_status']='pending_sampled_frame_analysis_audio_not_transcribed'
        bundle['bundle_id']=digest([bundle['identity'],bundle['parts']])
        write(directory/'task.json',bundle)
        cards=[]
        for i,p in enumerate(bundle['parts']):
            if p['entity_kind']=='image':
                with Image.open(p['asset']['local_path']) as im: image=im.convert('RGB')
                cards.append((f"part {i} | {p['role']} | {p['part_id'][:8]}",image))
            elif p['entity_kind']=='video':
                cap=cv2.VideoCapture(p['asset']['local_path']);n=cap.get(cv2.CAP_PROP_FRAME_COUNT);fps=cap.get(cv2.CAP_PROP_FPS)
                frames=[];timestamps=[]
                for j in range(8):
                    frame_index=round((n-1)*(j+.5)/8);cap.set(cv2.CAP_PROP_POS_FRAMES,frame_index);ok,frame=cap.read()
                    if not ok:raise ValueError('Video sample failed')
                    stamp=round(frame_index/fps,2);timestamps.append(stamp)
                    image=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                    frames.append((f'part {i} video | {stamp}s',image))
                cap.release(); sheet(frames,directory/f'video-part{i}.jpg')
                p['sampled_frame_evidence']={'sample_count':8,'timestamps_seconds':timestamps,'contact_sheet':str(directory/f'video-part{i}.jpg'),'audio_transcribed':False}
        sheet(cards,directory/'images.jpg')
        write(directory/'task.json',bundle)
        result.append({'rank':rank,'asin':bundle['identity']['product_id'],'components':len(bundle['parts']),'images':len(cards),'directory':str(directory)})
    write(output/'preparation.json',result)
    return result


def sheet(cards,path):
    """生成原图缩略联系图用于浏览；不编辑、替代或覆盖归档原件。"""
    width,height=400,320;cols=4;rows=(len(cards)+cols-1)//cols
    image=Image.new('RGB',(width*cols,height*rows),'#eeeeee');draw=ImageDraw.Draw(image)
    for i,(label,im) in enumerate(cards):
        x=(i%cols)*width;y=(i//cols)*height
        thumb=ImageOps.contain(im,(width-12,height-35))
        image.paste(thumb,(x+(width-thumb.width)//2,y+28+(height-35-thumb.height)//2))
        draw.text((x+8,y+6),label,fill='black')
    image.save(path,quality=92)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--supplemental',type=Path)
    a=parser.parse_args();print(json.dumps(prepare(a.report,a.output,a.supplemental),ensure_ascii=False,indent=2))
