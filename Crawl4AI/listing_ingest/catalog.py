# 文件用途：国家/站点/品类路径与商品身份规范化；Amazon使用ASIN，独立站身份只是预留，不表示已接入采集器。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Site-independent catalogue identity, separate from crawl adapters."""
import hashlib
import re


# 功能及输出：校验目录片段，拒绝路径穿越和Windows保留名，返回原有效字符串。
# 参数：value（待解析/校验值）。
def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value):
        raise ValueError("Invalid catalogue path component")
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("Reserved catalogue path component")
    return value


# 功能及输出：从配置规范国家/站点/内部品类；兼容旧topper配置，返回三个分类字段。
# 参数：config（规范化采集配置）。
def classification(config):
    site = config.get("site_id", "amazon" if config.get("source_type", "amazon_bestsellers").startswith("amazon") else None)
    category = config.get("category_id")
    if category is None:
        category = "toppers" if str(config.get("category_node")) == "8521807011" else "node-" + str(config.get("category_node", "unknown"))
    return {"country_code": segment(config.get("country_code", config.get("marketplace"))), "site_id": segment(site), "category_id": segment(category)}


# 功能及输出：结合配置与商品记录产生身份；Amazon使用ASIN，其他站点可用显式ID或来源URL哈希。
# 参数：config（规范化采集配置）；product（当前商品快照记录）。
def product_identity(config, product):
    result = classification(config)
    parsed = product.get("parsed", {})
    if result["site_id"] == "amazon":
        product_id = parsed.get("asin")
        if not isinstance(product_id, str) or not re.fullmatch(r"[A-Z0-9]{10}", product_id):
            raise ValueError("Confirmed ASIN required for Amazon product")
        basis = "asin"
    else:
        product_id = parsed.get("product_id")
        basis = "site_product_id"
        if not product_id:
            url = product.get("requested_url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError("Site product ID or original HTTPS URL required")
            product_id = "url-" + hashlib.sha256(url.encode()).hexdigest()[:24]
            basis = "exact_source_url_sha256"
    result.update(product_id=segment(product_id), product_id_basis=basis)
    return result
