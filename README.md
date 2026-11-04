# Listing Studio

保留原七阶段规划，本仓库包含已实现的前三阶段源码与本地参考匹配前端。

| 目录 | 功能 |
| --- | --- |
| `Crawl4AI/` | 第一阶段：采集、快照、产品归属和媒体下载 |
| `ListingStage2/` | 第二阶段：特征审阅、整体/组件独立编码、Qdrant 双集合 |
| `ListingStage3/` | 第三阶段：整体匹配、参考包与本机测试前端 |
| `tools/` | 从原工作目录同步源码副本 |
| `docs/` | GitHub 上传与本地运行说明 |

当前前端调用真实第三阶段算法，支持卖点输入、可选筛选、候选数量、严格相似度排序、图片/视频预览、原始文字与证据跳转、结果 JSON 导出。LLM 条件复核和重排尚未实现。

新增v6细粒度提取试验：逐图区分六类配色，按对象保存属性、条件和精确证据；8套试验数据独立发布，原50套库保留。试验入口 http://127.0.0.1:8766 。详见 [新版提取与未来输入LLM契约](ListingStage2/docs/细粒度特征提取与输入LLM契约.md)。词表与输出Schema已生成，用户输入LLM尚未接入；试验数据不随源码上传。

## 当前开发机启动

```powershell
cd D:\ListingStage3
./run_web.ps1
```

打开 http://127.0.0.1:8765 。不要双击 HTML 文件。浏览不需要 Ollama，匹配时需要本地 Ollama 与已有库的模型保持一致。

## 仓库副本与原工作目录

当前实际运行目录仍为 D:/Crawl4AI、D:/ListingStage2、D:/ListingStage3。
D:/ListingStudio 是集中上传源码的仓库副本，不会搬走或删除原始素材。现有部分脚本和配置保留本机绝对路径，不是开箱即用的可移植发行包。

修改原工作目录后，先运行同步脚本，再检查 diff、commit 和 push。同步是单向覆盖，不自动双向合并，也不会删除旧文件。若以后改在仓库副本开发，应先调整本机配置，避免两处同时修改。

## 另一台电脑运行

本仓库不包含已下载的图片/视频、采集快照、50套人工审阅数据、向量库、查询缓存、数据库或环境密钥。因此 clone 源码不等于复制当前演示数据。

1. 安装 Python 3.12/3.13；第一阶段依赖见 Crawl4AI/pyproject.toml，还需完成 Crawl4AI 的浏览器安装。
2. 准备本机第二阶段 Python 环境，安装依赖，见各阶段 README 及 ListingStage2/config/dependencies.md。
3. 单独准备或导入采集数据、审阅记录及特征库。当前固定50套的手工审阅结果在原开发机 outputs 下，未发布到 GitHub。
4. 复制 ListingStage3/config/runtime.structured.example.json 为 runtime.local.json，将 library_indexes、encoder.stage2_project、cache_directory、Ollama地址改为本机位置；库内媒体与存储路径也需要迁移，不能只改前端配置。
5. 使用 `ListingStage3/run_web.ps1 -Config <本机配置路径>` 启动。需要相邻 ListingStage2/.venv 或可用的 python 命令。

当前向量模型为 nomic-embed-text，768维。部分中文输入不能可靠区分；先使用英文卖点测试。相似度不是产品要求满足率，变体、否定、认证和清洗对象需要人工核对。

## GitHub

仓库：https://github.com/pyxu3321/listing

具体命令见 [上传与更新说明](docs/GitHub上传与更新.md)。源码与文档纳入版本管理，媒体和运行数据通过独立存储管理。
