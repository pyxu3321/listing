# 文件用途：Amazon美国站解析：BSR榜单、当前所选商品、变体、主图、图文与视频候选；仅解析已观察页面，不执行页面脚本。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Evidence-first Amazon HTML parsing; no network calls or inferred rankings."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from .content import extract_sections

TOPPER_NODE = "8521807011"
ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.I)
RANK_RE = re.compile(r"#\s*([\d,]+)\s+in\s+(.+?)(?=\s*#\s*[\d,]+\s+in\b|$)", re.I)
BLOCK_MESSAGES = (
    "Enter the characters you see below",
    "Sorry, we just need to make sure you're not a robot",
    "Click the button below to continue shopping",
    "Sorry! Something went wrong!",
)
DETAIL_RANK_SELECTORS = (
    "#SalesRank, #productDetails_detailBullets_sections1 tr, "
    "#productDetails_db_sections tr, #detailBullets_feature_div li, "
    "#productDetails_feature_div tr"
)


# 功能及输出：提取节点可见文本并规范空白；节点不存在返回None。
# 参数：node（DOM节点）。
def _text(node: Tag | None) -> str | None:
    return " ".join(node.stripped_strings).strip() if node else None


# 功能及输出：解析相对地址，过滤不支持的协议；返回观察到的HTTP(S)地址或None。
# 参数：value（待解析/校验值）；base（相对链接基准URL）。
def _url(value: str | None, base: str) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    result = urljoin(base, value.strip())
    return result if urlsplit(result).scheme in {"http", "https"} else None


# 功能及输出：从链接或字符串匹配ASIN并转大写；不能匹配时返回None。
# 参数：value（待解析/校验值）。
def _asin(value: str | None) -> str | None:
    match = ASIN_RE.search(value or "")
    return match.group(1).upper() if match else None


# 功能及输出：检查ASIN是否为10位字母数字，返回有效值或None。
# 参数：value（待解析/校验值）。
def _valid_asin(value: str | None) -> str | None:
    value = (value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z0-9]{10}", value) else None


# 功能及输出：从榜单路径或查询参数读取类目节点，不猜测类目。
# 参数：url（待处理来源地址）。
def _node(url: str | None) -> str | None:
    parts = urlsplit(url or "")
    match = re.search(r"/(?:gp/bestsellers|zgbs)/[^/?]+/(\d+)(?:[/?]|$)", parts.path)
    if match:
        return match.group(1)
    return parse_qs(parts.query).get("node", [None])[0]


# 功能及输出：识别验证码/拒绝访问等页面阻断提示，返回去重原因。
# 参数：soup（解析后的HTML树）。
def _blockers(soup: BeautifulSoup) -> list[str]:
    text = soup.get_text(" ", strip=True)
    result = [message for message in BLOCK_MESSAGES if message.casefold() in text.casefold()]
    if soup.select_one("#captchacharacters, form[action*='validateCaptcha']"):
        result.append("captcha_form")
    title = _text(soup.title) or ""
    if "robot check" in title.casefold():
        result.append("robot_check_title")
    return list(dict.fromkeys(result))


# 功能及输出：提取配送位置显示文字，保留其观察状态，不保证已完成地区切换。
# 参数：soup（解析后的HTML树）。
def _delivery_location(soup: BeautifulSoup) -> str | None:
    lines = [_text(soup.select_one(selector)) for selector in ("#glow-ingress-line1", "#glow-ingress-line2")]
    lines = [line for line in lines if line and line.casefold() not in {"update location", "select your address"}]
    return " ".join(lines) or None


