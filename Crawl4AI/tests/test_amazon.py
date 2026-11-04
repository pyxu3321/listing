# 文件用途：采集回归测试：test_amazon；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
from listing_ingest.amazon import parse_bestsellers, parse_product


BSR_URL = "https://www.amazon.com/gp/bestsellers/home-garden/8521807011"
PRODUCT_URL = "https://www.amazon.com/dp/B012345678"


# 功能及输出：构造本地测试输入夹具，返回HTML片段或图片字节供断言。
def ranking_page(cards, extra=""):
    return f'<html><title>Amazon Best Sellers</title><h1 id="zg_banner_text">Best Sellers in Mattress Toppers</h1>{cards}{extra}</html>'


# 功能及输出：构造本地测试输入夹具，返回HTML片段或图片字节供断言。
def card(rank, asin="B012345678"):
    return f'<div class="zg-grid-general-faceout"><span class="zg-bdg-text">#{rank}</span><a href="/dp/{asin}"><img alt="Product topper"></a><a href="/dp/{asin}"><div class="p13n-sc-truncate">A topper</div></a></div>'


# 功能及输出：构造本地测试输入夹具，返回HTML片段或图片字节供断言。
def product(body="", asin="B012345678"):
    return f'<html><title>Example product</title><span id="productTitle">Example topper</span><input id="ASIN" value="{asin}">{body}</html>'


# 验证目标：显式BSR卡片保留名次和分页；仅本地夹具/模拟请求，不真实采集。
def test_explicit_bsr_cards_preserve_rank_and_pagination():
    data = parse_bestsellers(ranking_page(card(51) + card(52, "B098765432"), '<li class="a-last"><a href="/gp/bestsellers/home-garden/8521807011?pg=3">Next</a></li>'), BSR_URL + "?pg=2")
    assert data["status"] == "ok"
    assert [i["rank"] for i in data["items"]] == [51, 52]
    assert data["items"][0]["rank_type"] == "bsr_category"
    assert data["items"][0]["evidence_text"] == "#51"
    assert data["items"][0]["title"] == "A topper"
    assert data["next_page_url"].endswith("?pg=3")


# 验证目标：搜索页即使有徽标也不能提供BSR；仅本地夹具/模拟请求，不真实采集。
def test_search_page_cannot_supply_bsr_even_with_a_badge():
    data = parse_bestsellers(ranking_page(card(1)), "https://www.amazon.com/s?rh=n%3A8521807011&s=popularity-rank")
    assert data["status"] == "unexpected_page"
    assert not data["items"]


# 验证目标：榜单标题和类目必须同时匹配；仅本地夹具/模拟请求，不真实采集。
def test_heading_and_category_both_required():
    assert parse_bestsellers('<title>Amazon Best Sellers Mattress Toppers</title>' + card(1), BSR_URL)["status"] == "unexpected_page"
    assert parse_bestsellers(ranking_page(card(1)), BSR_URL.replace("8521807011", "12345"))["status"] == "unexpected_page"
    wrong = '<link rel="canonical" href="https://www.amazon.com/gp/bestsellers/home-garden/99999">'
    assert parse_bestsellers(ranking_page(card(1), wrong), BSR_URL)["status"] == "unexpected_page"


# 验证目标：不推测名次且不分配含糊容器；仅本地夹具/模拟请求，不真实采集。
def test_no_rank_inference_and_ambiguous_container_not_assigned():
    data = parse_bestsellers(ranking_page('<div><a href="/dp/B012345678">Product without a badge</a></div>'), BSR_URL)
    assert data["status"] == "empty"
    mixed = '<div><span class="zg-bdg-text">#1</span><a href="/dp/B012345678">One</a><a href="/dp/B098765432">Two</a></div>'
    assert not parse_bestsellers(ranking_page(mixed), BSR_URL)["items"]


# 验证目标：同ASIN出现在不同名次时保留异常；仅本地夹具/模拟请求，不真实采集。
def test_duplicate_asin_at_different_ranks_is_visible():
    data = parse_bestsellers(ranking_page(card(1) + card(2)), BSR_URL)
    assert len(data["items"]) == 2
    assert any("multiple_explicit_ranks" in warning for warning in data["warnings"])


