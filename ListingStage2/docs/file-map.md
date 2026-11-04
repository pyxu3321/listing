# 清理后的代码文件职责

更新：2026-11-02。路径相对 src/listing_stage2/。

| 文件 | 功能 |
| --- | --- |
| api_analysis.py | 第一阶段报告→预检→组件API分析→整体综合 |
| model_gateway.py | Chat Completions图文JSON、环境变量密钥、响应与错误处理 |
| features.py | 组装来源任务、实际分析提示词、组件与整体返回校验 |
| component_policy.py | 类型与单项规则、数量上限、依赖处理 |
| encode_analysis.py | 已分析结果单独编码，避免重复付费分析 |
| whole_listing.py | 独立整体向量、组件向量、审阅指纹与视频证据挂接 |
| local_encoder.py | 本地Ollama、归一化、模型摘要和内容缓存 |
| reference_library.py | 特征库契约、版本化导出、双索引、模板引用与失效校验 |
| prepare_report.py | 第一阶段报告转待分析任务 |
| phase1_reader.py | 旧冻结数据读取 |
| contracts.py | 旧payload、引用、媒体哈希和向量校验 |
| listing_bundles.py | 素材装配，历史v2聚合与整套浏览 |
| storage.py | JSON安全替换及MySQL读回比较 |
| settings.py | 路径设置 |
| clustering.py | 已有描述向量聚类 |
| scoring.py | 保持未校准分数和候选原则 |
| export.py | 原有分析报告和HTML导出 |
| pipeline.py | 历史五商品v2主流程及可选MySQL实验 |
| rank1_experiment.py | 第一名v3与视频关键帧人工审阅实验 |
| prepare_five_experiment.py | 冻结前五名素材、核对HLS补充视频归属与哈希、生成图片联系图和8帧视频采样任务；不自动识别图片 |
| reviewed_experiment.py | 读取本次GPT逐项审阅，校验输入和卖点证据，生成五套独立整体/组件向量、参考索引及离线页面 |
| batch_review.py | 50套冻结任务、联系图、按输入签名复用审阅、显式审阅校验、整体/组件独立编码和分页输出；不自动猜图 |
| match_preview.py | 历史v2匹配与组合预览 |
| __main__.py / __init__.py | Python包入口和标识 |

配置见 config/；测试见 tests/。实际启动为根目录 run_api_analysis.ps1 与 run_stage2.ps1。

无调用的空适配器、media/review占位、未启用的prompts目录和embeddings辅助草案已移入回收站。缺失业务功能仍记录在architecture.md，不以空文件冒充实现。

2026-11-03：已恢复详细中文注释，按[详细注释约定](注释规范.md)维护。配置使用见[配置入口](../config/README.md)，原JSON不变。

2026-11-03 注释补充：运行代码、测试与保留的演示Python脚本均有文件/函数中文说明，启动脚本使用PowerShell参数帮助。配置注释见 [配置核对入口](../config/README.md)。原JSON不变，注释对照不能直接传入程序。

## 完整原文整体编码更新

`whole_document.py`负责完整原文/视觉描述收集、带证据去重、无丢失分块及整体文档编码；`full_evidence_batch.py`从已完成批次重建新整体版本，保留所有组件向量。[详见说明](完整原文整体编码.md)。

## 当前v5整体/组件双集合

- `structured_whole.py`：绑定完整来源审阅，校验归纳特征及条件，整体单次独立编码。
- `collection_store.py`：两个Qdrant集合、外键、版本发布隔离、持久化和真实向量查询。
- `structured_batch.py`：批次编码、入库回读及关联预览。
- `structured_model_review.py`：后续LLM综合提取接口，默认只预检。
- `run_structured_stage2.ps1`：当前第二阶段入口。

[完整说明](整体组件双集合与API.md)。
