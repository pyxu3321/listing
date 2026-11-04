# 文件用途：历史快照重新解析/视频归属复核工具；可选视频下载，不属于正常采集必经步骤。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Reparse an immutable pilot capture without making network requests."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from .amazon import parse_bestsellers, parse_product
from .runner import PROJECT, render_report, utc_now
from .storage import LocalArchive, download_media
from .export_products import export_products


# 功能及输出：读取旧快照重新解析归属并保存复核批次，download_videos开启时可联网取视频；返回复核目录。
# 参数：source（原文件或原报告路径）；download_videos（是否联网下载复核视频）。
def review(source: Path, download_videos: bool = False) -> Path:
    source = source.resolve()
    report = json.loads(source.read_text(encoding="utf-8"))
    archive = LocalArchive(source.parents[2])
    report["source_run_id"] = report["run_id"]
    report["run_id"] += "_reviewed_" + uuid.uuid4().hex[:6]
    report["observation_mode"] = "snapshot_reparse"
    report["reviewed_at"] = utc_now()
    report["captured_implementation_hashes"] = report.get("implementation_hashes")
    report["implementation_hashes"] = {name: hashlib.sha256((PROJECT / "listing_ingest" / name).read_bytes()).hexdigest() for name in ("amazon.py", "storage.py", "runner.py", "review_snapshots.py")}
    report["review_note"] = "已排除广告视频及无法确认商品归属的视频。仅接纳详情页图片区播放器中明确绑定当前 ASIN 的视频。页面观察时间沿用原快照，补充下载时间单独记录；原始运行记录保持不变。"
    pages = {}
    for page in report["pages"]:
        body = Path(page["html"]["path"]).read_text(encoding="utf-8")
        parser = parse_bestsellers if page["kind"] == "bsr" else parse_product
        page["parsed"] = parser(body, page["final_url"])
        pages[page["snapshot_id"]] = page
    excluded = []
    for product in report["products"]:
        product["parsed"] = pages[product["snapshot_id"]]["parsed"]
        allowed = {m["url"] for m in product["parsed"]["videos"]}
        excluded_by_url = {m["url"]: m["exclusion_reason"] for m in product["parsed"]["excluded_videos"]}
        kept = []
        for media in product["media"]:
            if media["kind"] == "video" and media["source_url"] not in allowed:
                excluded.append({**media, "excluded_from_product_materials": True, "exclusion_reason": excluded_by_url.get(media["source_url"], "product_ownership_unconfirmed")})
            else:
                kept.append(media)
        product["media"] = kept
    if download_videos:
        # 功能及输出：内部异步下载复核后的视频候选并记录状态；不会把播放清单说成已下载文件。
        async def fetch_videos():
            import aiohttp
            async with aiohttp.ClientSession(trust_env=True) as session:
                for product in report["products"]:
                    for candidate in product["parsed"]["videos"][:report["config"]["max_videos_per_product"]]:
                        entry = await download_media(session, candidate["url"], archive, kind="video", max_bytes=report["config"]["max_video_bytes"])
                        entry.update({"media_id": uuid.uuid4().hex, "snapshot_id": product["snapshot_id"], "asin": product["parsed"]["asin"], "role": "video", "observed_at": product["observed_at"], "downloaded_at": utc_now(), "evidence_region": candidate.get("evidence_region"), "evidence_asin": candidate.get("evidence_asin")})
                        product["media"].append(entry)
                        print(f'Product video {product["requested_asin"]}: {entry["status"]}', flush=True)
        asyncio.run(fetch_videos())
    for product in report["products"]:
        ready = any(m["kind"] == "video" and m["status"] == "stored" and m.get("preview_status") == "ready" and m.get("probe_status") == "ready" for m in product["media"])
        product["status"] = "ok" if ready and all(m["status"] == "stored" for m in product["media"]) else "partial"
        product["warning"] = "Sponsored and unconfirmed videos excluded." if ready else "Product video not archived or validated; see source candidates and media results."
    report["excluded_media"] = excluded
    media = [m for p in report["products"] for m in p["media"]]
    report["status"] = "success" if all(p["status"] == "ok" for p in report["products"]) else "partial"
    report["summary"] = {
        "rank_observations": len(report["rank_observations"]),
        "product_pages": len(report["products"]),
        "stored_media": sum(m["status"] == "stored" for m in media),
        "failed_media": sum(m["status"] == "failed" for m in media),
        "link_only_media": sum(m["status"] == "link_only" for m in media),
        "ready_previews": sum(m.get("preview_status") == "ready" for m in media),
        "excluded_media": len(excluded),
        "verified_product_videos": sum(m["kind"] == "video" and m["status"] == "stored" for m in media),
    }
    report["product_exports"] = export_products(report, archive.root)
    destination = archive.persist_json(report, f'runs/{report["run_id"]}/report.json')
    render_report(report, destination.parent, archive.root)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--download-videos", action="store_true")
    args = parser.parse_args()
    print(review(args.source, args.download_videos))
