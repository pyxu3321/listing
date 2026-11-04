"""本地界面的 HTTP 边界测试，不依赖真实素材或在线模型。"""
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from listing_stage3.web import Handler


class FakeApplication:
    def __init__(self, path):
        self.media = {'known': path}
        self.records = {'version': {}}

    def catalogue(self):
        return {'listings': []}

    def detail(self, version):
        return {'listing_version_id': version}

    def search(self, body):
        return body


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'clip.mp4'
        cls.path.write_bytes(b'0123456789')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.app = FakeApplication(cls.path)
        cls.server.web_root = Path(cls.temp.name)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def fetch(self, path, data=None, **headers):
        return urlopen(Request(self.base + path, data=data, headers=headers), timeout=5)

    def test_video_range_and_suffix(self):
        with self.fetch('/media/known', Range='bytes=2-5') as r:
            self.assertEqual((r.status, r.headers['Content-Range'], r.read()), (206, 'bytes 2-5/10', b'2345'))
        with self.fetch('/media/known', Range='bytes=-3') as r:
            self.assertEqual(r.read(), b'789')

    def test_invalid_range(self):
        with self.assertRaises(HTTPError) as error:
            self.fetch('/media/known', Range='bytes=20-30')
        self.assertEqual(error.exception.code, 416)

    def test_unknown_media_and_traversal(self):
        for path in ('/media/C:/Windows/win.ini', '/media/../known', '/api/listings/missing'):
            with self.assertRaises(HTTPError) as error:
                self.fetch(path)
            self.assertEqual(error.exception.code, 404)

    def test_foreign_host_and_origin(self):
        with self.assertRaises(HTTPError) as error:
            self.fetch('/api/library', Host='untrusted.example')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.fetch('/api/search', b'{}', Origin='https://untrusted.example', **{'Content-Type':'application/json'})
        self.assertEqual(error.exception.code, 403)

    def test_json_post_and_bad_body(self):
        with self.fetch('/api/search', b'{"request":{}}', **{'Content-Type':'application/json'}) as r:
            self.assertEqual(json.load(r), {'request':{}})
        for payload in (b'[]', b'broken'):
            with self.assertRaises(HTTPError) as error:
                self.fetch('/api/search', payload, **{'Content-Type':'application/json'})
            self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
