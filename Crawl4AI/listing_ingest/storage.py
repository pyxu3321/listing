# 文件用途：本地内容哈希归档与媒体下载：验证地址/体积/格式、保存原件及预览、隔离失败状态和源引用。
# 2026-11-03：支持全量媒体配置与视频无总时限下载。
"""Local content-addressed media archive for the phase-one collection pilot.

Files and source observations have different lifetimes. This module stores bytes;
the caller must retain every source/snapshot association even when bytes dedupe.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit
import warnings

import aiohttp
from PIL import Image, ImageOps


DEFAULT_ALLOWED_HOSTS = (
    "m.media-amazon.com",
    "images-na.ssl-images-amazon.com",
    "*.media-amazon.com",
    "*.ssl-images-amazon.com",
)
DEFAULT_IMAGE_LIMIT = 25 * 1024 * 1024
DEFAULT_VIDEO_LIMIT = 150 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
    "TIFF": ("tiff", "image/tiff"),
    "BMP": ("bmp", "image/bmp"),
    "AVIF": ("avif", "image/avif"),
}


# 类职责：受控媒体异常，错误消息避免泄露远程URL中的凭据。
class MediaError(ValueError):
    """Messages are deliberately fixed and never contain remote URL tokens."""


# 功能及输出：分块计算文件SHA256与字节数，不将整个大文件一次读入内存。
# 参数：path（本地文件路径）。
def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            length += len(block)
    return digest.hexdigest(), length


# 类职责：本地对象归档器，统一路径边界、内容去重及完整性。
class LocalArchive:
    # 功能及输出：确定归档根目录并创建库根/tmp目录；不会开始下载。
    # 参数：root（库根目录）。
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self._contained("tmp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # 功能及输出：将相对路径解析到归档根内，拒绝绝对路径、盘符及越界。
    # 参数：relative_path（库根内相对路径）。
    def _contained(self, relative_path: Path | str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or relative.drive:
            raise ValueError("Archive paths must be relative")
        target = (self.root / relative).resolve()
        if target == self.root or not target.is_relative_to(self.root):
            raise ValueError("Archive path escapes root")
        return target

    # 功能及输出：在归档tmp内创建唯一临时文件，再校验目录边界。
    # 参数：suffix（临时文件后缀）。
    def _temporary(self, suffix: str = ".part") -> Path:
        # Recheck containment in case a directory was replaced with a symlink.
        temp_dir = self._contained("tmp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="media-", suffix=suffix, dir=temp_dir)
        os.close(descriptor)
        return Path(name)

    # 功能及输出：按内容哈希保存文件并校验已存在原件；返回归档元数据，不删除输入文件。
    # 参数：source（原文件或原报告路径）；kind（图片/视频或关联类型）；extension（对象扩展名）。
    def persist_file(self, source: Path | str, kind: str, extension: str) -> dict[str, Any]:
        """Copy a file without reading it all into memory; leave source intact."""
        extension = extension.lstrip(".").lower()
        if not re.fullmatch(r"[a-z0-9]{1,12}", extension):
            raise ValueError("Invalid object extension")
        source = Path(source)
        digest, length = _hash_file(source)
        relative = Path("objects") / digest[:2] / f"{digest}.{extension}"
        target = self._contained(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._contained(relative)
        deduplicated = target.exists()
        if deduplicated:
            if _hash_file(target) != (digest, length):
                raise ValueError("Existing archived object failed integrity check")
        else:
            temporary = self._temporary()
            try:
                with source.open("rb") as reader, temporary.open("wb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                if _hash_file(temporary) != (digest, length):
                    raise ValueError("Source changed during archive copy")
                # Content-derived names mean concurrent writers have equal bytes.
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return {
            "sha256": digest,
            "relative_path": relative.as_posix(),
            "path": str(target),
            "bytes": length,
            "kind": kind,
            "deduplicated": deduplicated,
        }

    # 功能及输出：先写临时文件，再复用文件归档；完成后清理临时副本。
    # 参数：data（待保存内容）；kind（图片/视频或关联类型）；extension（对象扩展名）。
    def persist_bytes(self, data: bytes, kind: str, extension: str) -> dict[str, Any]:
        temporary = self._temporary()
        try:
            temporary.write_bytes(data)
            return self.persist_file(temporary, kind, extension)
        finally:
            temporary.unlink(missing_ok=True)

    # 功能及输出：在归档根内以临时文件原子替换JSON，拒绝NaN，返回目标路径。
    # 参数：data（待保存内容）；relative_path（库根内相对路径）。
    def persist_json(self, data: Any, relative_path: Path | str) -> Path:
        target = self._contained(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._contained(relative_path)
        temporary = self._temporary(".json")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


# 功能及输出：保留来源查询便于追溯；如URL嵌入用户名密码则移除敏感部分。
# 参数：url（待处理来源地址）。
def _safe_source(url: str) -> str:
    """Keep source queries for provenance, but do not echo embedded credentials."""
    try:
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None:
            return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
    except ValueError:
        return "[invalid URL]"
    return url


# 功能及输出：校验媒体HTTPS、域名白名单、端口与非法字符，拒绝IP字面量和凭据URL。
# 参数：url（待处理来源地址）；allowed_hosts（允许媒体域名清单）。
def _validate_url(url: str, allowed_hosts: Iterable[str]) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise MediaError("Invalid URL characters")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme.lower() != "https":
            raise MediaError("Only HTTPS media downloads are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise MediaError("Credential-bearing URLs are not allowed")
        if parsed.port not in (None, 443):
            raise MediaError("Only the standard HTTPS port is allowed")
    except ValueError as exc:
        if isinstance(exc, MediaError):
            raise
        raise MediaError("Invalid media URL") from None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise MediaError("IP-literal media URLs are not allowed")
    accepted = False
    for item in allowed_hosts:
        item = item.lower().rstrip(".")
        if item.startswith("*."):
            accepted |= host.endswith(item[1:]) and host != item[2:]
        else:
            accepted |= host == item
    if not host or not accepted:
        raise MediaError("Media host is not allowlisted")
    return url


# 功能及输出：验证图片解码、格式和尺寸，返回扩展名、MIME、宽高。
# 参数：path（本地文件路径）。
def _image_info(path: Path) -> tuple[str, str, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise MediaError("Image exceeds the pixel limit")
                if image.format not in IMAGE_FORMATS:
                    raise MediaError("Image format is not supported")
                extension, mime = IMAGE_FORMATS[image.format]
                image.verify()
            # verify() is not a complete pixel decode for every image format.
            with Image.open(path) as image:
                image.seek(0)
                image.load()
        return extension, mime, width, height
    except MediaError:
        raise
    except Exception:
        raise MediaError("Image validation failed") from None


# 功能及输出：由已验证原图制作派生预览并归档；不覆盖原件。
# 参数：path（本地文件路径）；archive（本地归档对象）。
def _image_preview(path: Path, archive: LocalArchive) -> dict[str, Any]:
    temporary = archive._temporary(".jpg")
    try:
        with Image.open(path) as original:
            original.seek(0)
            image = ImageOps.exif_transpose(original).convert("RGBA")
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            background.save(temporary, "JPEG", quality=85)
            width, height = background.size
        result = archive.persist_file(temporary, "image_preview", "jpg")
        result.update({"width": width, "height": height, "mime": "image/jpeg", "recipe": "jpeg-white-640-v1"})
        return result
    finally:
        temporary.unlink(missing_ok=True)


# 功能及输出：校验并归档图片原件和预览；预览失败不抹掉已保存原件。
# 参数：path（本地文件路径）；archive（本地归档对象）。
def _process_image(path: Path, archive: LocalArchive) -> dict[str, Any]:
    extension, mime, width, height = _image_info(path)
    result = archive.persist_file(path, "image", extension)
    result.update({"mime": mime, "width": width, "height": height, "media_validation": "decoded_first_frame"})
    try:
        result["preview"] = _image_preview(path, archive)
        result["preview_status"] = "ready"
    except Exception as exc:
        # A derived-file problem must not discard a verified original.
        result.update({"preview_status": "failed", "preview_error": f"Preview generation failed ({type(exc).__name__})"})
    return result


# 功能及输出：Windows使用隐藏子进程标记，其他系统返回空选项。
def _subprocess_options() -> dict[str, Any]:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


# 功能及输出：仅探测可选OpenCV能力，不在当前进程启动解码。
def _opencv_available() -> bool:
    """Optional capability check; do not import a video decoder in this process."""
    try:
        return importlib.util.find_spec("cv2") is not None
    except (ImportError, ValueError):
        return False


# Keep decoding isolated: VideoCapture backend timeouts differ by OpenCV build.
# subprocess.run's timeout below bounds startup, open, one read, and JPEG output.
_OPENCV_PROBE_SCRIPT = r"""
import json
import math
import sys
import cv2

