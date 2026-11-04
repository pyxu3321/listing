# 第一阶段配置核对

更新：2026-11-03。原始JSON保持原值和严格格式不变，逐字段中文说明见 [配置逐项注释.jsonc](配置逐项注释.jsonc)。对照文件不可直接运行。

| 文件 | 使用入口 | 说明 |
| --- | --- | --- |
| sources.json | python -m listing_ingest.sources | 多来源注册表；统一配置多个URL和每个来源的国家/站点/品类说明 |
| topper-us.json | run_topper.ps1 或 python -m listing_ingest | 原单来源入口，保留兼容；不自动读取sources.json |

## 多来源合并顺序

sources.py内置DEFAULTS → sources.json的defaults → sources每项配置。浅层覆盖，不递归合并。旧config字段可引用单来源文件，但不能同时给inline URL；以后Excel/SQL读取器可转换成相同结构，当前尚未实现。

注册表url会映射为ranking_url；id会映射为source_id。当前US Amazon BSR适配器会核对站点、类目及显式排名。改成其他国家/网站并不能自动启用其采集能力。

## 优先核对这些参数

- country_code/site_id/category_id决定分类目录：国家/网站/品类/商品/批次。
- ranking_url和category_node/category_name要对应同一真实榜单；discovery_url仅作发现，不作BSR。
- 图库、普通详情、A+分别限额；视频用独立max_videos_per_product，和图库4张无关。
- max_products限制访问商品详情数量；0不等于离线，不要用来做纯配置检查。
- 多来源真正的无联网检查使用sources入口的--plan。
- OCR语言可能回退，返回文字需要核对原图；不覆盖DOM原文。

## 只读计划示例

```powershell
Set-Location -LiteralPath 'D:\Crawl4AI'
& 'D:\python\python.exe' -m listing_ingest.sources --sources 'D:\Crawl4AI\config\sources.json' --plan
```

实际执行多来源时移除--plan，可重复--source来源ID做筛选；详情命令见 [多来源说明](../docs/多来源与素材关联.md)。

## 视频两种入口

常规采集遵循配置额度及普通媒体超时，暂时性下载错误至多补试一次。独立listing_ingest.download_video是为单商品长下载设计：无总时限，Range续传，单请求60秒、固定100MiB上限，网络错误可持续重试；无ETag版本一致性校验，不能仅凭续传判定原视频从未变化。

## 配置格式

JSON不能写//注释或尾逗号。pyproject.toml支持#备注，本次已在原文件添加中文说明；uv.lock由依赖工具生成，未手工修改。库中的报告和素材关联JSON是历史数据，不是运行配置，本次不添加字段或改写。
