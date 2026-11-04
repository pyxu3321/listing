# 文件用途：采集回归测试：test_runner；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
import json
from pathlib import Path

import pytest

from listing_ingest.runner import PROJECT, load_config, render_report, select_products, validate_page_url


# 验证目标：显式商品不被榜单数量上限挤掉；仅本地夹具/模拟请求，不真实采集。
def test_explicit_product_is_not_lost_to_ranking_limit():
    ranked = [{'asin': 'B012345678', 'url': 'https://www.amazon.com/dp/B012345678', 'rank': 1}]
    selected = select_products(ranked, ['https://www.amazon.com/dp/B087654321'], 1)
    assert selected[0]['asin'] == 'B087654321'
    assert selected[0]['rank'] is None
    selected = select_products(ranked, ['https://www.amazon.com/dp/B012345678?ref=test'], 3)
    assert len(selected) == 1
    assert selected[0]['rank'] == 1


# 验证目标：拒绝非Amazon页及嵌入凭据URL；仅本地夹具/模拟请求，不真实采集。
def test_rejects_non_amazon_page_and_embedded_credentials():
    for url in ('http://www.amazon.com/dp/B012345678', 'https://www.amazon.com.attacker.test/', 'https://localhost/', 'https://name:secret@www.amazon.com/', 'https://www.amazon.com:8443/'):
        with pytest.raises(ValueError):
            validate_page_url(url)


# 验证目标：浏览器启动前拒绝无界配置；仅本地夹具/模拟请求，不真实采集。
def test_rejects_unbounded_config_before_crawl(tmp_path):
    config = json.loads((PROJECT / 'config/topper-us.json').read_text(encoding='utf-8'))
    config['max_products'] = 10000
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


# 验证目标：报告转义页面文本且兼容缺失截图；仅本地夹具/模拟请求，不真实采集。
def test_report_escapes_page_text_and_handles_missing_screenshot(tmp_path):
    directory = tmp_path / 'runs/test'
    directory.mkdir(parents=True)
    report = {
        'run_id': 'test', 'started_at_shanghai': 'test', 'status': 'blocked',
        'pages': [{'kind': 'bsr', 'status': 'blocked', 'parsed': {'page_title': '<script>alert(1)</script>', 'blockers': ['<blocked>']}}],
        'products': [], 'rank_observations': [],
    }
    path = render_report(report, directory, tmp_path)
    text = path.read_text(encoding='utf-8')
    assert '<script>alert' not in text
    assert '&lt;script&gt;' in text
    assert '未取得可验证的榜单排名' in text


# 验证目标：按显式排名而非原数组顺序排商品队列；仅本地夹具/模拟请求，不真实采集。
def test_ranked_queue_uses_explicit_rank_instead_of_input_order():
    items = [{'asin': f'B{i:09d}', 'url': f'https://www.amazon.com/dp/B{i:09d}', 'rank': i} for i in (50, 3, 1, 2)]
    assert [p['rank'] for p in select_products(items, [], 50)] == [1, 2, 3, 50]