cv2.setNumThreads(1)
capture = cv2.VideoCapture()
try:
    if not capture.open(sys.argv[1]):
        raise RuntimeError('Video open failed')
    reported_width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    reported_height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if (math.isfinite(reported_width) and math.isfinite(reported_height)
            and reported_width * reported_height > 40000000):
        raise RuntimeError('Video exceeds pixel limit')
    success, frame = capture.read()
    if not success or frame is None or frame.size == 0:
        raise RuntimeError('First frame decode failed')
    height, width = frame.shape[:2]
    if width < 1 or height < 1 or width * height > 40000000:
        raise RuntimeError('Video exceeds pixel limit')
    scale = min(1.0, 640.0 / width, 640.0 / height)
    if scale < 1.0:
        frame = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                           interpolation=cv2.INTER_AREA)
    if not cv2.imwrite(sys.argv[2], frame, [cv2.IMWRITE_JPEG_QUALITY, 85]):
        raise RuntimeError('Poster write failed')
    result = {'width': width, 'height': height}
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if math.isfinite(fps) and 0 < fps <= 1000:
        result['fps'] = fps
    if math.isfinite(count) and count > 0:
        result['frame_count'] = int(count)
    if 'fps' in result and 'frame_count' in result:
        duration = result['frame_count'] / result['fps']
        if math.isfinite(duration) and duration > 0:
            result.update(duration=duration, duration_estimated=True,
                          duration_method='frame_count/fps')
    print(json.dumps(result, allow_nan=False))