# 验证目标：HTTP200阻断页不当作内容成功；仅本地夹具/模拟请求，不真实采集。
def test_blocked_200_page_is_not_content_success():
    html = '<title>Amazon.com</title><p>Click the button below to continue shopping</p><button>Continue shopping</button>'
    assert parse_bestsellers(html, BSR_URL)["status"] == "blocked"
    result = parse_product(html, PRODUCT_URL)
    assert result["status"] == "blocked"
    assert not result["images"]


# 验证目标：商品BSR限定在详情区域并匹配类目链接；仅本地夹具/模拟请求，不真实采集。
def test_product_bsr_is_scoped_to_details_and_matches_category_link():
    html = product('''<table id="productDetails_detailBullets_sections1"><tr><th>Best Sellers Rank</th><td>#1,234 in Home &amp; Kitchen (See Top 100 in Home &amp; Kitchen)<br>#9 in <a href="/gp/bestsellers/home-garden/8521807011">Mattress Toppers</a></td></tr></table><div id="reviews">#1 in Fake Category</div>''')
    result = parse_product(html, PRODUCT_URL)
    assert result["status"] == "ok"
    assert [(r["rank"], r["category"]) for r in result["bsr"]] == [(1234, "Home & Kitchen"), (9, "Mattress Toppers")]
    assert result["bsr"][1]["category_node"] == "8521807011"
    assert result["bsr"][0]["category_node"] is None


# 验证目标：详情名次、项目符号文字和缺失BSR分开；仅本地夹具/模拟请求，不真实采集。
def test_detail_bullet_bsr_and_missing_bsr_remain_distinct():
    html = product('<div id="detailBullets_feature_div"><ul><li><span>Best Sellers Rank: #42 in <a href="/gp/bestsellers/home-garden/8521807011">Mattress Toppers</a></span></li></ul></div>')
    assert parse_product(html, PRODUCT_URL)["bsr"][0]["rank"] == 42
    absent = parse_product(product('<div>#8 in Mattress Toppers</div>'), PRODUCT_URL)
    assert absent["bsr"] == []
    assert "bsr_not_observed" in absent["warnings"]
    unparsed = parse_product(product('<div id="detailBullets_feature_div"><li>Best Sellers Rank: unavailable</li></div>'), PRODUCT_URL)
    assert "bsr_label_present_but_unparsed" in unparsed["warnings"]


# 验证目标：高清图库与A+角色保持区分；仅本地夹具/模拟请求，不真实采集。
def test_high_resolution_images_keep_gallery_and_aplus_roles():
    html = product('''<img id="landingImage" src="https://m.media-amazon.com/thumb.jpg" data-a-dynamic-image='{"https://m.media-amazon.com/small.jpg":[200,200],"https://m.media-amazon.com/large.jpg":[1200,1200]}' alt="Product"><div id="aplus"><img src="https://m.media-amazon.com/large.jpg" alt="Detail"></div>''')
    images = parse_product(html, PRODUCT_URL)["images"]
    assert len(images) == 2
    assert images[0]["url"].endswith("large.jpg")
    assert {i["role"] for i in images} == {"gallery", "aplus"}


# 验证目标：初始图库仅解码JSON不执行JavaScript；仅本地夹具/模拟请求，不真实采集。
def test_initial_gallery_json_only_not_javascript_evaluation():
    html = product('''<script>var data = {'colorImages': {'initial': [{"hiRes":"https://m.media-amazon.com/full.jpg","large":"https://m.media-amazon.com/low.jpg"}]}};</script><script>var other = {"images":[{"hiRes":"https://m.media-amazon.com/recommendation.jpg"}]};</script>''')
    assert [i["url"] for i in parse_product(html, PRODUCT_URL)["images"]] == ["https://m.media-amazon.com/full.jpg"]


