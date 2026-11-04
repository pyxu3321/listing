# 文件用途：采集回归测试：test_storage；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
import asyncio
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from listing_ingest.storage import LocalArchive, download_media


# 功能及输出：构造本地测试输入夹具，返回HTML片段或图片字节供断言。
def png_bytes(size=(1000, 400)):
    handle = BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 0)).save(handle, "PNG")
    return handle.getvalue()


# 类职责：模拟异步下载分块，验证长度与限额。
class FakeContent:
    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    def __init__(self, blocks):
        self.blocks = blocks

    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    async def iter_chunked(self, size):
        for block in self.blocks:
            yield block


# 类职责：模拟HTTP状态、头部和异步上下文。
class FakeResponse:
    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    def __init__(self, blocks=(), status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(blocks)

    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    async def __aenter__(self):
        return self

    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    async def __aexit__(self, *args):
        return False


# 类职责：记录模拟请求并返回测试响应，不访问真实网站。
class FakeSession:
    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    def __init__(self, responses=()):
        self.responses = iter(responses)
        self.calls = []

    # 功能及输出：测试模拟对象的初始化、响应上下文或分块读取，不访问真实网络。
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


# 类职责：验证本地归档去重、完整性和路径边界。
class ArchiveTests(unittest.TestCase):
    # 验证目标：内容哈希去重不覆盖原件；仅本地夹具/模拟请求，不真实采集。
    def test_content_deduplicates_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LocalArchive(directory)
            first = archive.persist_bytes(b"original", "page", "html")
            second = archive.persist_bytes(b"original", "page", "html")
            changed = archive.persist_bytes(b"changed", "page", "html")
            self.assertFalse(first["deduplicated"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(first["path"], second["path"])
            self.assertNotEqual(first["path"], changed["path"])
            self.assertEqual(Path(first["path"]).read_bytes(), b"original")
            self.assertEqual(list(archive.temp_dir.iterdir()), [])

    # 验证目标：JSON写入保持原子性与根目录边界；仅本地夹具/模拟请求，不真实采集。
    def test_json_is_atomic_and_stays_under_root(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LocalArchive(directory)
            path = archive.persist_json({"label": "床垫"}, "runs/run1.json")
            self.assertEqual(json.loads(path.read_text("utf-8")), {"label": "床垫"})
            for invalid in ["../escape.json", Path(directory).parent / "escape.json"]:
                with self.assertRaises(ValueError):
                    archive.persist_json({}, invalid)
            with self.assertRaises(ValueError):
                archive.persist_bytes(b"x", "image", "../jpg")
            self.assertEqual(list(archive.temp_dir.iterdir()), [])

    # 验证目标：损坏的已有原件不会静默复用；仅本地夹具/模拟请求，不真实采集。
    def test_existing_corrupt_object_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = LocalArchive(directory)
            saved = archive.persist_bytes(b"source", "page", "html")
            Path(saved["path"]).write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "integrity"):
                archive.persist_bytes(b"source", "page", "html")


# 类职责：验证下载、跳转、预览和视频回退状态。
class DownloadTests(unittest.IsolatedAsyncioTestCase):
    # 功能及输出：为异步测试创建或清理临时归档目录，不接触真实素材库。
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.archive = LocalArchive(self.directory.name)

    # 功能及输出：为异步测试创建或清理临时归档目录，不接触真实素材库。
    async def asyncTearDown(self):
        self.directory.cleanup()

    # 验证目标：有效图片原件保留且预览白底有界；仅本地夹具/模拟请求，不真实采集。
    async def test_valid_image_original_preserved_preview_white_and_bounded(self):
        data = png_bytes()
        session = FakeSession([FakeResponse([data], headers={"Content-Length": str(len(data))})])
        result = await download_media(session, "https://m.media-amazon.com/images/a.jpg", self.archive)
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["mime"], "image/png")
        self.assertEqual(Path(result["path"]).read_bytes(), data)
        self.assertEqual((result["width"], result["height"]), (1000, 400))
        with Image.open(result["preview"]["path"]) as preview:
            self.assertLessEqual(max(preview.size), 640)
            self.assertGreater(min(preview.getpixel((0, 0))), 245)
        self.assertEqual(list(self.archive.temp_dir.iterdir()), [])

    # 验证目标：两个来源共用字节但保留独立引用；仅本地夹具/模拟请求，不真实采集。
    async def test_two_sources_share_bytes_but_keep_source_occurrences(self):
        data = png_bytes((20, 20))
        session = FakeSession([FakeResponse([data]), FakeResponse([data])])
        first = await download_media(session, "https://m.media-amazon.com/images/a.png", self.archive)
        second = await download_media(session, "https://m.media-amazon.com/images/b.png", self.archive)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["source_url"], second["source_url"])
        self.assertTrue(second["deduplicated"])

    # 验证目标：未知长度下载仍限制体积并清理临时文件；仅本地夹具/模拟请求，不真实采集。
    async def test_unknown_length_stream_enforces_limit_and_cleans_temp(self):
        session = FakeSession([FakeResponse([b"1234", b"5678"])])
        result = await download_media(session, "https://m.media-amazon.com/a.jpg", self.archive, max_bytes=5)
        self.assertEqual(result["status"], "failed")
        self.assertIn("byte limit", result["error"])
        self.assertEqual(list(self.archive.temp_dir.iterdir()), [])
        self.assertFalse((self.archive.root / "objects").exists())

    # 验证目标：声明长度不匹配不得归档；仅本地夹具/模拟请求，不真实采集。
    async def test_declared_length_mismatch_is_not_archived(self):
        session = FakeSession([FakeResponse([b"1234"], headers={"Content-Length": "8"})])
        result = await download_media(session, "https://m.media-amazon.com/a.jpg", self.archive)
        self.assertEqual(result["status"], "failed")
        self.assertIn("length", result["error"])

    # 验证目标：拒绝伪装为图片的HTML；仅本地夹具/模拟请求，不真实采集。
    async def test_html_masquerading_as_image_is_rejected(self):
        session = FakeSession([FakeResponse([b"<html>Access denied</html>"], headers={"Content-Type": "image/jpeg"})])
        result = await download_media(session, "https://m.media-amazon.com/a.jpg", self.archive)
        self.assertEqual(result["status"], "failed")
        self.assertIn("validation", result["error"])

    # 验证目标：不安全URL不会发给HTTP会话；仅本地夹具/模拟请求，不真实采集。
    async def test_unsafe_urls_never_reach_session(self):
        for url in [
            "file:///etc/passwd", "http://m.media-amazon.com/a.jpg", "https://127.0.0.1/a.jpg",
            "https://m.media-amazon.com.evil.example/a.jpg", "https://evilmedia-amazon.com/a.jpg",
            "https://user:secret@m.media-amazon.com/a.jpg", "https://m.media-amazon.com:8443/a.jpg",
        ]:
            with self.subTest(url=url):
                session = FakeSession()
                result = await download_media(session, url, self.archive)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(session.calls, [])
                self.assertNotIn("secret", json.dumps(result))

    # 验证目标：跳转目的地重新校验；仅本地夹具/模拟请求，不真实采集。
    async def test_redirect_destination_is_revalidated(self):
        session = FakeSession([FakeResponse(status=302, headers={"Location": "http://127.0.0.1/private?token=secret"})])
        result = await download_media(session, "https://m.media-amazon.com/a.jpg", self.archive)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(session.calls), 1)
        self.assertNotIn("secret", result["error"])

    # 验证目标：播放清单仅记链接且不下载；仅本地夹具/模拟请求，不真实采集。
    async def test_playlist_is_link_only_without_network(self):
        session = FakeSession()
        result = await download_media(session, "https://m.media-amazon.com/video.m3u8", self.archive, kind="video")
        self.assertEqual(result["status"], "link_only")
        self.assertEqual(session.calls, [])

    # 验证目标：视频文件头不等于整段验证；仅本地夹具/模拟请求，不真实采集。
    async def test_video_stream_signature_is_not_claimed_full_validation(self):
        data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100
        session = FakeSession([FakeResponse([data])])
        with patch("listing_ingest.storage.shutil.which", return_value=None), patch("listing_ingest.storage._opencv_available", return_value=False):
            result = await download_media(session, "https://m.media-amazon.com/a.mp4", self.archive, kind="video")
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["media_validation"], "container_signature_only")
        self.assertEqual(result["probe_status"], "unavailable")
        self.assertEqual(result["preview_video_status"], "not_generated")
        self.assertEqual(Path(result["path"]).read_bytes(), data)

    # 验证目标：OpenCV回退保留原件并标估算时长；仅本地夹具/模拟请求，不真实采集。
    async def test_opencv_fallback_preserves_original_and_reports_estimated_duration(self):
        data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100
        session = FakeSession([FakeResponse([data])])

        # 功能及输出：模拟来源执行或视频探测，替代真实网络/解码器以验证边界。
        def fake_probe(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            Image.new("RGB", (640, 360), "blue").save(command[-1], "JPEG")
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                "width": 1920, "height": 1080, "fps": 30.0, "frame_count": 300,
                "duration": 10.0, "duration_estimated": True, "duration_method": "frame_count/fps",
            }))

        with patch("listing_ingest.storage.shutil.which", return_value=None), patch("listing_ingest.storage._opencv_available", return_value=True), patch("listing_ingest.storage.subprocess.run", side_effect=fake_probe):
            result = await download_media(session, "https://m.media-amazon.com/a.mp4", self.archive, kind="video")
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["media_validation"], "metadata_and_first_frame")
        self.assertEqual(result["probe_engine"], "opencv")
        self.assertEqual(result["duration"], 10.0)
        self.assertTrue(result["duration_estimated"])
        self.assertEqual(result["preview_status"], "ready")
        self.assertEqual(result["preview_video_status"], "not_generated")
        self.assertEqual(Path(result["path"]).read_bytes(), data)
        with Image.open(result["preview"]["path"]) as poster:
            self.assertLessEqual(max(poster.size), 640)
        self.assertEqual(list(self.archive.temp_dir.iterdir()), [])

    # 验证目标：视频探测超时保留原件且不宣称已解码；仅本地夹具/模拟请求，不真实采集。
    async def test_opencv_timeout_keeps_original_without_claiming_decoded_video(self):
        data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100
        session = FakeSession([FakeResponse([data])])
        with patch("listing_ingest.storage.shutil.which", return_value=None), patch("listing_ingest.storage._opencv_available", return_value=True), patch("listing_ingest.storage.subprocess.run", side_effect=subprocess.TimeoutExpired("probe", 30)):
            result = await download_media(session, "https://m.media-amazon.com/a.mp4", self.archive, kind="video")
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["media_validation"], "container_signature_only")
        self.assertEqual(result["probe_status"], "timeout")
        self.assertEqual(result["preview_status"], "failed")
        self.assertNotIn("preview", result)
        self.assertTrue(Path(result["path"]).exists())
        self.assertEqual(list(self.archive.temp_dir.iterdir()), [])

    # 验证目标：预览失败仍保留验证过的原件；仅本地夹具/模拟请求，不真实采集。
    async def test_preview_failure_preserves_verified_original(self):
        session = FakeSession([FakeResponse([png_bytes((10, 10))])])
        with patch("listing_ingest.storage._image_preview", side_effect=RuntimeError("private-token")):
            result = await download_media(session, "https://m.media-amazon.com/a.png", self.archive)
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["preview_status"], "failed")
        self.assertTrue(Path(result["path"]).exists())
        self.assertNotIn("private-token", result["preview_error"])


if __name__ == "__main__":
    unittest.main()
