# 文件用途：采集回归测试：test_sources_links；使用本地HTML、临时文件和模拟网络验证边界，不进行真实采集。
# 注释核对：2026-11-03仅补中文备注，不改变原有代码语句、配置或采集数据。
import asyncio
import json
import pytest
from listing_ingest.sources import plan, execute
from listing_ingest.runner import PROJECT
from listing_ingest.material_links import build_links
from listing_ingest.amazon import parse_bestsellers


# 验证目标：多来源可读取且拒绝重复ID；仅本地夹具/模拟请求，不真实采集。
def test_registry_multiple_sources_and_duplicate_rejected(tmp_path):
    config = json.loads((PROJECT / 'config/topper-us.json').read_text(encoding='utf-8'))
    entries = []
    for name in ('one', 'two'):
        config['source_id'] = name
        (tmp_path / (name + '.json')).write_text(json.dumps(config))
        entries.append({'source_id': name, 'config': name + '.json'})
    registry = tmp_path / 'sources.json'
    registry.write_text(json.dumps({'schema_version': 1, 'sources': entries}))
    assert len(plan(registry)) == 2
    assert len(plan(registry, ['two'])) == 1
    entries.append(entries[0])
    registry.write_text(json.dumps({'schema_version': 1, 'sources': entries}))
    with pytest.raises(ValueError):
        plan(registry)


# 验证目标：一个来源失败仍执行下一来源；仅本地夹具/模拟请求，不真实采集。
def test_source_failure_does_not_skip_next(monkeypatch):
    # 功能及输出：模拟来源执行或视频探测，替代真实网络/解码器以验证边界。
    async def fake(config, library_override=None):
        if config['source_id'] == 'bad':
            raise RuntimeError('failed source')
        return {'status': 'success'}, PROJECT
    monkeypatch.setattr('listing_ingest.sources.run', fake)
    tasks = [{'source_id': k, 'config': {'source_id': k}} for k in ('bad', 'good')]
    result = asyncio.run(execute(tasks))
    assert [x['status'] for x in result['sources']] == ['failed', 'success']


# 验证目标：模块链接与快照身份一致；仅本地夹具/模拟请求，不真实采集。
def test_module_links_and_snapshot_identity():
    report = {'source_id': 'test', 'run_id': 'run', 'config': {'marketplace': 'US'}}
    product = {'snapshot_id': 'snap', 'parsed': {'asin': 'B012345678', 'title': 'Title', 'bullets': ['First', 'Second'], 'content_sections': {'aplus': {'modules': [{'module_id': 'm1', 'order': 1, 'dom_text': 'Module', 'images': [{'url': 'image'}]}]}}}}
    media = [{'source_url': 'image', 'role': 'aplus', 'kind': 'image', 'status': 'stored', 'sha256': 'hash'}]
    result = build_links(report, product, media)
    assert len(result['texts']) == 3
    assert result['media_references'][0]['module_keys'] == [result['modules'][0]['module_key']]
    assert result['semantic_links'] == []
    product['snapshot_id'] = 'new'
    assert build_links(report, product, media)['texts'][0]['text_id'] != result['texts'][0]['text_id']


# 验证目标：可配置类目仍拒绝错误节点和搜索页；仅本地夹具/模拟请求，不真实采集。
def test_configurable_category_does_not_accept_wrong_node_or_search():
    body = '<h1>Best Sellers in Pillows</h1><div><span class="zg-bdg-text">#1</span><a href="/dp/B012345678">Pillow</a></div>'
    result = parse_bestsellers(body, 'https://www.amazon.com/zgbs/home-garden/12345', '12345', 'Pillows')
    assert result['items'][0]['category_node'] == '12345'
    assert parse_bestsellers(body, 'https://www.amazon.com/zgbs/home-garden/999', '12345', 'Pillows')['status'] == 'unexpected_page'
    assert parse_bestsellers(body, 'https://www.amazon.com/s?rh=n:12345', '12345', 'Pillows')['items'] == []



# 验证目标：内联默认覆盖及适配器范围；仅本地夹具/模拟请求，不真实采集。
def test_inline_defaults_overrides_and_adapter_boundary(tmp_path):
    from listing_ingest.sources import normalize_sources
    row = {'id': 'first', 'url': 'https://www.amazon.com/zgbs/home-garden/8521807011', 'marketplace': 'US', 'language': 'en-US', 'category_node': '8521807011', 'category_name': 'Mattress Toppers'}
    doc = {'defaults': {'max_products': 20}, 'sources': [row, {**row, 'id': 'second', 'max_products': 3}]}
    before = json.dumps(doc)
    tasks = normalize_sources(doc)
    assert [t['config']['max_products'] for t in tasks] == [20, 3]
    assert tasks[0]['config']['ranking_url'] == row['url']
    assert tasks[0]['config']['max_videos_per_product'] == 0
    assert json.dumps(doc) == before
    path = tmp_path / 'sources.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    assert plan(path) == tasks


@pytest.mark.parametrize('update', [{'max_products': 51}, {'marketplace': 'DE'}, {'url': 'https://example.com'}, {'enabled': 'yes'}])
# 验证目标：拒绝无效内联来源；仅本地夹具/模拟请求，不真实采集。
def test_inline_invalid_source_rejected(update):
    from listing_ingest.sources import normalize_sources
    row = {'id': 'first', 'url': 'https://www.amazon.com/zgbs/home-garden/8521807011', 'marketplace': 'US', 'category_node': '8521807011', 'category_name': 'Mattress Toppers'}
    with pytest.raises(ValueError):
        normalize_sources({'sources': [{**row, **update}]})


# 验证目标：禁用市场与未知来源选择被拒绝；仅本地夹具/模拟请求，不真实采集。
def test_disabled_market_and_unknown_selection():
    from listing_ingest.sources import normalize_sources
    row = {'id': 'first', 'url': 'https://www.amazon.com/zgbs/home-garden/8521807011', 'marketplace': 'US', 'category_node': '8521807011', 'category_name': 'Mattress Toppers'}
    doc = {'sources': [row, {'id': 'future-de', 'enabled': False, 'marketplace': 'DE'}]}
    assert len(normalize_sources(doc)) == 1
    for selected in (['future-de'], ['missing']):
        with pytest.raises(ValueError):
            normalize_sources(doc, selected)
