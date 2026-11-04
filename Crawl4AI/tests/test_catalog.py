# 文件用途：采集回归测试：test_catalog；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
import json
import pytest
from listing_ingest.catalog import classification, product_identity
from listing_ingest.export_products import export_products


# 验证目标：分类导出路径与元数据一致；仅本地夹具/模拟请求，不真实采集。
def test_export_grouping_and_metadata(tmp_path):
    report = {'config': {'marketplace': 'US', 'site_id': 'amazon', 'category_id': 'toppers'}, 'source_id': 'test', 'run_id': 'batch', 'pages': [], 'rank_observations': [], 'products': [{'parsed': {'asin': 'B012345678', 'title': 'Example', 'bullets': ['Soft']}, 'status': 'ok', 'snapshot_id': 'snapshot', 'media': []}]}
    result = export_products(report, tmp_path)
    folder = tmp_path / 'products/US/amazon/toppers/B012345678/batch'
    assert folder.is_dir()
    links = json.loads((folder / '素材关联.json').read_text(encoding='utf-8'))
    assert links['identity']['site_id'] == 'amazon'
    assert links['identity']['product_id'] == 'B012345678'
    assert result['layout_version'] == 2
    report['config'].update(site_id='brand', category_id='foam-pads')
    report['products'][0]['parsed'] = {'product_id': 'pad-123', 'title': 'Pad'}
    export_products(report, tmp_path)
    assert (tmp_path / 'products/US/brand/foam-pads/pad-123/batch/商品信息.json').is_file()


# 验证目标：旧类目配置与URL哈希身份回退；仅本地夹具/模拟请求，不真实采集。
def test_legacy_category_and_url_fallback():
    assert classification({'marketplace': 'US', 'category_node': '8521807011'})['category_id'] == 'toppers'
    config = {'marketplace': 'US', 'site_id': 'brand', 'category_id': 'toppers'}
    product = {'requested_url': 'https://example.com/pad', 'parsed': {}}
    assert product_identity(config, product) == product_identity(config, product)
    assert product_identity(config, product)['product_id'].startswith('url-')


@pytest.mark.parametrize('field,value', [('site_id', '../escape'), ('category_id', 'CON'), ('country_code', 'US/../../')])
# 验证目标：拒绝不安全分类字段；仅本地夹具/模拟请求，不真实采集。
def test_unsafe_classification_rejected(field, value):
    with pytest.raises(ValueError):
        classification({'marketplace': 'US', 'site_id': 'amazon', 'category_id': 'toppers', field: value})
