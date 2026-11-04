# 文件用途：采集回归测试：test_content；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
from bs4 import BeautifulSoup

from listing_ingest.content import audit_content, extract_sections, select_image_candidates

URL = "https://www.amazon.com/dp/B012345678"


# 功能及输出：构造本地测试输入夹具，返回HTML片段或图片字节供断言。
def sections(html):
    return extract_sections(BeautifulSoup(html, "html.parser"), URL)


# 验证目标：纯图片A+不误报为已取得标题正文；仅本地夹具/模拟请求，不真实采集。
def test_image_only_aplus_is_not_misreported_as_extracted_heading_text():
    result = sections('<div id="aplus"><h2>Product description</h2><div class="aplus-module"><img src="https://m.media-amazon.com/grey-pixel.gif" data-src="https://m.media-amazon.com/real.jpg"><noscript><img src="https://m.media-amazon.com/real.jpg"></noscript></div></div>')["aplus"]
    assert result["dom_text"] is None
    assert result["state"] == "image_only"
    assert len(result["images"]) == 1
    assert result["images"][0]["url"].endswith("real.jpg")


# 验证目标：图库额度不占用A+额度；仅本地夹具/模拟请求，不真实采集。
def test_section_budgets_do_not_allow_gallery_to_consume_aplus_allowance():
    images = [{"role": role, "url": f'https://m.media-amazon.com/{role}-{i}.jpg'} for role, count in (("gallery", 8), ("aplus", 7), ("description", 2)) for i in range(count)]
    selected, budgets = select_image_candidates({"images": images}, {"max_images_per_product": 4})
    assert len(selected) == 13
    assert budgets["gallery"]["selected"] == 4
    assert budgets["aplus"]["selected"] == 7
    assert budgets["description"]["selected"] == 2


# 验证目标：重复图片保留模块位置但不重复下载；仅本地夹具/模拟请求，不真实采集。
def test_repeated_image_preserves_module_placements_without_duplicate_downloads():
    result = sections('<div id="aplus"><div class="aplus-module"><img src="https://m.media-amazon.com/same.jpg"></div><div class="aplus-module"><p>Second module</p><img src="https://m.media-amazon.com/same.jpg"></div></div>')["aplus"]
    assert [m["order"] for m in result["modules"]] == [1, 2]
    assert len(result["images"]) == 1
    assert [p["module_order"] for p in result["images"][0]["placements"]] == [1, 2]
    assert result["modules"][1]["dom_text"] == "Second module"


# 验证目标：空容器不能证明商品没有详情；仅本地夹具/模拟请求，不真实采集。
def test_empty_container_is_not_evidence_that_product_has_no_description():
    result = sections('<div id="productDescription_feature_div"><div></div></div>')["description"]
    assert result["state"] == "empty_container"
    assert result["dom_text"] is None
    assert result["missing_reason"] == "no_substantive_content_returned_in_snapshot"


# 验证目标：内联背景图片与普通详情可提取；仅本地夹具/模拟请求，不真实采集。
def test_inline_background_image_and_ordinary_description_are_captured():
    result = sections('''<div id="productDescription"><p>Observed text</p><img src="https://m.media-amazon.com/detail.jpg"></div><div id="aplus"><div class="aplus-module" style="background-image: url('https://m.media-amazon.com/banner.jpg')"></div></div>''')
    assert result["description"]["state"] == "mixed"
    assert result["description"]["dom_text"] == "Observed text"
    assert result["aplus"]["images"][0]["url"].endswith("banner.jpg")


# 验证目标：归档图片、待OCR和缺失媒体分别审计；仅本地夹具/模拟请求，不真实采集。
def test_audit_distinguishes_archived_images_from_pending_ocr_and_missing_assets():
    source = sections('<div id="aplus"><img src="https://m.media-amazon.com/one.jpg"><img src="https://m.media-amazon.com/two.jpg"></div>')
    product = {"parsed": {"content_sections": source}, "media": [{"kind": "image", "role": "aplus", "source_url": "https://m.media-amazon.com/one.jpg", "status": "stored", "ocr": {"status": "failed"}}]}
    audit = audit_content(product)["aplus"]
    assert audit["acquisition_status"] == "partial"
    assert audit["missing_images"] == ["https://m.media-amazon.com/two.jpg"]
    assert audit["ocr_pending_images"] == ["https://m.media-amazon.com/one.jpg"]


# 验证目标：限额截断有明确记录；仅本地夹具/模拟请求，不真实采集。
def test_limit_truncation_is_explicit():
    _, budgets = select_image_candidates({"images": [{"role": "aplus", "url": str(i)} for i in range(6)]}, {"max_images_per_product": 4, "max_aplus_images_per_product": 2})
    assert budgets["aplus"]["truncated"] == 4


# 验证目标：srcset解析保留Amazon裁切URL内逗号；仅本地夹具/模拟请求，不真实采集。
def test_picture_srcset_keeps_commas_inside_amazon_crop_urls():
    result = sections('<div id="aplus"><picture><source srcset="https://m.media-amazon.com/one.__CR0,0,600,300___.jpg 600w, https://m.media-amazon.com/two.__CR0,0,1464,600___.jpg 1464w"><img src="https://m.media-amazon.com/grey-pixel.gif"></picture></div>')["aplus"]
    assert result["images"][0]["url"] == "https://m.media-amazon.com/two.__CR0,0,1464,600___.jpg"
