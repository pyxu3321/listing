# 文件用途：同商品/快照/DOM模块的显式素材关联；不推断图片与某条五点的卖点对应关系。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
"""Evidence links, not inferred selling-point alignment."""
import hashlib
import json
from .catalog import product_identity


# 功能及输出：返回schema2关联记录：商品身份、文本、DOM模块、媒体引用；semantic_links为空待第二阶段分析。
# 参数：report（采集报告）；product（当前商品快照记录）；media（媒体记录集合或单图记录）。
def build_links(report: dict, product: dict, media: list[dict]) -> dict:
    parsed = product.get("parsed", {})
    identity = {"source_id": report["source_id"], "marketplace": report["config"]["marketplace"], "asin": parsed.get("asin"), "snapshot_id": product["snapshot_id"], "run_id": report["run_id"]}
    try:
        identity.update(product_identity(report["config"], product))
    except ValueError:
        if parsed.get("asin"):
            raise
        # Failed/unidentified captures may be inspected but not exported.
        identity["product_id"] = None
    # 功能及输出：以当前身份、类型与位置计算稳定关联ID，非随机商品编号。
    # 参数：kind（图片/视频或关联类型）；position（来源位置序号）。
    def identifier(kind, position):
        return hashlib.sha256(json.dumps([identity, kind, position], sort_keys=True).encode()).hexdigest()[:32]
    texts = []
    for kind, values in (("title", [parsed.get("title")]), ("bullet", parsed.get("bullets", [])), ("description", [parsed.get("description")]), ("aplus", [parsed.get("aplus_text")])):
        for index, text in enumerate(values, 1):
            if text:
                texts.append({"text_id": identifier(kind, index), "kind": kind, "sequence": index, "text": text})
    modules = []
    for role, section in parsed.get("content_sections", {}).items():
        for module in section.get("modules", []):
            modules.append({"module_key": identifier(role, module["module_id"]), "role": role, "source_module_id": module["module_id"], "order": module.get("order"), "dom_text": module.get("dom_text"), "image_urls": [x["url"] for x in module.get("images", [])]})
    references = []
    for index, item in enumerate(media, 1):
        references.append({"reference_id": identifier("media", index), "asset_sha256": item.get("sha256"), "kind": item.get("kind"), "role": item.get("role"), "status": item.get("status"), "is_main_image": item.get("is_main_image", False), "source_url": item.get("source_url"), "export_path": item.get("export_path"), "module_keys": [m["module_key"] for m in modules if m["role"] == item.get("role") and item.get("source_url") in m["image_urls"]]})
    # 此处仅生成显式来源/DOM关联；semantic_links留空，交由第二阶段分析卖点关系。
    return {"schema_version": 2, "identity": identity, "source_metadata": {k: report["config"].get(k) for k in ("country", "language", "category_node", "category_name", "description", "tags")}, "variants_observed": parsed.get("variants", []), "variant_scope": "selected_product_only_other_variants_not_assumed", "texts": texts, "modules": modules, "media_references": references, "semantic_links": [], "semantic_links_status": "pending_stage2_analysis", "note": "Shared product/snapshot and explicit DOM modules are evidence; no image-to-bullet semantic correspondence is inferred."}
