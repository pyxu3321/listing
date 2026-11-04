# 文件用途：本地Windows OCR派生文字与缓存；不覆盖DOM原文，不把识别文字当成已验证参数。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Local OCR derivatives; never overwrite DOM text or claim product facts."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .storage import LocalArchive


# 功能及输出：验证语言标签，优先读源图哈希缓存；Windows隐藏子进程OCR及25秒超时，返回派生文字/状态；原图不改写。
# 参数：media（媒体记录集合或单图记录）；archive（本地归档对象）；language（期望OCR语言）。
def recognize_image(media: dict, archive: LocalArchive, language: str = "en-US") -> dict:
    if not re.fullmatch(r"[A-Za-z0-9-]{2,35}", language):
        return {"status": "failed", "error": "Invalid OCR language tag"}
    recipe = "windows-ocr-2000-v1"
    cache = archive.root / "derived" / "ocr" / recipe / language / (media["sha256"] + ".json")
    if cache.is_file():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("source_sha256") == media["sha256"] and cached.get("status") in {"ready", "empty"}:
            return {**cached, "cached": True}
    if os.name != "nt":
        return {"status": "unavailable", "error": "Windows OCR backend unavailable on this OS", "source_sha256": media["sha256"]}
    shell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not shell.is_file():
        return {"status": "unavailable", "error": "Windows PowerShell OCR host unavailable", "source_sha256": media["sha256"]}
    try:
        with tempfile.TemporaryDirectory(prefix="listing-ocr-") as temporary:
            normalized = Path(temporary) / "input.png"
            with Image.open(media["path"]) as source:
                original_size = source.size
                image = source.convert("RGB")
                image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
                image.save(normalized)
            result = subprocess.run([str(shell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(Path(__file__).with_name("ocr_image.ps1")), "-ImagePath", str(normalized), "-Language", language], capture_output=True, text=True, encoding="utf-8-sig", errors="replace", timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                return {"status": "failed", "error": "Local OCR process failed", "source_sha256": media["sha256"]}
            data = json.loads(result.stdout)
            # 识别结果保留实际语言/回退和源图哈希，始终标记人工核对，不覆盖原DOM文字。
            data.update({"source_sha256": media["sha256"], "recipe": recipe, "original_width": original_size[0], "original_height": original_size[1], "coordinate_space": "ocr_input_pixels", "needs_human_review": True, "text_source": "image_ocr"})
            if data.get("status") == "ready":
                if not data.get("text", "").strip():
                    data["status"] = "empty"
                archive.persist_json(data, cache.relative_to(archive.root).as_posix())
            return data
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": "Local OCR exceeded 25 seconds", "source_sha256": media["sha256"]}
    except Exception as exc:
        return {"status": "failed", "error": f"Local OCR failed ({type(exc).__name__})", "source_sha256": media["sha256"]}
