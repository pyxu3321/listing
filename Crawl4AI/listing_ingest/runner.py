# 文件用途：Crawl4AI/Playwright采集编排：校验配置、榜单证据、顺序访问商品、保存快照/媒体和报告。浏览器成功不等于内容完整。
# 2026-11-03：支持全量媒体配置与视频无总时限下载。
"""Bounded live pilot; browser success is distinct from business success."""
from __future__ import annotations

import asyncio
import base64
import html
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

from .amazon import parse_bestsellers, parse_product
from .storage import LocalArchive
from .export_products import export_products
from .media_collect import collect_product_media

PROJECT = Path(__file__).resolve().parent.parent


# 功能及输出：返回带UTC时区的ISO时间，用于独立记录观察时间。
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 功能及输出：限制Amazon美国站公开HTTPS页面，无嵌入凭据；返回有效URL或报错。
# 参数：url（待处理来源地址）。
def validate_page_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.amazon.com", "amazon.com"} or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("Only public Amazon US HTTPS page URLs are accepted by this pilot")
    return url


# 功能及输出：读取单来源JSON并统一校验，返回规范配置。
# 参数：path（本地文件路径）。
def load_config(path: Path) -> dict:
    return validate_config(json.loads(path.read_text(encoding="utf-8-sig")))


# 功能及输出：校验规范配置的站点/国家适配边界、来源URL、额度、类型和分类路径；不访问网络。
# 参数：config（规范化采集配置）。
def validate_config(config: dict) -> dict:
    """Validate normalized settings independently of JSON/Excel/SQL readers."""
    config = dict(config)
    from .catalog import classification
    config.update(classification(config))
    if config["site_id"] != "amazon" or config["country_code"] != config.get("marketplace"):
        raise ValueError("Current crawler requires site_id=amazon and country_code=marketplace")
    for key in ("source_id", "ranking_url", "library_directory"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"Missing configuration field: {key}")
    if config.get("source_type") != "amazon_bestsellers":
        raise ValueError("Only amazon_bestsellers sources are currently executable")
    if config.get("marketplace") != "US":
        raise ValueError("Only US parsing is implemented; register other markets disabled")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", config["source_id"]):
        raise ValueError("Invalid source_id")
    if not str(config.get("category_node", "")).isdigit() or not config.get("category_name", "").strip():
        raise ValueError("category_node and category_name are required")
    for key in ("ranking_url", "alternate_ranking_url"):
        if config.get(key):
            validate_page_url(config[key])
    for key, low, high in (("max_products", 0, 50), ("max_images_per_product", 0, 20), ("max_videos_per_product", 0, 3), ("request_delay_seconds", 1, 60), ("page_timeout_ms", 1000, 120000)):
        value = config.get(key)
        # 媒体数量null表示全部；商品页数量仍有独立上限。
        if key in {"max_images_per_product", "max_videos_per_product"} and value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"Invalid configured limit: {key}")
    for key in ("max_products", "max_images_per_product", "max_videos_per_product", "page_timeout_ms"):
        if key in {"max_images_per_product", "max_videos_per_product"} and config[key] is None:
            continue
        if not isinstance(config[key], int):
            raise ValueError(f"{key} must be an integer")
    for key in ("max_image_bytes", "max_video_bytes"):
        if not isinstance(config.get(key), int) or not 1024 <= config[key] <= 500 * 1024 * 1024:
            raise ValueError(f"Invalid byte limit: {key}")
    if config.get("storage_backend") != "local":
        raise ValueError("Only the local archive backend is implemented in this pilot")
    for key, default, maximum in (("max_description_images_per_product", 20, 60), ("max_aplus_images_per_product", 40, 80), ("media_concurrency", 3, 4)):
        value = config.get(key, default)
        if key != "media_concurrency" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not (1 if key == "media_concurrency" else 0) <= value <= maximum:
            raise ValueError(f"Invalid content limit: {key}")
    if not isinstance(config.get("ocr_enabled", True), bool):
        raise ValueError("ocr_enabled must be boolean")
    if config.get("video_total_timeout_seconds", 60) is not None:
        if type(config.get("video_total_timeout_seconds", 60)) not in (int, float) or config.get("video_total_timeout_seconds",60) <= 0:
            raise ValueError("Invalid video_total_timeout_seconds")
    pause=config.get("video_chunk_pause_seconds",1)
    if type(pause) not in (int,float) or not 0<=pause<=60:
        raise ValueError("Invalid video_chunk_pause_seconds")
    if not isinstance(config.get("rank_end", 50), int) or not 1 <= config.get("rank_end", 50) <= 50:
        raise ValueError("rank_end must be an integer from 1 to 50")
    return config


