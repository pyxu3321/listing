"""本机测试界面：复用现有整体匹配，不改变算法或自动选取生成组件。"""
import argparse
from copy import deepcopy
import json
import mimetypes
from pathlib import Path
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit

from .encoder import create
from .library import load, read
from .matcher import match, request_query


class Application:
    """启动时读取一次库并释放数据库；图片仅通过已登记的组件编号访问。"""

    def __init__(self, config_path):
        self.config = read(config_path)
        self.listings, self.inventory = load(self.config['library_indexes'], self.config['encoder']['stage2_project'])
        self.records = {x['listing_version_id']: x for x in self.listings}
        self.media = {}
        self.lock = Lock()
        self.encoder = None  # 浏览库不需要模型在线，第一次匹配才连接 Ollama。
        for record in self.listings:
            for part in record['components']:
                asset = part.get('asset') or {}
                if asset.get('local_path'):
                    path = Path(asset['local_path']).resolve()
                    if path.is_file():
                        self.media[part['part_id']] = path

    def part(self, part):
        """返回原始文本及审阅特征，向量和任意本机文件路径不发送到页面。"""
        keys = ('part_id', 'role', 'entity_kind', 'source_text', 'features', 'reference',
                'controls', 'identity_scope', 'is_main_image', 'index_enabled')
        result = {k: part.get(k) for k in keys}
        result['media_url'] = '/media/' + part['part_id'] if part['part_id'] in self.media else None
        return result

    def card(self, record):
        parts = record['components']
        title = next((x['source_text'] for x in parts if x['role'] == 'title'), record['identity']['product_id'])
        hero = next((x for x in parts if x['role'] == 'main_image' and x['part_id'] in self.media), None)
        return {'listing_version_id': record['listing_version_id'], 'identity': record['identity'],
                'title': title, 'historical_rank': record['overall_features'].get('historical_rank'),
                'preview_url': '/media/' + hero['part_id'] if hero else None,
                'counts': {kind: sum(p['entity_kind'] == kind for p in parts) for kind in ('image', 'video', 'text')},
                'structured_features': record.get('structured_features'),
                'approval_status': record.get('approval_status')}

    def catalogue(self):
        return {'listings': [self.card(r) for r in self.listings], 'inventory': self.inventory,
                'model': self.config['encoder']['model'], 'retrieval': self.config['retrieval'],
                'mode': 'vector_only_no_llm_reranking', 'component_count': sum(len(r['components']) for r in self.listings),
                'feature_recipes': sorted({r['overall_embedding']['recipe'] for r in self.listings})}

    def detail(self, version):
        record = self.records[version]
        return {**self.card(record), 'components': [self.part(p) for p in record['components']],
                'overall_features': record['overall_features'], 'source': record['library_source']}

    def search(self, body):
        request = body.get('request')
        if not isinstance(request, dict):
            raise ValueError('request 必须是对象')
        request_query(request)  # 无内容的输入先拒绝，不为了错误请求连接模型。
        count = body.get('top_k', 3)
        if type(count) is not int or not 1 <= count <= 50:
            raise ValueError('候选数量须为 1–50 的整数')
        settings = deepcopy(self.config['retrieval'])
        settings['whole_top_k'] = count
        settings['match_components'] = False
        # 原始排序作为显式实验选项，不把它写回默认配置。
        if body.get('raw_order', False) is not False:
            if body['raw_order'] is not True:
                raise ValueError('raw_order 必须为布尔值')
            settings['rank_tiebreak_tolerance'] = 0
        with self.lock:
            if self.encoder is None:
                self.encoder = create(self.config['encoder'])
            result = match(request, self.listings, settings, self.encoder)
        for candidate in result['whole_candidates']:
            candidate.update(self.card(self.records[candidate['listing_version_id']]))
        return {'result': result, 'request': request, 'settings': settings,
                'mode': 'vector_only_no_llm_reranking'}


class Handler(BaseHTTPRequestHandler):
    """仅监听回环地址；拒绝跨来源请求和任意路径媒体读取。"""
    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self.valid_host():
            return self.send_json({'error': 'Host not allowed'}, 403)
        path = urlsplit(self.path).path
        if path == '/api/library':
            return self.send_json(self.server.app.catalogue())
        if path.startswith('/api/listings/'):
            version = path.removeprefix('/api/listings/')
            if version not in self.server.app.records:
                return self.send_json({'error': 'Listing 不存在'}, 404)
            return self.send_json(self.server.app.detail(version))
        if path.startswith('/media/'):
            target = self.server.app.media.get(path.removeprefix('/media/'))
            if target is None or not target.is_file():
                return self.send_json({'error': '素材不存在'}, 404)
            return self.file(target, ranges=True)
        target = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}.get(path)
        if target:
            return self.file(self.server.web_root / target)
        return self.send_json({'error': 'Not found'}, 404)

    def file(self, path, ranges=False):
        """视频支持 HTTP Range，拖动播放无需重传整个视频。"""
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get('Range') if ranges else None
        if header:
            found = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
            if found and any(found.groups()):
                left, right = found.groups()
                if left:
                    start, end = int(left), min(int(right), size - 1) if right else size - 1
                else:
                    start = max(0, size - int(right))
                status = 206
            else:
                start = size
            if start > end or start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        self.send_response(status)
        mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') or mime in ('application/javascript',) else ''))
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if ranges:
            self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self):
        if not self.valid_host():
            return self.send_json({'error': 'Host not allowed'}, 403)
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://localhost:{self.server.server_port}', f'http://127.0.0.1:{self.server.server_port}'}:
            return self.send_json({'error': 'Cross-origin request rejected'}, 403)
        if urlsplit(self.path).path != '/api/search':
            return self.send_json({'error': 'Not found'}, 404)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json({'error': '请发送 JSON'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('请求大小不正确')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('请求必须是对象')
            return self.send_json(self.server.app.search(body))
        except (ValueError, KeyError, TypeError) as error:
            return self.send_json({'error': str(error)}, 400)
        except Exception as error:
            # 本地模型不可用、配置故障等要明确显示；前端保留已输入内容。
            return self.send_json({'error': f'匹配未完成：{error}。请确认 Ollama 已启动且模型与特征库一致。'}, 503)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument('--config', type=Path, default=root / 'config/runtime.json')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    app = Application(args.config)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.app, server.web_root = app, root / 'web'
    print(f'Listing Studio: http://127.0.0.1:{args.port} ({len(app.listings)} listings)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
