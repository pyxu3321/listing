# 文件用途：普通详情和A+按DOM分区提取，保留模块顺序与媒体位置，分别控制图片额度并检查缺失/OCR状态。
# 2026-11-03：支持全量媒体配置与视频无总时限下载。
"""Observed detail sections, ordered modules, and independent image budgets."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

HEADINGS = {"product description", "from the manufacturer", "product details", "description"}


# 功能及输出：过滤标题、导航/控件与时长等噪声，只保留观察到的正文。
# 参数：node（DOM节点）。
def _body_text(node: Tag) -> str | None:
    clone = BeautifulSoup(str(node), "html.parser")
    for el in clone.select("script,style,noscript,template,button,video,.vjs-control-bar,.vjs-control-text,.vjs-modal-dialog,.a-carousel-goto-nextpage,.a-carousel-goto-prevpage"):
        el.decompose()
    for el in clone.select("h1,h2,h3"):
        if el.get_text(" ", strip=True).casefold() in HEADINGS:
            el.decompose()
    text = " ".join(clone.stripped_strings)
    text = re.sub(r"\b(?:Previous page|Next page)\b", "", text, flags=re.I)
    text = " ".join(text.split()).strip()
    return None if not text or text.casefold() in HEADINGS or re.fullmatch(r"-?\d{1,2}:\d{2}", text) else text


# 功能及输出：读取图片/背景图片实际地址，解析相对路径并过滤无效内容。
# 参数：node（DOM节点）；base（相对链接基准URL）。
def _image_url(node: Tag, base: str) -> str | None:
    value = node.get("data-old-hires") or node.get("data-src")
    if not value:
        try:
            dynamic = json.loads(node.get("data-a-dynamic-image", "{}"))
            valid = [(url, size) for url, size in dynamic.items() if isinstance(size, list) and len(size) == 2 and all(isinstance(n, (int, float)) for n in size)]
            value = max(valid, key=lambda pair: pair[1][0] * pair[1][1])[0] if valid else None
        except (ValueError, TypeError, AttributeError):
            pass
    if not value:
        srcset = node.get("data-srcset") or node.get("srcset")
        if not srcset and node.find_parent("picture"):
            source = node.find_parent("picture").select_one("source[data-srcset],source[srcset]")
            if source:
                srcset = source.get("data-srcset") or source.get("srcset")
        if srcset:
            options = []
            for match in re.finditer(r"(\S+)\s+(\d+(?:\.\d+)?)[wx](?=\s*(?:,|$))", srcset):
                options.append((float(match[2]), match[1]))
            if options:
                value = max(options)[1]
    value = value or node.get("src")
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(base, value)
    if urlsplit(url).scheme != "https" or any(fragment in url.casefold() for fragment in ("grey-pixel", "transparent-pixel", "loading-spinner")):
        return None
    return url


# 功能及输出：从DOM提取普通详情/A+分区、原文、模块和图片位置，返回区段字典。
# 参数：soup（解析后的HTML树）；source_url（实际来源/最终跳转URL）。
def extract_sections(soup: BeautifulSoup, source_url: str) -> dict:
    sections = {}
    for role, selectors in (("description", ("#productDescription", "#productDescription_feature_div")), ("aplus", ("#aplus", "#aplus_feature_div"))):
        root = next((el for selector in selectors if (el := soup.select_one(selector)) is not None), None)
        section = {"role": role, "present": root is not None, "state": "not_observed", "dom_text": None, "heading": None, "modules": [], "images": [], "missing_reason": "section_not_returned_in_snapshot"}
        sections[role] = section
        if root is None:
            continue
        section["dom_text"] = _body_text(root)
        heading = root.select_one("h1,h2,h3")
        section["heading"] = heading.get_text(" ", strip=True) if heading else None
        candidates = root.select(".aplus-module") if role == "aplus" else []
        candidate_ids = {id(node) for node in candidates}
        modules = [node for node in candidates if not any(id(parent) in candidate_ids for parent in node.parents)]
        if not modules and (section["dom_text"] or root.select_one("img,video,iframe")):
            modules = [root]
        images_by_url = {}
        for module_order, module in enumerate(modules, 1):
            module_id = f"{role}_{module_order:03d}"
            record = {"module_id": module_id, "order": module_order, "type": " ".join(module.get("class", [])), "dom_text": _body_text(module), "images": [], "video_present": bool(module.select_one("video,iframe"))}
            seen_module_urls = set()
            for img in module.select("img"):
                url = _image_url(img, source_url)
                if not url or url in seen_module_urls:
                    continue
                seen_module_urls.add(url)
                placement = {"module_id": module_id, "module_order": module_order, "image_order": len(record["images"]) + 1}
                item = {"url": url, "role": role, "alt": img.get("alt"), "is_main_image": False, "is_thumbnail_fallback": False, **placement}
                record["images"].append(item)
                if url not in images_by_url:
                    images_by_url[url] = {**item, "placements": []}
                images_by_url[url]["placements"].append(placement)
            # Some A+ modules use inline background images rather than img tags.
            for el in [module, *module.select("[style]")]:
                for match in re.finditer(r"background(?:-image)?\s*:[^;]*?url\(\s*['\"]?([^)'\"]+)", el.get("style", ""), re.I):
                    url = urljoin(source_url, match[1].strip())
                    if not url or urlsplit(url).scheme != "https" or url in seen_module_urls:
                        continue
                    seen_module_urls.add(url)
                    placement = {"module_id": module_id, "module_order": module_order, "image_order": len(record["images"]) + 1}
                    item = {"url": url, "role": role, "alt": None, "is_main_image": False, "is_thumbnail_fallback": False, **placement}
                    record["images"].append(item)
                    images_by_url.setdefault(url, {**item, "placements": []})["placements"].append(placement)
            section["modules"].append(record)
        section["images"] = list(images_by_url.values())
        has_text, has_images = bool(section["dom_text"]), bool(section["images"])
        section["state"] = "mixed" if has_text and has_images else "image_only" if has_images else "text_only" if has_text else "heading_only" if section["heading"] else "empty_container"
        section["missing_reason"] = None if has_text or has_images else "no_substantive_content_returned_in_snapshot"
    return sections


# 功能及输出：按图库、普通详情、A+各自额度选取图片；返回候选及预算/截断记录，保留重复图的多模块位置。
# 参数：parsed（已解析商品内容）；config（规范化采集配置）。
def select_image_candidates(parsed: dict, config: dict) -> tuple[list[dict], dict]:
    selected, budgets = [], {}
    for role, limit in (("gallery", config["max_images_per_product"]), ("description", config.get("max_description_images_per_product", 20)), ("aplus", config.get("max_aplus_images_per_product", 40))):
        candidates = [image for image in parsed.get("images", []) if image["role"] == role]
        chosen = candidates if limit is None else candidates[:limit]
        selected.extend(chosen)
        budgets[role] = {"discovered": len(candidates), "selected": len(chosen), "limit": limit, "truncated": len(candidates)-len(chosen)}
    return selected, budgets


# 功能及输出：比较解析区段、媒体下载及OCR状态；区分未取得、限额截断、原件失败和OCR待处理。
# 参数：product（当前商品快照记录）。
def audit_content(product: dict) -> dict:
    result = {}
    for role, section in product.get("parsed", {}).get("content_sections", {}).items():
        candidates = section["images"]
        stored = {m["source_url"]: m for m in product.get("media", []) if m.get("role") == role and m.get("status") == "stored"}
        missing = [image["url"] for image in candidates if image["url"] not in stored]
        ocr_pending = [url for url, media in stored.items() if media.get("ocr", {}).get("status") not in {"ready", "empty"}]
        result[role] = {"source_state": section["state"], "has_dom_text": bool(section["dom_text"]), "expected_images": len(candidates), "stored_images": len(stored), "missing_images": missing, "ocr_pending_images": ocr_pending,
                        "acquisition_status": "not_observed" if section["state"] in {"not_observed", "empty_container", "heading_only"} else "partial" if missing else "complete",
                        "text_status": "ocr_pending" if ocr_pending else "dom_and_ocr" if stored and section["dom_text"] else "ocr" if stored else "dom" if section["dom_text"] else "not_observed"}
    return result
