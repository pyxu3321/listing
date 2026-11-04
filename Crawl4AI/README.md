> 2026-11-03全量媒体更新：数量null为全部，视频无总时限，后台已启动补采。[配置/进度/恢复说明](docs/全量媒体补采.md)。原始报告保持不变。

# Amazon Listing 第一阶段：采集与素材库

> 2026-11-03：运行代码、测试、启动脚本和依赖配置已补中文注释。[配置核对入口](config/README.md) · [逐字段中文对照](config/配置逐项注释.jsonc) · [注释验证记录](docs/注释核对记录.json)。原始JSON和采集证据保持不变，63项测试通过。

> 2026-11-03：已恢复详细中文注释。[配置核对入口](config/README.md) · [注释规范](docs/注释规范.md) · [注释验证记录](docs/注释核对记录.json)。原始JSON和采集证据保持不变，63项测试通过。

按原流程第①步实现：采集可验证 BSR，依排名读取商品，保存图文、媒体、来源与快照，按 ASIN 导出。

- [项目框架与模块职责](docs/phase1-framework.md)
- [当前 50 个商品的完整素材索引](library/products/批次索引/20261029T004510Z_fdcb2277_content_a81a90.html)
- [完整补采报告](library/runs/20261029T004510Z_fdcb2277_content_a81a90/index.html)
- [本轮验证记录](library/checks/details-repair-20261029.json)
- [清理清单](library/checks/cleanup-20261029.json)

## 启动

本机实际使用 `D:\python\python.exe`，已验证 Crawl4AI 0.9.5、Playwright 1.58.0。启动脚本自动查找可用解释器，也可通过 `-Python` 指定。

```powershell
Set-Location -LiteralPath 'D:\Crawl4AI'
.\run_topper.ps1 -CheckEnvironment
.\run_topper.ps1
```

默认读取美国站 Mattress Toppers 榜单的 Rank 1–50，按排名逐个采集。小范围测试可用 `.\run_topper.ps1 -MaxProducts 1`。

依赖在 `pyproject.toml` 中；`uv.lock` 为独立环境的解析结果，与当前实测全局环境可能不同。未完成安装的旧 `.venv` 已清理，后续需要独立环境时再创建和验证。

## 配置

编辑 `config/topper-us.json`：

| 配置 | 当前值 | 含义 |
|---|---|---|
| `max_products` / `rank_end` | 50 / 50 | 商品数量及榜单范围 |
| `max_images_per_product` | 4 | 图库采样数量 |
| `max_description_images_per_product` | 20 | 普通详情独立图片限额 |
| `max_aplus_images_per_product` | 40 | A+ 独立图片限额 |
| `media_concurrency` | 3 | 同一商品内的下载并发 |
| `request_delay_seconds` | 3 | 商品间请求间隔 |
| `ocr_enabled` | true | 详情图片本地识别 |
| `max_videos_per_product` | 0 | 当前不下载视频 |

主图根据页面所选商品的主展示图标记。搜索排序不作 BSR。页面空容器、图片失败、超限和识别失败分别记录；整体 `partial` 不等于图片下载失败。

## 查看素材

当前商品包位于 `library/products/US/<ASIN>/20261029T004510Z_fdcb2277_content_a81a90/`。

- `标题与五点.txt`、`商品信息.json`、`来源与排名.json`：文本和证据。
- `图片/`：主图与附图，文件名明确标注。
- `普通详情/`、`A+详情/`：原文、OCR 文本、模块及图片。
- `详情预览.html`：按模块看图文。
- `证据/`：原始页面、截图和 Markdown。

原始文件集中保存在 `library/objects/`，报告和历史快照关系保存在 `library/runs/`。旧的重复导出已清理，原始采集报告及最终验证所需的证据保留，可重新导出。

## 补采与重新导出

用现有快照补采详情和 A+，不重新读取榜单：

```powershell
& 'D:\python\python.exe' -m listing_ingest.enrich_details 'library/runs/20261029T004510Z_fdcb2277/report.json'
```

从保留报告重建商品导出副本：

```powershell
& 'D:\python\python.exe' -m listing_ingest.export_products 'library/runs/20261029T004510Z_fdcb2277_content_a81a90/report.json'
```

`review_snapshots.py` 是历史视频归属复核工具，正常采集和详情补采不依赖它。

## 验证与当前限制

```powershell
& 'D:\python\python.exe' -B -c "import sys; sys.path.insert(0, '.test-deps'); import pytest; raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider']))"
```

63 项正式测试通过。本机 `.test-deps/` 提供测试工具，已保留。

当前正式数据包含 50 个商品、200 张图库图片和 457 张 A+ 图片，下载失败为 0。普通详情有 42 个、A+ 有 2 个未从页面取得，保留缺失标记。OCR 337 张取得文字、120 张无识别结果；无结果不代表没有文字。本机识别语言可能回退，结果需核对原图，不能代替产品事实。

已实现命令行采集与本地归档。定时调度、数据库、云存储和运营后台尚未接入；本项目目前只对应原流程第①步。

## 多来源与素材关联（2026-11-02）

已增加多来源清单、只读执行计划和按商品快照输出的 素材关联.json。配置、命令与支持范围见 [多来源与素材关联](docs/多来源与素材关联.md)。

新商品导出目录已改为 `library/products/<country_code>/<site_id>/<category_id>/<product_id>/<run_id>/`。配置示例为 US/amazon/toppers；已重新导出原50商品，旧目录保留。独立站通用商品编号已预留，网络采集适配器尚未实现。