# 功能及输出：按显式排名排序候选并结合额外测试链接及数量；额外链接不虚构排名。
# 参数：ranked（显式排名候选列表）；explicit_urls（用户指定商品链接）；limit（处理数量上限）。
def select_products(ranked: list[dict], explicit_urls: list[str], limit: int) -> list[dict]:
    """Explicit test targets take precedence, retaining observed ranks if known."""
    # 功能及输出：内部从链接提取ASIN用于队列去重，不能识别时保留URL作为身份。
    # 参数：url（待处理来源地址）。
    def identity(url: str) -> str:
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", url, re.I)
        return match.group(1).upper() if match else url
    ranked_by_key = {item.get("asin") or identity(item["url"]): item for item in ranked}
    candidates = []
    for url in explicit_urls:
        validate_page_url(url)
        key = identity(url)
        candidates.append({**ranked_by_key.get(key, {"asin": key if len(key) == 10 else None, "rank": None}), "url": url})
    candidates.extend(sorted(ranked, key=lambda item: item.get("rank", 999999)))
    selected, seen = [], set()
    for item in candidates:
        key = item.get("asin") or identity(item["url"])
        if key not in seen:
            seen.add(key)
            selected.append(item)
    return selected[:limit]


# 功能及输出：生成本地HTML报告，转义外来文本并展示缺失、证据与媒体状态，返回报告文件路径。
# 参数：report（采集报告）；directory（导出/运行目录）；archive_root（原件归档根）。
def render_report(report: dict, directory: Path, archive_root: Path) -> Path:
    esc = lambda value: html.escape(str(value if value is not None else ""), quote=True)
    # 功能及输出：内部将可用本地记录渲染为安全链接；无文件时返回空串。
    # 参数：record（对象归档记录）；label（报告链接显示文字）。
    def file_link(record: dict | None, label: str) -> str:
        if not record or not record.get("relative_path"):
            return ""
        path = (archive_root / record["relative_path"]).resolve()
        if not path.is_relative_to(archive_root.resolve()):
            return ""
        url = quote(os.path.relpath(path, directory).replace("\\", "/"), safe="/")
        return f'<a href="{url}">{esc(label)}</a>'
    rows = []
    for page in report["pages"]:
        parsed = page.get("parsed", {})
        reasons = parsed.get("blockers", []) + parsed.get("warnings", []) + ([page["error"]] if page.get("error") else [])
        rows.append(f'<tr><td>{esc(page["kind"])}</td><td>{esc(page["status"])}</td><td>{esc(page.get("http_status"))}</td><td>{esc(parsed.get("page_title"))}</td><td>{file_link(page.get("html"), "HTML")} {file_link(page.get("screenshot"), "截图")}</td><td>{esc("; ".join(reasons))}</td></tr>')
    rank_rows = [f'<tr><td>{esc(item["rank"])}</td><td>{esc(item["asin"])}</td><td>{esc(item.get("title"))}</td><td>{esc(item.get("observed_at"))}</td></tr>' for item in report["rank_observations"]]
    product_sections = []
    for product in report["products"]:
        details = product.get("parsed", {})
        media_items = []
        for media in product.get("media", []):
            media = {**media, "role": "主图" if media.get("is_main_image") else {"gallery": "附图", "aplus": "A+详情图", "description": "普通详情图"}.get(media.get("role"), media.get("role", media.get("kind")))}
            preview = media.get("preview")
            thumb = ""
            if isinstance(preview, dict) and preview.get("relative_path"):
                relative = quote(os.path.relpath(archive_root / preview["relative_path"], directory).replace("\\", "/"), safe="/")
                thumb = f'<img src="{relative}" alt="素材预览" loading="lazy">'
            object_record = media.get("object") if isinstance(media.get("object"), dict) else media
            if media.get("kind") == "video" and media.get("status") == "stored" and media.get("relative_path"):
                video_url = quote(os.path.relpath(archive_root / media["relative_path"], directory).replace("\\", "/"), safe="/")
                thumb = f'<video controls preload="metadata" src="{video_url}" style="width:220px;max-height:220px"></video>' + thumb
            media_items.append(f'<div class="media">{thumb}<p>{esc(media.get("role", media.get("kind")))} · {esc(media.get("status"))}</p>{file_link(object_record, "原文件")}<small>预览: {esc(media.get("preview_status"))} · 校验: {esc(media.get("media_validation"))}</small><small>{esc(media.get("error", ""))} {esc(media.get("preview_error", ""))}</small></div>')
        warnings = details.get("warnings", []) + ([product["warning"]] if product.get("warning") else [])
        bsr_text = " / ".join(f'#{b["rank"]} {b["category"]}' for b in details.get("bsr", []))
        content_note = ""
        for role, label in (("description", "普通详情"), ("aplus", "A+详情")):
            audit = product.get("content_audit", {}).get(role)
            if audit:
                content_note += f'<p>{label}：{esc(audit["acquisition_status"])} · 原图 {esc(audit["stored_images"])}/{esc(audit["expected_images"])} · 待识别 {len(audit["ocr_pending_images"])}</p>'
        for item in report.get("product_exports", {}).get("products", []):
            if item.get("asin") == details.get("asin") and item.get("directory"):
                preview = Path(item["directory"]) / "详情预览.html"
                if preview.resolve().is_relative_to(archive_root.resolve()) and preview.is_file():
                    link = quote(os.path.relpath(preview, directory).replace("\\", "/"), safe="/")
                    content_note += f'<p><a href="{link}">按模块查看详情原图、原文和识别文字</a></p>'
        product_sections.append(f'<section><h2>Rank {esc(product.get("listing_rank"))} · {esc(details.get("title") or product.get("requested_asin"))}</h2><p>{esc(details.get("subtitle"))}</p><p>ASIN: {esc(details.get("asin"))} · {esc(product.get("status"))}</p><p>详情页 BSR: {esc(bsr_text or "未取得")}</p><p>{esc("; ".join(warnings))}</p>{content_note}<ul>{"".join("<li>"+esc(x)+"</li>" for x in details.get("bullets", []))}</ul><div class="grid">{"".join(media_items)}</div></section>')
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Topper BSR 采集测试</title><style>body{{font:15px/1.7 system-ui,sans-serif;color:#243044;background:#f4f6f9;max-width:1200px;margin:32px auto;padding:0 20px}}section,header{{background:white;padding:24px;margin-bottom:20px;border-radius:12px}}h1{{margin:0 0 8px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #e1e6ee;overflow-wrap:anywhere}}a{{color:#1765b5}}small{{display:block}}.grid{{display:flex;gap:18px;flex-wrap:wrap}}.media{{max-width:230px}}img{{max-width:220px;max-height:220px}}code{{overflow-wrap:anywhere}}</style><header><h1>Topper BSR 采集测试</h1><p>运行 {esc(report["run_id"])} · {esc(report["started_at_shanghai"])} · 状态 <b>{esc(report["status"])}</b></p><p>真实网络采集；仅记录页面明确给出的 BSR。搜索排序不作 BSR。当前采用本地文件归档，未接云存储或生产数据库。</p><p>榜单观察 {len(report["rank_observations"])} 条 · 商品详情 {len(report["products"])} 条 · 已归档媒体 {report.get("summary", {}).get("stored_media", 0)} 个</p><p>{esc(report.get("error", ""))}</p><a href="report.json">完整 JSON 记录</a></header><section><h2>页面与证据</h2><table><tr><th>类型</th><th>业务状态</th><th>HTTP</th><th>页面标题</th><th>证据</th><th>原因</th></tr>{"".join(rows)}</table></section><section><h2>榜单观察</h2><table><tr><th>BSR</th><th>ASIN</th><th>标题</th><th>观察时间 UTC</th></tr>{"".join(rank_rows)}</table>{"<p>未取得可验证的榜单排名。</p>" if not rank_rows else ""}</section>{"".join(product_sections)}</html>'''
    coverage = report.get("rank_coverage")
    if coverage:
        coverage_text = f'Rank 1–{len(coverage["expected"])}：已取得 {len(coverage["observed"])} 个名次；缺失 {coverage["missing"]}；重复 {coverage["duplicates"]}'
        document = document.replace('<a href="report.json">完整 JSON 记录</a>', '<p>' + esc(coverage_text) + '</p><a href="report.json">完整 JSON 记录</a>')
    if report.get("observation_mode") == "snapshot_reparse":
        document = document.replace("真实网络采集；", "基于已保存的真实网页快照重新解析，未重新访问网站；")
        document = document.replace('<a href="report.json">完整 JSON 记录</a>', '<p>' + esc(report.get("review_note")) + '</p><a href="report.json">完整 JSON 记录</a>')
    destination = directory / "index.html"
    destination.write_text(document, encoding="utf-8")
    return destination


# 功能及输出：使用Crawl4AI加载榜单/商品，顺序抓取并归档快照和媒体，写报告及分类导出；返回报告与运行目录。
# 参数：config（规范化采集配置）；library_override（覆盖归档库位置）；product_urls（额外测试商品链接）。
async def run(config: dict, *, library_override: Path | None = None, product_urls: list[str] | None = None) -> tuple[dict, Path]:
    os.environ.setdefault("CRAWL4AI_BASE_DIRECTORY", str(PROJECT / ".runtime"))
    # 实际网页采集使用Crawl4AI，底层浏览器能力由Playwright提供。
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    import aiohttp

    archive_root = library_override or PROJECT / config["library_directory"]
    archive = LocalArchive(archive_root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    report = {
        "schema_version": 1, "run_id": run_id, "source_id": config["source_id"],
        "observation_mode": "live", "started_at": utc_now(),
        "started_at_shanghai": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "status": "running", "config": config, "storage_backend": "local",
        "python_executable": sys.executable,
        "implementation_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (PROJECT / "listing_ingest").iterdir() if path.suffix in {".py", ".ps1"}},
        "versions": {p: importlib.metadata.version(p) for p in ("crawl4ai", "playwright", "aiohttp", "pillow")},
        "pages": [], "products": [], "rank_observations": [],
    }
    relative_report = f"runs/{run_id}/report.json"
    report_path = archive.persist_json(report, relative_report)
    report_directory = Path(report_path).parent

    # 功能及输出：内部保存当前运行报告与页面预览，支持中断后核查。
    def checkpoint() -> None:
        archive.persist_json(report, relative_report)
        render_report(report, report_directory, archive_root)

    # 功能及输出：内部执行一次浏览器页面抓取，保存原HTML/截图/Markdown与状态；返回页面证据记录。
    # 参数：crawler（Crawl4AI浏览器实例）；url（待处理来源地址）；kind（图片/视频或关联类型）。
    async def capture(crawler, url: str, kind: str) -> dict:
        validate_page_url(url)
        page = {"snapshot_id": uuid.uuid4().hex, "kind": kind, "requested_url": url, "started_at": utc_now(), "status": "fetching"}
        report["pages"].append(page)
        checkpoint()
        print(f"[crawl] {kind} {url}", flush=True)
        try:
            result = await crawler.arun(url=url, config=CrawlerRunConfig(
                cache_mode=CacheMode.DISABLED, page_timeout=config["page_timeout_ms"],
                wait_until="domcontentloaded", delay_before_return_html=3,
                scan_full_page=True, max_scroll_steps=30, scroll_delay=0.6,
                force_viewport_screenshot=(kind == "product"),
                screenshot=True, screenshot_wait_for=1, verbose=False,
            ))
            page.update({"observed_at": utc_now(), "crawler_success": result.success,
                         "http_status": result.status_code, "final_url": result.redirected_url or result.url or url})
            body = result.html or ""
            page["html"] = archive.persist_bytes(body.encode("utf-8"), "snapshot", "html")
            if result.screenshot:
                page["screenshot"] = archive.persist_bytes(base64.b64decode(result.screenshot), "screenshot", "png")
                page["screenshot_scope"] = "viewport" if kind == "product" else "full_page"
            markdown = result.markdown
            text = getattr(markdown, "raw_markdown", markdown if isinstance(markdown, str) else "") or ""
            page["markdown"] = archive.persist_bytes(text.encode("utf-8"), "snapshot", "md")
            validate_page_url(page["final_url"])
            parser = parse_bestsellers if kind == "bsr" else parse_product
            page["parsed"] = parser(body, page["final_url"], str(config["category_node"]), config["category_name"]) if kind == "bsr" else parser(body, page["final_url"])
            page["status"] = page["parsed"]["status"]
            if not result.success or (result.status_code is not None and result.status_code >= 400):
                page["status"] = "blocked" if page["parsed"].get("blockers") else "fetch_failed"
            if result.error_message:
                page["error"] = str(result.error_message)[:1000]
        except Exception as exc:
            page.update({"status": "fetch_failed", "error": f"{type(exc).__name__}: {str(exc)[:600]}", "finished_at": utc_now()})
        checkpoint()
        print(f"[result] {kind}: {page['status']} HTTP={page.get('http_status')}", flush=True)
        return page

    try:
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, viewport_width=1440, viewport_height=1000, verbose=False)) as crawler:
            ranking_page = None
            for url in dict.fromkeys(filter(None, (config["ranking_url"], config.get("alternate_ranking_url")))):
                page = await capture(crawler, url, "bsr")
                if page["status"] == "ok":
                    ranking_page = page
                    break
                await asyncio.sleep(config["request_delay_seconds"])

            ranked_products = []
            if ranking_page:
                for item in ranking_page["parsed"].get("items", []):
                    report["rank_observations"].append({**item, "observed_at": ranking_page["observed_at"], "snapshot_id": ranking_page["snapshot_id"], "source_url": ranking_page["final_url"], "delivery_location": ranking_page["parsed"].get("delivery_location_text"), "requested_delivery_location": config.get("delivery_location")})
                ranked_products = ranking_page["parsed"].get("items", [])
            rank_end = config.get("rank_end", 50)
            ranked_products = [item for item in ranked_products if 1 <= item["rank"] <= rank_end]
            observed_ranks = [item["rank"] for item in ranked_products]
            report["rank_coverage"] = {"expected": list(range(1, rank_end + 1)), "observed": sorted(set(observed_ranks)), "missing": sorted(set(range(1, rank_end + 1)) - set(observed_ranks)), "duplicates": sorted({rank for rank in observed_ranks if observed_ranks.count(rank) > 1})}
            requested_products = select_products(ranked_products, product_urls or [], config["max_products"])
            print(f'[ranking] {len(observed_ranks)} ranks; missing={report["rank_coverage"]["missing"]}; detail targets={len(requested_products)}', flush=True)
            timeout = aiohttp.ClientTimeout(total=120, connect=20, sock_read=30)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
                shared_downloads = {}
                for sequence, item in enumerate(requested_products, 1):
                    print(f'[progress] {sequence}/{len(requested_products)} Rank {item.get("rank")} ASIN {item.get("asin")}', flush=True)
                    await asyncio.sleep(config["request_delay_seconds"])
                    page = await capture(crawler, item["url"], "product")
                    product = {"requested_asin": item.get("asin"), "requested_url": item["url"], "listing_rank": item.get("rank"), "snapshot_id": page["snapshot_id"], "status": page["status"], "observed_at": page.get("observed_at"), "parsed": page.get("parsed", {}), "media": []}
                    report["products"].append(product)
                    if page["status"] == "ok":
                        if item.get("asin") and product["parsed"].get("asin") != item["asin"]:
                            product["status"] = "identity_mismatch"
                            product["warning"] = "Selected detail ASIN differs from ranking ASIN; not bound as same variant."
                            checkpoint()
                            continue
                        await collect_product_media(product, config, archive, session, checkpoint=checkpoint, shared_downloads=shared_downloads)
                    checkpoint()

            if ranking_page:
                report["status"] = "success" if all(p["status"] == "ok" for p in report["products"]) else "partial"
                if report["rank_coverage"]["missing"] or report["rank_coverage"]["duplicates"]:
                    report["status"] = "partial"
            else:
                report["status"] = "blocked" if any(p["status"] == "blocked" for p in report["pages"] if p["kind"] == "bsr") else "failed"
                if any(p["status"] in {"ok", "partial"} for p in report["products"]):
                    report["status"] = "partial"
    except Exception as exc:
        report.update({"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:1200]}"})
    finally:
        report["finished_at"] = utc_now()
        all_media = [m for p in report["products"] for m in p.get("media", [])]
        report["summary"] = {
            "rank_observations": len(report["rank_observations"]),
            "product_pages": len(report["products"]),
            "stored_media": sum(m.get("status") == "stored" for m in all_media),
            "failed_media": sum(m.get("status") == "failed" for m in all_media),
            "link_only_media": sum(m.get("status") == "link_only" for m in all_media),
            "ready_previews": sum(m.get("preview_status") == "ready" for m in all_media),
            "unverified_videos": sum(m.get("kind") == "video" and m.get("status") == "stored" and m.get("probe_status") != "ready" for m in all_media),
        }
        try:
            report["product_exports"] = export_products(report, archive.root)
        except Exception as exc:
            report["product_exports"] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
            if report["status"] == "success":
                report["status"] = "partial"
        checkpoint()
    return report, report_directory