except Exception:
    sys.exit(2)
finally:
    capture.release()
"""


# 功能及输出：隔离子进程获取视频元数据和首帧；不验证整段视频/音频或实测时长。
# 参数：path（本地文件路径）；archive（本地归档对象）。
def _opencv_metadata_and_poster(path: Path, archive: LocalArchive) -> dict[str, Any]:
    poster = archive._temporary(".jpg")
    try:
        environment = os.environ.copy()
        environment["OPENCV_LOG_LEVEL"] = "SILENT"
        result = subprocess.run(
            [sys.executable, "-c", _OPENCV_PROBE_SCRIPT, str(path), str(poster)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=environment, **_subprocess_options(),
        )
        if result.returncode:
            raise MediaError("OpenCV could not decode the first video frame")
        info = json.loads(result.stdout)
        if not isinstance(info, dict):
            raise MediaError("OpenCV returned invalid metadata")
        for key in ("width", "height"):
            value = info.get(key)
            if not isinstance(value, int) or value < 1:
                raise MediaError("OpenCV returned invalid video dimensions")
        if info["width"] * info["height"] > MAX_IMAGE_PIXELS:
            raise MediaError("Video exceeds the pixel limit")
        _, _, width, height = _image_info(poster)
        if max(width, height) > 640:
            raise MediaError("OpenCV poster exceeds the preview size")
        preview = archive.persist_file(poster, "video_poster", "jpg")
        preview.update({"width": width, "height": height, "mime": "image/jpeg", "recipe": "opencv-first-frame-640-v1"})
        return {
            **info,
            "media_validation": "metadata_and_first_frame",
            "validation_scope": "First frame only; full video and audio streams are not validated",
            "probe_status": "ready",
            "probe_engine": "opencv",
            "preview_status": "ready",
            "preview_engine": "opencv",
            "preview": preview,
        }
    finally:
        poster.unlink(missing_ok=True)


# 功能及输出：归档视频原件并尝试元数据/首帧；保留估算值、未知或探测失败状态。
# 参数：path（本地文件路径）；archive（本地归档对象）。
def _process_video(path: Path, archive: LocalArchive) -> dict[str, Any]:
    with path.open("rb") as handle:
        signature = handle.read(64)
    if len(signature) >= 12 and signature[4:8] == b"ftyp":
        extension, mime = "mp4", "video/mp4"
    elif signature.startswith(b"\x1a\x45\xdf\xa3"):
        extension, mime = "webm", "video/webm"
    else:
        raise MediaError("Unsupported or invalid video container signature")

    metadata: dict[str, Any] = {
        "mime": mime,
        "media_validation": "container_signature_only",
        "probe_status": "unavailable",
        "preview_status": "not_generated",
        "preview_video_status": "not_generated",
    }
    probe = shutil.which("ffprobe")
    if probe:
        try:
            result = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,duration", "-of", "json", str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                **_subprocess_options(),
            )
            if result.returncode:
                raise MediaError("Video probe rejected the file")
            info = json.loads(result.stdout)
            stream = next((item for item in info.get("streams", []) if item.get("codec_type") == "video"), None)
            if not stream:
                raise MediaError("No video stream found")
            metadata.update({"probe_status": "ready", "probe_engine": "ffprobe", "media_validation": "container_and_stream_metadata", "width": stream.get("width"), "height": stream.get("height")})
            duration = info.get("format", {}).get("duration", stream.get("duration"))
            if duration is not None:
                duration = float(duration)
                if math.isfinite(duration) and duration >= 0:
                    metadata["duration"] = duration
        except MediaError:
            raise
        except subprocess.TimeoutExpired:
            metadata.update({"probe_status": "timeout", "probe_error": "Video metadata probe timed out"})
        except Exception:
            raise MediaError("Video metadata probe failed") from None

    metadata.update(archive.persist_file(path, "video", extension))
    encoder = shutil.which("ffmpeg")
    if (not probe or not encoder) and _opencv_available():
        try:
            details = _opencv_metadata_and_poster(path, archive)
            if metadata.get("probe_engine") == "ffprobe" and "duration" in metadata:
                # Keep ffprobe's container duration when available, separately
                # retain the OpenCV estimate instead of replacing its provenance.
                details["duration"] = metadata["duration"]
                details["duration_estimated"] = False
                details["duration_method"] = "ffprobe_container_metadata"
                details["probe_engine"] = "ffprobe+opencv"
            metadata.update(details)
            return metadata
        except subprocess.TimeoutExpired:
            metadata.update({"probe_status": "timeout", "probe_engine": "opencv", "preview_status": "failed", "preview_error": "OpenCV first-frame probe timed out"})
        except Exception as exc:
            metadata.update({"probe_status": "failed", "probe_engine": "opencv", "preview_status": "failed", "preview_error": f"OpenCV first-frame probe failed ({type(exc).__name__})"})
    if not encoder:
        metadata.setdefault("preview_error", "FFmpeg and OpenCV are unavailable; original archived without poster or preview video")
        return metadata
    poster = archive._temporary(".jpg")
    try:
        result = subprocess.run(
            [encoder, "-v", "error", "-y", "-i", str(path), "-frames:v", "1", "-vf", "scale=w='min(640,iw)':h=-2", str(poster)],
            capture_output=True, timeout=45, **_subprocess_options(),
        )
        if result.returncode:
            raise MediaError("Video poster generation failed")
        _, _, width, height = _image_info(poster)
        metadata["preview"] = archive.persist_file(poster, "video_poster", "jpg")
        metadata["preview"].update({"width": width, "height": height, "mime": "image/jpeg", "recipe": "first-frame-640-v1"})
        metadata["preview_status"] = "ready"
    except Exception as exc:
        metadata.update({"preview_status": "failed", "preview_error": f"Video poster generation failed ({type(exc).__name__})"})
    finally:
        poster.unlink(missing_ok=True)
    return metadata


# 功能及输出：下载单个原始媒体、限制体积并复核跳转目的地；返回归档/失败/仅链接状态；HLS、blob不假装直接视频已下载。
# 参数：session（HTTP客户端会话）；url（待处理来源地址）；archive（本地归档对象）；kind（图片/视频或关联类型）；max_bytes（本次媒体字节上限）；allowed_hosts（允许媒体域名清单）；timeout_seconds（普通单媒体请求超时秒数）。
async def download_media(
    session: aiohttp.ClientSession,
    url: str,
    archive: LocalArchive,
    kind: str = "image",
    max_bytes: int | None = None,
    *,
    allowed_hosts: Iterable[str] | None = None,
    timeout_seconds: float | None = 60,
) -> dict[str, Any]:
    """Download one original and optional preview, with explicit partial states.

    Files are content-deduplicated; this result is still one source occurrence.
    Only direct MP4/WebM files are archived as video. Playlists need a separate
    source adapter and are recorded as links. This function never follows them.
    """
    output: dict[str, Any] = {"source_url": _safe_source(url), "kind": kind}
    temporary: Path | None = None
    try:
        if kind not in {"image", "video"}:
            raise MediaError("Unsupported media kind")
        limit = max_bytes if max_bytes is not None else (DEFAULT_VIDEO_LIMIT if kind == "video" else DEFAULT_IMAGE_LIMIT)
        if limit <= 0:
            raise MediaError("Media byte limit must be positive")
        hosts = tuple(allowed_hosts) if allowed_hosts is not None else DEFAULT_ALLOWED_HOSTS
        if kind == "video" and url.lower().startswith("blob:"):
            return {**output, "status": "link_only", "error": "Browser blob URL requires a source adapter"}
        current = _validate_url(url, hosts)
        for redirect_count in range(5):
            suffix = Path(urlsplit(current).path).suffix.lower()
            if kind == "video" and suffix in {".m3u8", ".mpd"}:
                return {**output, "status": "link_only", "error": "Streaming playlist requires a source adapter"}
            async with session.get(
                current, allow_redirects=False,
                # null取消单视频总时限，保留无数据读取超时，避免死连接。
                timeout=aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=60, sock_read=60 if timeout_seconds is None else min(timeout_seconds, 20)),
                headers={"Accept-Encoding": "identity"}, auto_decompress=False,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    if redirect_count == 4:
                        raise MediaError("Too many media redirects")
                    location = response.headers.get("Location")
                    if not location:
                        raise MediaError("Redirect is missing a destination")
                    current = _validate_url(urljoin(current, location), hosts)
                    continue
                if response.status != 200:
                    raise MediaError(f"Media request returned HTTP {response.status}")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if kind == "video" and content_type in {"application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml", "audio/mpegurl"}:
                    return {**output, "status": "link_only", "error": "Streaming playlist requires a source adapter"}
                declared = response.headers.get("Content-Length")
                try:
                    declared_size = int(declared) if declared is not None else None
                except ValueError:
                    raise MediaError("Invalid media content length") from None
                if declared_size is not None and (declared_size < 0 or declared_size > limit):
                    raise MediaError("Media exceeds the byte limit")
                temporary = archive._temporary()
                length = 0
                with temporary.open("wb") as handle:
                    async for block in response.content.iter_chunked(64 * 1024):
                        length += len(block)
                        if length > limit:
                            raise MediaError("Media exceeds the byte limit")
                        handle.write(block)
                if length == 0:
                    raise MediaError("Media response was empty")
                if declared_size is not None and length != declared_size:
                    raise MediaError("Media content length did not match the downloaded file")
            processor = _process_image if kind == "image" else _process_video
            stored = await asyncio.to_thread(processor, temporary, archive)
            return {**output, **stored, "status": "stored"}
        raise MediaError("Media redirect handling failed")
    except MediaError as exc:
        return {**output, "status": "failed", "error": str(exc)}
    except Exception as exc:
        return {**output, "status": "failed", "error": f"Media download failed ({type(exc).__name__})"}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
