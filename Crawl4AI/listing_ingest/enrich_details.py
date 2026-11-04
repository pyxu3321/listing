# 文件用途：依据保留报告补采详情和A+，保留原排名观察；联网访问商品页并写新批次，不重新推断排名。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Repair detail packages from captured HTML, fetching only discovered assets."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

import aiohttp

from .amazon import parse_product
from .export_products import export_products
from .media_collect import collect_product_media
from .runner import PROJECT, load_config, render_report, utc_now
from .storage import LocalArchive


# 功能及输出：依据补采记录汇总商品、区段、图片/OCR等计数，不以排名替代质量。
# 参数：report（采集报告）。
def summarize(report):
    media = [m for p in report["products"] for m in p.get("media", [])]
    sections = {}
    for role in ("description", "aplus"):
        audits = [p.get("content_audit", {}).get(role, {}) for p in report["products"]]
        sections[role] = {"images_stored": sum(m["status"] == "stored" and m.get("role") == role for m in media), "ocr_ready": sum(m.get("role") == role and m.get("ocr", {}).get("status") == "ready" for m in media), "ocr_empty": sum(m.get("role") == role and m.get("ocr", {}).get("status") == "empty" for m in media), "source_not_observed": sum(a.get("acquisition_status") == "not_observed" for a in audits), "asset_complete": sum(a.get("acquisition_status") == "complete" for a in audits), "asset_partial": sum(a.get("acquisition_status") == "partial" for a in audits)}
    return {"rank_observations": len(report["rank_observations"]), "product_pages": len(report["products"]), "enriched_products": sum(p.get("enrichment_state") == "done" for p in report["products"]), "stored_media": sum(m["status"] == "stored" for m in media), "failed_media": sum(m["status"] == "failed" for m in media), "ready_previews": sum(m.get("preview_status") == "ready" for m in media), "content_sections": sections}


# 功能及输出：读取来源报告，访问选定商品补采详情，保存新批次、证据和导出；可限制数量，返回新目录。
# 参数：source（原文件或原报告路径）；limit（处理数量上限）。
async def enrich(source: Path, limit: int | None = None) -> Path:
    source = source.resolve()
    report = json.loads(source.read_text(encoding="utf-8"))
    archive = LocalArchive(source.parents[2])
    report["source_run_id"] = report["run_id"]
    report["run_id"] += "_content_" + uuid.uuid4().hex[:6]
    report["source_config"] = report["config"].copy()
    current = load_config(PROJECT / "config/topper-us.json")
    report["config"].update({key: current[key] for key in ("max_description_images_per_product", "max_aplus_images_per_product", "media_concurrency", "ocr_enabled")})
    report["observation_mode"] = "snapshot_reparse"
    report["review_note"] = "从原始快照重新提取普通详情和 A+，补充下载独立分区图片并执行本地 OCR。原始页面观察时间、榜单名次保持原记录；新增图片下载时间另存。空区域标记未取得，OCR 与网页原文分开保存。"
    report["enrichment_started_at"] = utc_now()
    report["captured_implementation_hashes"] = report.get("implementation_hashes")
    report["implementation_hashes"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (PROJECT / "listing_ingest").glob("*.py")}
    report["implementation_hashes"]["ocr_image.ps1"] = hashlib.sha256((PROJECT / "listing_ingest/ocr_image.ps1").read_bytes()).hexdigest()
    if limit is not None:
        report["products"] = report["products"][:limit]
    for product in report["products"]:
        product["enrichment_state"] = "pending"
    report["status"] = "running"
    report.pop("product_exports", None)
    relative = f'runs/{report["run_id"]}/report.json'
    destination = archive.root / relative
    last_checkpoint = 0.0

    # 功能及输出：内部按条件保存当前补采进度；force用于强制落盘，避免中断丢失全部结果。
    # 参数：force（是否强制保存）。
    def checkpoint(force=False):
        nonlocal last_checkpoint
        if not force and time.monotonic() - last_checkpoint < 2:
            return
        report["summary"] = summarize(report)
        archive.persist_json(report, relative)
        render_report(report, destination.parent, archive.root)
        last_checkpoint = time.monotonic()

    checkpoint(True)
    print(f'Report: {destination}', flush=True)
    pages = {page["snapshot_id"]: page for page in report["pages"]}
    shared_downloads = {}
    try:
        async with aiohttp.ClientSession(trust_env=True) as session:
            for sequence, product in enumerate(report["products"], 1):
                print(f'[details] {sequence}/{len(report["products"])} Rank {product.get("listing_rank")} {product["requested_asin"]}', flush=True)
                page = pages[product["snapshot_id"]]
                path = (archive.root / page["html"]["relative_path"]).resolve()
                if not path.is_relative_to(archive.root / "objects") or hashlib.sha256(path.read_bytes()).hexdigest() != page["html"]["sha256"]:
                    raise ValueError("Snapshot path or checksum mismatch")
                parsed = parse_product(path.read_text(encoding="utf-8"), page["final_url"])
                page["parsed"] = product["parsed"] = parsed
                if parsed.get("asin") != product["requested_asin"] or parsed["status"] != "ok":
                    product.update({"status": "identity_mismatch", "enrichment_state": "skipped"})
                    checkpoint(True)
                    continue
                product["enrichment_state"] = "running"
                await collect_product_media(product, report["config"], archive, session, checkpoint=checkpoint, shared_downloads=shared_downloads)
                product["enrichment_state"] = "done"
                checkpoint(True)
                print(f'[details-result] Rank {product.get("listing_rank")} ' + json.dumps(product["content_audit"], ensure_ascii=True), flush=True)
        report["status"] = "success" if all(p["status"] == "ok" for p in report["products"]) else "partial"
    except Exception as exc:
        report.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        report["enrichment_finished_at"] = utc_now()
        report["summary"] = summarize(report)
        try:
            report["product_exports"] = export_products(report, archive.root)
        except Exception as exc:
            report["export_error"] = f"{type(exc).__name__}: {exc}"
            report["status"] = "partial" if report["status"] == "success" else report["status"]
        checkpoint(True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and not 1 <= args.limit <= 50:
        parser.error("--limit must be 1-50")
    path = asyncio.run(enrich(args.source, args.limit))
    print(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "success" else 2)