# 验证目标：优先完整原图且不重复下载缩略图；仅本地夹具/模拟请求，不真实采集。
def test_gallery_prioritizes_full_images_and_does_not_duplicate_thumbnails():
    html = product('''<img id="landingImage" src="https://m.media-amazon.com/images/I/first._AC_US40_.jpg"><div id="altImages"><img src="https://m.media-amazon.com/images/I/first._AC_US40_.jpg"><img src="https://m.media-amazon.com/images/I/second._AC_US40_.jpg"><img src="https://m.media-amazon.com/images/I/third._AC_US40_.jpg"></div><script>var data = {'colorImages': {'initial': [{"hiRes":"https://m.media-amazon.com/images/I/first._AC_SL1500_.jpg"},{"hiRes":"https://m.media-amazon.com/images/I/second._AC_SL1500_.jpg"}]}};</script>''')
    images = parse_product(html, PRODUCT_URL)["images"]
    assert len(images) == 3
    assert images[0]["url"].endswith("first._AC_SL1500_.jpg")
    assert images[1]["url"].endswith("second._AC_SL1500_.jpg")
    assert images[0]["is_thumbnail_fallback"] is False
    assert images[2]["is_thumbnail_fallback"] is True


# 验证目标：所选ASIN与已观察变体分别记录；仅本地夹具/模拟请求，不真实采集。
def test_selected_asin_and_observed_variants():
    html = product('<div id="variation_size_name"><li data-defaultasin="B098765432" title="Queen"></li><li data-defaultasin="B011112222" title="King"></li></div>', asin="B098765432")
    data = parse_product(html, PRODUCT_URL)
    assert data["asin"] == "B098765432"
    assert any("differs_from_url" in warning for warning in data["warnings"])
    assert data["variants"][0]["selected"] is True
    assert data["variants"][1]["selected"] is False


# 验证目标：视频清单不当已下载视频且blob不当直接URL；仅本地夹具/模拟请求，不真实采集。
def test_video_manifest_is_not_a_downloaded_video_and_blob_is_not_url():
    html = product('<div id="imageBlock"><video poster="/poster.jpg"><source src="https://example.com/video.mp4"></video><video src="https://example.com/video.m3u8"></video><video src="blob:1234"></video></div>')
    videos = parse_product(html, PRODUCT_URL)["videos"]
    assert [v["kind"] for v in videos] == ["direct", "manifest"]
    assert videos[0]["poster"] == "https://www.amazon.com/poster.jpg"


# 验证目标：缺少标题不宣称商品成功；仅本地夹具/模拟请求，不真实采集。
def test_missing_title_never_claims_product_success():
    result = parse_product('<h1>Amazon Search</h1><img id="landingImage" src="https://example.com/a.jpg">', PRODUCT_URL)
    assert result["status"] == "unexpected_page"
    assert not result["images"]


# 验证目标：已观察parseJSON图库能关联不同缩略图ID；仅本地夹具/模拟请求，不真实采集。
def test_observed_parsejson_gallery_maps_different_thumbnail_ids():
    html = product('''<img id="landingImage" src="https://m.media-amazon.com/images/I/thumb._AC_US40_.jpg"><div id="altImages"><img src="https://m.media-amazon.com/images/I/thumb._AC_US40_.jpg"></div><script>var data = {'colorImages': {'initial': A.$.parseJSON('[{"hiRes":"https://m.media-amazon.com/images/I/full._AC_SL1500_.jpg","thumb":"https://m.media-amazon.com/images/I/thumb._AC_US40_.jpg"}]')}};</script>''')
    images = parse_product(html, PRODUCT_URL)["images"]
    assert len(images) == 1
    assert images[0]["url"].endswith("full._AC_SL1500_.jpg")
    assert images[0]["is_thumbnail_fallback"] is False


