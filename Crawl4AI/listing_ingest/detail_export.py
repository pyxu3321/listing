# 文件用途：导出商品普通详情/A+原文、OCR和模块化本地预览，不重新抓取或生成文案。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Readable detail packages with module order and image/text provenance."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from urllib.parse import quote


# 功能及输出：将当前商品详情与已归档媒体写为原文/OCR/模块文件和HTML预览；不替代原件。
# 参数：product（当前商品快照记录）；media（媒体记录集合或单图记录）；directory（导出/运行目录）；root（库根目录）。
def export_details(product: dict, media: list[dict], directory: Path, root: Path) -> None:
    sections = product.get("parsed", {}).get("content_sections", {})
    if not sections:
        return
    esc = lambda value: html.escape(str(value if value is not None else ""), quote=True)
    # 功能及输出：内部将本地路径转为相对预览链接并转义路径字符。
    # 参数：path（本地文件路径）。
    def href(path: Path) -> str:
        return quote(os.path.relpath(path, directory).replace("\\", "/"), safe="/")
    blocks, combined = [], []
    for role, title in (("description", "普通详情"), ("aplus", "A+详情")):
        section = sections.get(role, {})
        folder = directory / title
        folder.mkdir(exist_ok=True)
        dom = section.get("dom_text") or ("[本区已取得图片内容，没有独立网页正文；请查看原图及下方图片识别文字。]" if section.get("images") else "[本次页面未返回可提取的实质正文；栏目标题不计为正文。]")
        (folder / "原始文本.txt").write_text(dom + "\n", encoding="utf-8-sig")
        records = {m["source_url"]: m for m in media if m.get("role") == role}
        audit = product.get("content_audit", {}).get(role, {})
        (folder / "模块.json").write_text(json.dumps({"section": section, "audit": audit, "media": list(records.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
        ocr_lines = ["图片识别文字，保留识别原样，需人工核对；不等同于网页原文或产品事实。"]
        modules_html = []
        for module in section.get("modules", []):
            figures = []
            module_id = module["module_id"]
            for image in module["images"]:
                entry = records.get(image["url"], {})
                ocr = entry.get("ocr", {})
                text = ocr.get("text") or "[未识别出文字]" if ocr.get("status") in {"ready", "empty"} else f'[识别状态：{ocr.get("status", "not_processed")}]'
                ocr_lines.append(f'\n模块 {module["order"]} / 图 {image["image_order"]}\n来源图片：{image["url"]}\n识别引擎语言：{ocr.get("language", "未记录")}\n{text}')
                if entry.get("export_path"):
                    original = root / entry["export_path"]
                    preview = root / entry.get("preview_export_path", entry["export_path"])
                    figure = f'<a href="{href(original)}"><img loading="lazy" src="{href(preview)}" alt="{esc(image.get("alt"))}"></a><p><a href="{href(original)}">查看原图</a></p>'
                else:
                    figure = '<p>原图未归档：' + esc(entry.get("error", "未下载、超出限额或下载失败")) + '</p>'
                figures.append(f'<figure>{figure}<figcaption>模块 {module["order"]} / 图 {image["image_order"]} · OCR {esc(ocr.get("status", "not_processed"))}</figcaption><pre>{esc(text)}</pre></figure>')
            modules_html.append(f'<article id="{esc(module_id)}"><h3>模块 {module["order"]}</h3><h4>网页原文</h4><pre>{esc(module.get("dom_text") or "本模块没有实质 DOM 文字")}</pre>{"".join(figures)}</article>')
        (folder / "OCR文本.txt").write_text("\n".join(ocr_lines) + "\n", encoding="utf-8-sig")
        combined.append(f'{title}\n来源状态：{section.get("state", "unknown")}\n采集状态：{audit.get("acquisition_status", "unknown")}\n\n网页原文\n{dom}\n\n' + "\n".join(ocr_lines))
        blocks.append(f'<section><h2>{title}</h2><p>页面内容状态：{esc(section.get("state"))} · 采集状态：{esc(audit.get("acquisition_status"))} · 图片 {esc(audit.get("stored_images", 0))}/{esc(audit.get("expected_images", 0))}</p><h3>网页原文</h3><pre>{esc(dom)}</pre>{"".join(modules_html)}</section>')
    (directory / "详情.txt").write_text("\n\n".join(combined), encoding="utf-8-sig")
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>详情素材预览</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:24px auto;padding:16px;background:#f6f7f9}section,article{background:white;border:1px solid #ddd;border-radius:8px;padding:20px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}img{max-width:100%;height:auto}figure{margin:12px 0}figcaption{color:#555}</style><h1>' + esc(product.get("parsed", {}).get("title")) + '</h1><p>ASIN ' + esc(product.get("requested_asin")) + ' · Rank ' + esc(product.get("listing_rank")) + '</p><p>网页原文和图片识别文字分开保存。OCR 可能漏字、错字，且本机可能使用可用语言回退；核对原图后再使用。页面空区域表示本次未取得，不判断商品实际没有内容。</p>' + ''.join(blocks) + '</html>'
    (directory / "详情预览.html").write_text(document, encoding="utf-8")
