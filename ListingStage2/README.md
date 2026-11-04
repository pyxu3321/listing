> 当前主流程：v5结构化整体与独立组件，已写入本地Qdrant两个集合。当前批次50条整体、1277条组件。[总览](outputs/batches/structured-whole-components-20261104/release/index.html) · [存储结构、运行与API说明](docs/整体组件双集合与API.md)。下方旧结果保留为历史记录。

> 新版v6独立试验库已扩至50套。原8套保留，新增42套核对主图颜色与构图，其余图片未复核的颜色角色标为not_assessed，文字综合保留原审阅来源。与默认v5库独立、不混排。[扩容说明](docs/独立试验库扩容50套.md) · [本机试验前端](http://127.0.0.1:8766)。

# Listing 第二阶段

将第一阶段商品快照整理为可追溯的整体特征、组件特征、独立向量与生成方案。按国家 → 网站 → 品类 → 商品 → 快照归档。

## 从哪里开始

- [API 配置与试跑](docs/API接入配置.md)
- [所有配置的中文注释](config/README.md) · [逐字段对照](config/配置逐项注释.jsonc)
- [所有配置的中文注释](config/README.md) · [注释规范](docs/注释规范.md)
- [项目架构](docs/architecture.md)
- [代码文件说明](docs/file-map.md)
- [数据契约](docs/data-contract.md)
- [存储设计](docs/storage-design.md)
- [依赖说明](config/dependencies.md)

## 启动与配置

`run_api_analysis.ps1` 为新 API 入口，默认无联网预检；`-Execute` 才请求模型，`-Encode` 可在分析后使用本地 Ollama 编码。完整命令见 API 文档。

- `config/model-api.example.json`：API 配置模板；密钥使用环境变量。
- `config/components.json`：组件类型开关及数量限制。
- `config/components.override.example.json`：单项覆盖示例，须对应当前任务版本。
- `config/generation-recipes.example.json`：待验证的生成方案。

实际启用的分析提示词位于 `src/listing_stage2/features.py`。

## 当前结果

- API 入口：真实来源预检与模拟响应验证通过，34项测试通过；未使用真实密钥调用。
- 第一名 v3：1个独立整体向量、18个组件向量；视频仅关键帧人工分析。
- 配置导出示例：保留18个来源组件，活动组件向量可减至10个。
- 前五名：91张图片、5个视频及来源文字形成132个组件，118个进入参考检索索引；第三阶段已接入。
- 新特征库导出未执行 MySQL 写入或 Qdrant 同步；向量保存在本地JSON索引中。

[第一名实验](docs/排名第一双层特征实验.md) · [配置后的索引](outputs/reference_library/rank1-configured/library_index.json) · [API预检](outputs/api_analysis/rank1-dry-run/plan.json)

## 保留的历史流程

`run_stage2.ps1`、`pipeline.py` 和 `outputs/batches/d315d7b83444ef3b27cd` 保留五商品 v2 聚合实验，不与独立整体向量 v3 混用。旧流程依赖 D:/ListingAnalysis 和 D:/Crawl4AI。[历史实现说明](docs/整体Listing实现.md)

## 目录

```text
config/    配置及可用示例
src/       实际运行代码
tests/     回归测试
data/      待分析任务、审阅证据与向量缓存
outputs/   分析结果、特征库与生图演示
docs/      架构、接口、规范和运行说明
```

2026-11-02 已清理无调用占位模块、未启用提示词、重复规划、旧批次和可再生成缓存。清单见 cleanup-report.json，移除项目已送 Windows 回收站。生图实验、原始证据及正在使用的结果保留。


## 当前v5入口

`run_structured_stage2.ps1`读取完整来源及绑定版本的结构化审阅，整体只编码提炼后的正向特征和条件，组件独立保留。`structured_model_review.py`提供后续LLM综合接口，默认仅预检。全文汇聚v4已退出默认路径。
