# 文件用途：商品内部有界并发下载图库/普通详情/A+及视频，详情图可做本地OCR，写检查点及完整性状态。
# 2026-11-03：支持全量媒体配置与视频无总时限下载。
"""Collect each image role independently; OCR only detail-image derivatives."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from .content import audit_content, select_image_candidates
from .ocr import recognize_image
from .storage import download_media


# 功能及输出：选择各分区候选，限并发下载、调用详情OCR、保存检查点并计算partial/ok，返回更新后的商品记录。
# 参数：product（当前商品快照记录）；config（规范化采集配置）；archive（本地归档对象）；session（HTTP客户端会话）；checkpoint（可选进度保存回调）；shared_downloads（跨商品复用的下载缓存）。
async def collect_product_media(product, config, archive, session, checkpoint=None, shared_downloads=None):
    parsed = product["parsed"]
    images, budgets = select_image_candidates(parsed, config)
    product["image_budgets"] = budgets
    candidates = [("image", image) for image in images]
    # 视频由独立额度控制，与图库只取4张无关；0表示常规流程不下载视频。
    candidates += [("video", video) for video in parsed.get("videos", [])[:config["max_videos_per_product"]]]
    existing = {(m["kind"], m["source_url"], m.get("role", "gallery")): m for m in product.get("media", [])}
    cache = shared_downloads if shared_downloads is not None else {}
    # 并发仅作用于当前商品媒体；商品详情队列仍由runner按排名顺序处理。
    semaphore = asyncio.Semaphore(config.get("media_concurrency", 3))
    video_semaphore = asyncio.Semaphore(1)

    # 功能及输出：内部单媒体任务：复用已存原件或缓存，针对暂时性错误至多补试一次，保留独立来源与模块位置。
    # 参数：sequence（来源顺序）；kind（图片/视频或关联类型）；candidate（媒体候选）。
    async def collect(sequence, kind, candidate):
        async with semaphore:
            role = candidate.get("role", "video" if kind == "video" else "gallery")
            key = (kind, candidate["url"], role)
            entry = existing.get(key)
            if entry is None or entry.get("status") != "stored":
                cached = cache.get((kind, candidate["url"]))
                timeout = config.get("video_total_timeout_seconds",60) if kind == "video" else 60
                if cached:
                    downloaded = dict(cached)
                elif kind == "video":
                    async with video_semaphore:
                        downloaded = await download_media(session,candidate["url"],archive,kind=kind,max_bytes=config["max_video_bytes"],timeout_seconds=timeout)
                else:
                    downloaded = await download_media(session,candidate["url"],archive,kind=kind,max_bytes=config["max_image_bytes"])
                if downloaded.get("status") == "failed" and any(token in downloaded.get("error", "") for token in ("Timeout", "HTTP 429", "HTTP 503", "Connection")):
                    await asyncio.sleep(2)
                    if kind == "video":
                        async with video_semaphore:
                            downloaded = await download_media(session,candidate["url"],archive,kind=kind,max_bytes=config["max_video_bytes"],timeout_seconds=timeout)
                    else:
                        downloaded = await download_media(session,candidate["url"],archive,kind=kind,max_bytes=config["max_image_bytes"])
                    downloaded["retry_count"] = 1
                if downloaded.get("status") == "stored":
                    cache[(kind, candidate["url"])] = dict(downloaded)
                if entry is not None:
                    product["media"].remove(entry)
                entry = {**downloaded, "media_id": uuid.uuid4().hex, "snapshot_id": product["snapshot_id"], "asin": parsed["asin"], "kind": kind, "role": role, "observed_at": product.get("observed_at"), "downloaded_at": datetime.now(timezone.utc).isoformat()}
                product["media"].append(entry)
            entry.update({"sequence": sequence, "is_main_image": candidate.get("is_main_image", False), "main_image_evidence": candidate.get("main_image_evidence"), "is_thumbnail_fallback": candidate.get("is_thumbnail_fallback", False)})
            for field in ("module_id", "module_order", "image_order", "placements", "alt"):
                if field in candidate:
                    entry[field] = candidate[field]
            if checkpoint:
                checkpoint()
            if kind == "image" and role in {"aplus", "description"} and entry.get("status") == "stored":
                if config.get("ocr_enabled", True):
                    entry["ocr"] = await asyncio.to_thread(recognize_image, entry, archive, config.get("language", "en-US"))
                else:
                    entry["ocr"] = {"status": "disabled"}
            if checkpoint:
                checkpoint()

    await asyncio.gather(*(collect(i, kind, candidate) for i, (kind, candidate) in enumerate(candidates, 1)))
    product["media"].sort(key=lambda entry: entry.get("sequence", 999999))
    product["content_audit"] = audit_content(product)
    issues = any(m.get("status") != "stored" or m.get("preview_status") != "ready" or (m.get("kind") == "video" and m.get("probe_status") != "ready") for m in product["media"])
    issues |= any(s["acquisition_status"] != "complete" or s["ocr_pending_images"] for s in product["content_audit"].values())
    issues |= not any(m.get("is_main_image") and m.get("status") == "stored" for m in product["media"])
    product["status"] = "partial" if issues else "ok"
    return product
