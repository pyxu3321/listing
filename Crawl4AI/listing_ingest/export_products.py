# 文件用途：从已有报告导出分类商品包与排名索引；原件集中去重，导出是副本，不修改原始商品事实。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Export a captured report into editable, ASIN-specific material folders."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote
from .detail_export import export_details
from .material_links import build_links
from .catalog import classification, product_identity


# 功能及输出：兼容出口：校验商品导出路径片段。
# 参数：value（待解析/校验值）。
def _segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value):
        raise ValueError("Invalid export path component")
    return value


# 功能及输出：依据报告身份创建国家/网站/品类/商品/批次目录，复制素材与证据并生成排名索引，返回导出清单。
# 参数：report（采集报告）；archive_root（原件归档根）。
def export_products(report: dict, archive_root: Path) -> dict:
    root = archive_root.resolve()
    grouping = classification(report["config"])
    market = grouping["country_code"]
    batch = _segment(report["run_id"])
    pages = {p["snapshot_id"]: p for p in report["pages"]}
    exports = []

    # 功能及输出：内部以UTF-8写商品包JSON记录。
    # 参数：path（本地文件路径）；value（待解析/校验值）。
    def write_json(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    # 功能及输出：内部从对象库复制指定原件到导出位置，返回相对库根路径。
    # 参数：record（对象归档记录）；destination（副本目标路径）。
    def copy_object(record: dict, destination: Path) -> str:
        source = (root / record["relative_path"]).resolve()
        if not source.is_relative_to((root / "objects").resolve()):
            raise ValueError("Export source must be an archived object")
        if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Archived object checksum mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination.relative_to(root).as_posix()

    for product in report["products"]:
        parsed = product.get("parsed", {})
        asin = parsed.get("asin")
        try:
            identity = product_identity(report["config"], product)
        except ValueError:
            identity = None
        if identity is None or product.get("status") == "identity_mismatch":
            exports.append({"rank": product.get("listing_rank"), "requested_asin": product.get("requested_asin"), "status": "skipped", "reason": "Product identity unconfirmed or mismatched"})
            continue
        product_id = identity["product_id"]
        directory = root / "products" / market / grouping["site_id"] / grouping["category_id"] / product_id / batch
        directory.mkdir(parents=True, exist_ok=True)
        for child in ("图片", "视频", "预览", "证据"):
            (directory / child).mkdir(exist_ok=True)
        title = parsed.get("title") or ""
        subtitle = parsed.get("subtitle") or ""
        bullets = "\n\n".join(f'{i}. {text}' for i, text in enumerate(parsed.get("bullets", []), 1))
        (directory / "标题与五点.txt").write_text(f"商品编号：{product_id}\n榜单排名：{product.get('listing_rank')}\n\n标题\n{title}\n\n副标题\n{subtitle}\n\n五点描述（保留实际提取条数）\n{bullets}\n", encoding="utf-8-sig")
        description = parsed.get("description") or "[页面未提取到普通详情文本]"
        aplus = parsed.get("aplus_text") or "[页面未提取到 A+ 详情文本]"
        (directory / "详情.txt").write_text(f"普通详情\n{description}\n\nA+ 详情\n{aplus}\n", encoding="utf-8-sig")
        page = pages.get(product["snapshot_id"], {})
        media_records = []
        counters = {"image": 0, "video": 0}
        role_counters = {}
        for media in product.get("media", []):
            record = dict(media)
            if media.get("status") == "stored" and not media.get("excluded_from_product_materials"):
                kind = media["kind"]
                counters[kind] += 1
                role = media.get("role", kind)
                role_counters[role] = role_counters.get(role, 0) + 1
                label = "主图" if media.get("is_main_image") else "附图" if media.get("role") == "gallery" else "详情图" if kind == "image" else "视频"
                stem = f'{role_counters[role]:02d}_{label}'
                if role in {"description", "aplus"}:
                    stem = f'{role_counters[role]:02d}_模块{media.get("module_order", 0):03d}'
                suffix = Path(media["relative_path"]).suffix
                if not re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", suffix):
                    raise ValueError("Invalid archived media extension")
                child = "图片" if kind == "image" else "视频"
                if role in {"description", "aplus"}:
                    child = ("A+详情" if role == "aplus" else "普通详情") + "/图片"
                record["export_path"] = copy_object(media, directory / child / (stem + suffix))
                if isinstance(media.get("preview"), dict):
                    record["preview_export_path"] = copy_object(media["preview"], directory / "预览" / (role + "_" + stem + ".jpg"))
            media_records.append(record)
        for field, name in (("html", "原始页面.html"), ("screenshot", "网页截图.png"), ("markdown", "页面内容.md")):
            if page.get(field):
                copy_object(page[field], directory / "证据" / name)
        evidence = {
            **identity, "asin": asin, "marketplace": report["config"].get("marketplace"), "language": report["config"].get("language"),
            "run_id": batch, "snapshot_id": product["snapshot_id"],
            "observed_at": product.get("observed_at"), "source_url": page.get("final_url", product.get("requested_url")),
            "observation_mode": report.get("observation_mode"), "source_run_id": report.get("source_run_id"),
            "delivery_location_text": parsed.get("delivery_location_text"),
            "ranking_observations": [r for r in report["rank_observations"] if r["asin"] == asin],
            "detail_bsr": parsed.get("bsr", []), "media": media_records,
            "content_audit": product.get("content_audit", {}),
            "excluded_media": [m for m in report.get("excluded_media", []) if m.get("asin") == asin],
        }
        write_json(directory / "商品信息.json", {**identity, "asin": asin, "status": product["status"], "product": parsed, "content_audit": product.get("content_audit", {}), "image_budgets": product.get("image_budgets", {})})
        write_json(directory / "来源与排名.json", evidence)
        write_json(directory / "素材关联.json", build_links(report, product, media_records))
        export_details(product, media_records, directory, root)
        main = next((m for m in media_records if m.get("is_main_image") and m.get("export_path")), None)
        exports.append({**identity, "asin": asin, "rank": product.get("listing_rank"), "title": title, "status": "exported", "directory": str(directory), "images": counters["image"], "images_by_role": role_counters, "videos": counters["video"], "main_image": main.get("export_path") if main else None, "content_audit": product.get("content_audit", {})})
    result = {"root": str(root / "products"), "layout_version": 2, **grouping, "batch": batch, "products": exports}
    manifest = root / "products" / "批次索引" / f"{batch}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    write_json(manifest, result)
    index = manifest.with_suffix(".html")
    # 功能及输出：内部把索引引用转为相对链接，处理空格和路径转义。
    # 参数：path（本地文件路径）。
    def href(path: Path) -> str:
        return quote(os.path.relpath(path, index.parent).replace("\\", "/"), safe="/")
    rows = []
    for item in sorted(exports, key=lambda item: item.get("rank") or 999999):
        if item["status"] != "exported":
            rows.append(f'<tr><td>Rank {html.escape(str(item.get("rank")))}</td><td>{html.escape(str(item.get("requested_asin")))}</td><td colspan="3">未导出：{html.escape(item.get("reason", ""))}</td></tr>')
            continue
        directory = Path(item["directory"])
        detail_link = '<a href="' + href(directory / "详情预览.html") + '">详情图文预览</a> · ' if (directory / "详情预览.html").is_file() else ""
        main = f'<a href="{href(root / item["main_image"])}"><img src="{href(root / item["main_image"])}" width="120" alt="主图"></a>' if item.get("main_image") else "主图未确认或下载失败"
        rows.append(f'<tr><td>Rank {html.escape(str(item.get("rank")))}</td><td>{html.escape(item["product_id"])}</td><td>{main}</td><td>{html.escape(item["title"])}</td><td><a href="{href(directory / "标题与五点.txt")}">标题与五点</a> · {detail_link}<a href="{href(directory / "详情.txt")}">详情文本</a> · <a href="{href(directory / "来源与排名.json")}">来源与排名</a> · <a href="{href(directory / "图片")}/">图库文件夹</a></td></tr>')
    index.write_text('<!doctype html><meta charset="utf-8"><title>按排名查看商品素材</title><style>body{font:16px system-ui;margin:32px}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #ddd;text-align:left}img{object-fit:contain;max-height:120px}</style><h1>按排名查看商品素材</h1><p>主图依据详情页当前所选商品的主展示图识别；不按文件顺序猜测。排名取自本批次榜单快照。</p><table><tr><th>排名</th><th>商品编号</th><th>主图</th><th>标题</th><th>素材</th></tr>' + ''.join(rows) + '</table>', encoding="utf-8")
    result["index_html"] = str(index)
    write_json(manifest, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    source = args.report.resolve()
    print(json.dumps(export_products(json.loads(source.read_text(encoding="utf-8")), source.parents[2]), ensure_ascii=False, indent=2))