# 功能及输出：输入真实最终URL及HTML；校验榜单标题与类目后提取显式名次、ASIN和分页；搜索或错误类目不作为BSR。
# 参数：html（已观察页面HTML）；source_url（实际来源/最终跳转URL）；category_node（类目节点ID）；category_name（期望类目名称）。
def parse_bestsellers(html: str, source_url: str, category_node: str = TOPPER_NODE, category_name: str = "Mattress Toppers") -> dict:
    """Read explicit topper BSR cards, rejecting search pages and other categories.

    source_url must be the actual final page URL when a crawl was redirected.
    Absence of a verified heading/node returns unexpected_page rather than ranks.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    result = {
        "status": "empty", "page_title": _text(soup.title),
        "category_name": None, "category_node": _node(source_url),
        "delivery_location_text": _delivery_location(soup),
        "items": [], "blockers": _blockers(soup),
        "warnings": [], "next_page_url": None,
    }
    if result["blockers"]:
        result["status"] = "blocked"
        return result

    path = urlsplit(source_url).path
    if not re.search(r"/(?:gp/bestsellers|zgbs)/", path) or _node(source_url) != category_node:
        result.update(status="unexpected_page", warnings=["not_requested_topper_bestsellers_url"])
        return result
    canonical = soup.select_one("link[rel='canonical'][href]")
    canonical_url = _url(canonical.get("href"), source_url) if canonical else None
    if canonical_url and _node(canonical_url) not in (None, category_node):
        result.update(status="unexpected_page", warnings=["canonical_category_mismatch"])
        return result
    headings = [_text(el) or "" for el in soup.select("#zg_banner_text, #zg-banner-text, .zg-banner-text, h1")]
    heading = next((h for h in headings if re.search(r"\bbest\s*sellers\b", h, re.I) and category_name.casefold() in h.casefold()), None)
    if not heading:
        result.update(status="unexpected_page", warnings=["topper_bestsellers_heading_not_found"])
        return result
    result["category_name"] = re.sub(r"^.*?Best\s*Sellers\s*(?:in|:)?\s*(?:Best\s+)?", "", heading, flags=re.I).strip()

    seen_exact = set()
    for badge in soup.select(".zg-bdg-text, .zg-badge-text, .zg_rankNumber"):
        badge_text = _text(badge) or ""
        match = re.fullmatch(r"#?\s*([\d,]+)\.?", badge_text)
        if not match:
            continue
        rank = int(match.group(1).replace(",", ""))
        if rank < 1:
            continue
        card = badge.parent
        links = []
        for _ in range(8):
            if not isinstance(card, Tag):
                break
            if len(card.select(".zg-bdg-text, .zg-badge-text, .zg_rankNumber")) > 1:
                break
            links = [a for a in card.select("a[href]") if _asin(a.get("href"))]
            if links:
                break
            card = card.parent
        if not links:
            result["warnings"].append(f"rank_{rank}_has_no_product_link")
            continue
        asins = list(dict.fromkeys(_asin(a.get("href")) for a in links))
        if len(asins) != 1:
            result["warnings"].append(f"rank_{rank}_ambiguous_product_links")
            continue
        asin = asins[0]
        key = (rank, asin)
        if key in seen_exact:
            continue
        seen_exact.add(key)
        if any(item["asin"] == asin and item["rank"] != rank for item in result["items"]):
            result["warnings"].append(f"asin_{asin}_appears_at_multiple_explicit_ranks")
        if any(item["rank"] == rank and item["asin"] != asin for item in result["items"]):
            result["warnings"].append(f"rank_{rank}_appears_for_multiple_asins")
        title_node = card.select_one(".p13n-sc-truncate, .p13n-sc-truncated, .p13n-sc-line-clamp-3, .p13n-sc-line-clamp-4")
        title = _text(title_node)
        if not title:
            title = next((_text(a) for a in links if len(_text(a) or "") > 3), None)
        image = card.select_one("img[alt]")
        title = title or (image.get("alt") if image else None)
        product_url = _url(links[0].get("href"), source_url)
        result["items"].append({
            "asin": asin, "title": title, "url": product_url, "rank": rank,
            "rank_type": "bsr_category", "category_node": category_node,
            "category_name": result["category_name"], "evidence_text": badge_text,
        })
    result["items"].sort(key=lambda item: item["rank"])
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["status"] = "ok" if result["items"] else "empty"
    for a in soup.select("li.a-last a[href], a[rel='next'][href]"):
        candidate = _url(a.get("href"), source_url)
        if candidate and _node(candidate) == category_node:
            result["next_page_url"] = candidate
            break
    return result


# 功能及输出：从节点已观察的高清属性/尺寸候选选择图片URL，不凭空构造下载地址。
# 参数：el（图片DOM节点）。
def _highres_image(el: Tag) -> str | None:
    if el.get("data-old-hires"):
        return el["data-old-hires"]
    try:
        dynamic = json.loads(el.get("data-a-dynamic-image", "{}"))
        if isinstance(dynamic, dict) and dynamic:
            valid = [(url, size) for url, size in dynamic.items() if isinstance(size, list) and len(size) == 2 and all(isinstance(n, (int, float)) for n in size)]
            if valid:
                return max(valid, key=lambda pair: pair[1][0] * pair[1][1])[0]
    except (ValueError, TypeError):
        pass
    return el.get("data-src") or el.get("src")


# 功能及输出：识别Amazon同图不同尺寸变体，用于去重；不会修改实际下载URL。
# 参数：url（待处理来源地址）。
def _image_identity(url: str) -> str:
    """Compare known Amazon size variants without inventing a download URL."""
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    if host.endswith(".media-amazon.com") or host.endswith(".ssl-images-amazon.com"):
        match = re.search(r"/images/I/([^/]+)", parts.path)
        if match:
            return "amazon_image:" + re.sub(r"\._[^/]*_\.", ".", match.group(1))
    return url


# 功能及输出：把单个JS字符串字面量作为数据解码；不执行JS表达式。
# 参数：text（待解码数据文本）。
def _read_js_string(text: str) -> tuple[str, int] | None:
    """Decode a single JS string literal as data, with no expression evaluation."""
    if not text or text[0] not in {"'", '"'}:
        return None
    quote, out, index = text[0], [], 1
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    while index < len(text):
        char = text[index]
        index += 1
        if char == quote:
            return "".join(out), index
        if char in "\r\n":
            return None
        if char != "\\":
            out.append(char)
            continue
        if index >= len(text):
            return None
        escaped = text[index]
        index += 1
        if escaped in "\r\n":
            if escaped == "\r" and text[index:index + 1] == "\n":
                index += 1
            continue
        if escaped in {"u", "x"}:
            size = 4 if escaped == "u" else 2
            digits = text[index:index + size]
            if len(digits) != size or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                return None
            out.append(chr(int(digits, 16)))
            index += size
        else:
            out.append(escapes.get(escaped, escaped))
    return None


# 功能及输出：从页面初始图库JSON或已观察parseJSON字符串解码图片，不运行页面代码。
# 参数：soup（解析后的HTML树）。
def _initial_gallery(soup: BeautifulSoup) -> list[dict]:
    """JSON-decode an initial array or observed parseJSON string; never run JS."""
    images = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        marker = re.search(r"[\"']colorImages[\"']\s*:\s*\{\s*[\"']initial[\"']\s*:\s*", text)
        if not marker:
            continue
        raw_value = text[marker.end():].lstrip()
        wrapper = re.match(r"(?:A\.\$\.parseJSON|JSON\.parse)\s*\(\s*", raw_value)
        try:
            if wrapper:
                literal = raw_value[wrapper.end():]
                decoded = _read_js_string(literal)
                if not decoded or not literal[decoded[1]:].lstrip().startswith(")"):
                    continue
                value = json.loads(decoded[0])
            else:
                value, _ = json.JSONDecoder().raw_decode(raw_value)
        except (ValueError, TypeError):
            continue
        if isinstance(value, list):
            images.extend(image for image in value if isinstance(image, dict))
    return images


# 功能及输出：在商品详情相关区域读取明确排名及类目链接，返回独立商品页排名观察。
# 参数：soup（解析后的HTML树）；source_url（实际来源/最终跳转URL）。
def _parse_bsr(soup: BeautifulSoup, source_url: str) -> list[dict]:
    records = []
    containers = soup.select(DETAIL_RANK_SELECTORS)
    for el in containers:
        text = _text(el) or ""
        if not re.search(r"\bBest\s*Sellers\s*Rank\b", text, re.I):
            continue
        for match in RANK_RE.finditer(text):
            category = re.split(r"\s*\(\s*See\s+Top\s+100", match.group(2), maxsplit=1, flags=re.I)[0]
            category = category.strip(" \t\r\n)")
            if not category:
                continue
            anchor = next((a for a in el.select("a[href]") if (_text(a) or "").strip() == category), None)
            rank_url = _url(anchor.get("href"), source_url) if anchor else None
            record = {
                "rank": int(match.group(1).replace(",", "")), "category": category,
                "category_node": _node(rank_url), "source_url": source_url,
                "category_url": rank_url, "evidence_text": match.group(0).strip(),
            }
            if record["rank"] > 0 and not any((r["rank"], r["category"]) == (record["rank"], category) for r in records):
                records.append(record)
    return records


# 功能及输出：解析当前所选商品标题、五点、变体、图文、视频和BSR证据，保留缺失与阻断状态。
# 参数：html（已观察页面HTML）；source_url（实际来源/最终跳转URL）。
def parse_product(html: str, source_url: str) -> dict:
    """Extract only observed selected-product content and explicit BSR evidence."""
    soup = BeautifulSoup(html or "", "html.parser")
    result = {
        "status": "empty", "page_title": _text(soup.title), "asin": None,
        "title": None, "subtitle": None, "brand": None, "bullets": [], "description": None,
        "delivery_location_text": _delivery_location(soup),
        "aplus_text": None, "images": [], "videos": [], "excluded_videos": [], "bsr": [],
        "variants": [], "blockers": _blockers(soup), "warnings": [],
    }
    if result["blockers"]:
        result["status"] = "blocked"
        return result
    result["title"] = _text(soup.select_one("#productTitle"))
    result["subtitle"] = _text(soup.select_one("#title_feature_div .dp-title-differentiators"))
    if not result["title"]:
        result["status"] = "unexpected_page"
        result["warnings"].append("product_title_not_found")
        return result
    selected = soup.select_one("input#ASIN[value], input[name='ASIN'][value]")
    selected_asin = _valid_asin(selected.get("value")) if selected else None
    url_asin = _asin(source_url)
    result["asin"] = selected_asin or url_asin
    if selected_asin and url_asin and selected_asin != url_asin:
        result["warnings"].append(f"selected_asin_{selected_asin}_differs_from_url_{url_asin}")
    elif not selected_asin:
        result["warnings"].append("selected_asin_not_confirmed_by_page_input")
    if not result["asin"]:
        result["warnings"].append("asin_not_found")
    result["brand"] = _text(soup.select_one("#bylineInfo"))
    result["bullets"] = list(dict.fromkeys(t for el in soup.select("#feature-bullets li .a-list-item") if (t := _text(el))))
    result["content_sections"] = extract_sections(soup, source_url)
    result["description"] = result["content_sections"]["description"]["dom_text"]
    result["aplus_text"] = result["content_sections"]["aplus"]["dom_text"]
    result["bsr"] = _parse_bsr(soup, source_url)
    if not result["bsr"]:
        detail_nodes = soup.select(DETAIL_RANK_SELECTORS)
        label_present = any(re.search(r"\bBest\s*Sellers\s*Rank\b", _text(el) or "", re.I) for el in detail_nodes)
        result["warnings"].append("bsr_label_present_but_unparsed" if label_present else "bsr_not_observed")

    seen_images = set()
    image_aliases = {}
    # 功能及输出：内部追加图片候选：保留角色、主图依据和缩略图回退标记，并防重复。
    # 参数：value（待解析/校验值）；role（素材角色）；alt（源图片替代文字）；thumbnail_fallback（是否缩略图回退）；is_main（是否有主图来源依据）。
    def add_image(value: str | None, role: str, alt: str | None = None, thumbnail_fallback: bool = False, is_main: bool = False):
        url = _url(value, source_url)
        identity = _image_identity(url) if url else None
        identity = image_aliases.get(identity, identity)
        if url and (identity, role) not in seen_images:
            result["images"].append({"url": url, "role": role, "alt": alt, "is_thumbnail_fallback": thumbnail_fallback, "is_main_image": is_main, "main_image_evidence": "selected_product_landing_image" if is_main else None})
            seen_images.add((identity, role))
    initial_gallery = []
    initial_hires = set()
    preferred_gallery_by_alias = {}
    for image in _initial_gallery(soup):
        value = _url(image.get("hiRes") or image.get("large"), source_url)
        if value:
            initial_gallery.append(value)
            if image.get("hiRes"):
                initial_hires.add(value)
            # Amazon's observed thumb/large IDs can differ from the hiRes ID.
            aliases = [value, image.get("hiRes"), image.get("large"), image.get("thumb")]
            if isinstance(image.get("main"), dict):
                aliases.extend(image["main"].keys())
            for alias in aliases:
                alias_url = _url(alias, source_url)
                if alias_url:
                    key = _image_identity(alias_url)
                    image_aliases[key] = _image_identity(value)
                    preferred_gallery_by_alias[key] = value
    # Main image first; prefer an observed full-resolution version of that image.
    for el in soup.select("#landingImage, #imgBlkFront"):
        value = _url(_highres_image(el), source_url)
        if value:
            has_dom_hires = bool(el.get("data-old-hires") or el.get("data-a-dynamic-image"))
            preferred = preferred_gallery_by_alias.get(_image_identity(value))
            if preferred and (preferred in initial_hires or not has_dom_hires):
                value = preferred
            add_image(value, "gallery", el.get("alt"), is_main=True)
    for url in initial_gallery:
        add_image(url, "gallery")
    # Only append gallery thumbnails not represented in the full-size image set.
    for el in soup.select("#altImages img"):
        role = "aplus" if el.find_parent(id="aplus") else "description" if el.find_parent(id="productDescription") else "gallery"
        # Video player thumbnails belong to video discovery, not the product gallery.
        parent_text = " ".join(str(p.get("class", "")) + " " + str(p.get("id", "")) for p in [el, el.parent] if isinstance(p, Tag))
        if role == "gallery" and "video" in parent_text.casefold():
            continue
        fallback = role == "gallery" and not el.get("data-old-hires")
        add_image(_highres_image(el), role, el.get("alt"), fallback)
    for section in result["content_sections"].values():
        result["images"].extend(section["images"])

    seen_videos = set()
    for el in soup.select("video[src], video source[src]"):
        url = _url(el.get("src"), source_url)
        if not url or url in seen_videos:
            continue
        video = el if el.name == "video" else el.find_parent("video")
        path = urlsplit(url).path.casefold()
        kind = "direct" if path.endswith((".mp4", ".webm", ".mov")) else "manifest" if path.endswith((".m3u8", ".mpd")) else "unknown"
        ancestors = [video, *list(video.parents)] if video else []
        sponsored = any("sponsored" in str(node.get("aria-label", "")).casefold() or "multi-brand-video" in " ".join(node.get("class", [])) for node in ancestors if isinstance(node, Tag))
        product_region = next((str(node.get("id")) for node in ancestors if isinstance(node, Tag) and (node.get("id") in {"imageBlock", "imageBlock_feature_div", "altImages", "aplus", "productDescription"} or str(node.get("id", "")).startswith("detailpage-imageblock-player-"))), None)
        record = {"url": url, "kind": kind, "poster": _url(video.get("poster"), source_url) if video else None}
        if sponsored or not product_region:
            result["excluded_videos"].append({**record, "exclusion_reason": "sponsored_video" if sponsored else "product_ownership_unconfirmed"})
        else:
            result["videos"].append({**record, "evidence_region": product_region})
        seen_videos.add(url)
    # Amazon's product player configuration is JSON, keyed to the image block
    # and selected ASIN. Advertising players use other keys and are excluded.
    for script in soup.select('script[type="a-state"][data-a-state]'):
        try:
            state = json.loads(script["data-a-state"])
            if not str(state.get("key", "")).startswith("detailpage-imageblock-player-"):
                continue
            player = json.loads(script.get_text())
            evidence_asin = player.get("contentId") or player.get("clickstreamNexusMetricsConfig", {}).get("productId")
            if evidence_asin != result["asin"]:
                continue
            url = _url(player.get("videoUrl"), source_url)
            if not url or url in seen_videos:
                continue
            path = urlsplit(url).path.casefold()
            kind = "direct" if path.endswith((".mp4", ".webm")) else "manifest" if path.endswith((".m3u8", ".mpd")) else "unknown"
            result["videos"].append({"url": url, "kind": kind, "poster": _url(player.get("imageUrl"), source_url), "evidence_region": state["key"], "evidence_asin": evidence_asin})
            seen_videos.add(url)
            # A second player can expose an MP4 rendition of this exact video.
            # Require both the same content ID and the same selected product.
            content_id = player.get("aciContentId")
            if content_id:
                for alternate_script in soup.select('script[type="a-state"][data-a-state]'):
                    try:
                        alternate = json.loads(alternate_script.get_text())
                        alternate_asin = alternate.get("contentId") or alternate.get("clickstreamNexusMetricsConfig", {}).get("productId")
                        alternate_url = _url(alternate.get("videoUrl"), source_url)
                        if alternate.get("aciContentId") != content_id or alternate_asin != result["asin"] or not alternate_url or alternate_url in seen_videos:
                            continue
                        if not urlsplit(alternate_url).path.casefold().endswith((".mp4", ".webm")):
                            continue
                        result["videos"].append({"url": alternate_url, "kind": "direct", "poster": _url(alternate.get("imageUrl"), source_url), "evidence_region": state["key"], "evidence_asin": evidence_asin, "evidence_video_content_id": content_id})
                        seen_videos.add(alternate_url)
                    except (ValueError, TypeError, AttributeError):
                        continue
        except (ValueError, TypeError, AttributeError):
            continue
    result["videos"].sort(key=lambda video: video["kind"] != "direct")
    if not result["videos"]:
        result["warnings"].append("no_direct_video_source_observed_in_html")

    seen_variants = set()
    for el in soup.select("#twister [data-asin], #twister [data-defaultasin], [id^='variation_'] [data-asin], [id^='variation_'] [data-defaultasin], [id^='variation_'] a[href]"):
        asin = _valid_asin(el.get("data-asin")) or _valid_asin(el.get("data-defaultasin")) or _asin(el.get("href"))
        if not asin or asin in seen_variants:
            continue
        image = el.select_one("img[alt]")
        label = el.get("title") or el.get("aria-label") or (image.get("alt") if image else None) or _text(el)
        result["variants"].append({"asin": asin, "label": label, "selected": asin == selected_asin if selected_asin else None, "evidence_source": "page_dom"})
        seen_variants.add(asin)
    result["status"] = "ok"
    return result