# 验证目标：新详情表排名与配送位置分别观察；仅本地夹具/模拟请求，不真实采集。
def test_new_details_table_bsr_and_delivery_are_observed_separately():
    html = product('''<span id="glow-ingress-line2">Delivering to Goodyear 85395</span><div id="productDetails_feature_div"><table><tr><th>Best Sellers Rank</th><td>#10 in Home &amp; Kitchen (See Top 100 in Home &amp; Kitchen)<br>#1 in <a href="/gp/bestsellers/home-garden/8521807011">Mattresses Toppers</a></td></tr></table></div>''')
    result = parse_product(html, PRODUCT_URL)
    assert [r["rank"] for r in result["bsr"]] == [10, 1]
    assert result["bsr"][1]["category_node"] == "8521807011"
    assert "Goodyear 85395" in result["delivery_location_text"]


# 验证目标：广告和归属不明视频不进入商品媒体；仅本地夹具/模拟请求，不真实采集。
def test_ads_and_unscoped_videos_never_become_product_media():
    html = product('<video aria-label="Sponsored video, click to navigate" src="https://m.media-amazon.com/ad.mp4"></video><video src="https://m.media-amazon.com/unknown.mp4"></video><div id="detailpage-imageblock-player-example"><video src="https://m.media-amazon.com/product.mp4"></video></div>')
    result = parse_product(html, PRODUCT_URL)
    assert [v["url"] for v in result["videos"]] == ["https://m.media-amazon.com/product.mp4"]
    assert [v["exclusion_reason"] for v in result["excluded_videos"]] == ["sponsored_video", "product_ownership_unconfirmed"]


# 验证目标：播放器JSON必须匹配所选ASIN与图片区域；仅本地夹具/模拟请求，不真实采集。
def test_product_player_json_requires_selected_asin_and_imageblock_key():
    html = product('''<script type="a-state" data-a-state='{"key":"detailpage-imageblock-player-one"}'>{"contentId":"B012345678","videoUrl":"https://m.media-amazon.com/product.mp4"}</script><script type="a-state" data-a-state='{"key":"detailpage-imageblock-player-two"}'>{"contentId":"B098765432","videoUrl":"https://m.media-amazon.com/other.mp4"}</script><script type="a-state" data-a-state='{"key":"ad-player"}'>{"contentId":"B012345678","videoUrl":"https://m.media-amazon.com/ad.mp4"}</script>''')
    result = parse_product(html, PRODUCT_URL)
    assert [v["url"] for v in result["videos"]] == ["https://m.media-amazon.com/product.mp4"]


# 验证目标：MP4转码候选必须匹配商品和视频内容ID；仅本地夹具/模拟请求，不真实采集。
def test_mp4_rendition_requires_matching_product_and_video_content_id():
    html = product('''<script type="a-state" data-a-state='{"key":"detailpage-imageblock-player-one"}'>{"contentId":"B012345678","aciContentId":"video-one","videoUrl":"https://m.media-amazon.com/product.m3u8"}</script><script type="a-state" data-a-state='{"key":"mobile-player"}'>{"clickstreamNexusMetricsConfig":{"productId":"B012345678"},"aciContentId":"video-one","videoUrl":"https://m.media-amazon.com/product.mp4"}</script><script type="a-state" data-a-state='{"key":"another-player"}'>{"contentId":"B012345678","aciContentId":"video-other","videoUrl":"https://m.media-amazon.com/unrelated.mp4"}</script>''')
    videos = parse_product(html, PRODUCT_URL)["videos"]
    assert [v["kind"] for v in videos] == ["direct", "manifest"]
    assert videos[0]["url"] == "https://m.media-amazon.com/product.mp4"


# 验证目标：只有已观察主展示图标为主图；仅本地夹具/模拟请求，不真实采集。
def test_only_observed_landing_image_is_marked_main():
    html = product('<img id="landingImage" src="https://m.media-amazon.com/main.jpg"><div id="altImages"><img src="https://m.media-amazon.com/secondary.jpg"></div>')
    images = parse_product(html, PRODUCT_URL)["images"]
    assert [m["url"] for m in images if m["is_main_image"]] == ["https://m.media-amazon.com/main.jpg"]
    without_main = parse_product(product('<div id="altImages"><img src="https://m.media-amazon.com/secondary.jpg"></div>'), PRODUCT_URL)
    assert not any(m["is_main_image"] for m in without_main["images"])
