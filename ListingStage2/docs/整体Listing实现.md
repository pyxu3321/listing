# 第二阶段：整套 Listing 特征包实现说明

更新：2026-11-02。本说明取代旧文档中“仅单图分组、无整体向量”的描述。当前实现是前五个已审阅商品的可运行版本，其他商品仍需人工分析输入。

## 业务行为

沿用第一阶段的国家 → 网站 → 内部品类 → 商品 → 快照。每套 Listing 对应一个整体向量，供第三阶段先选整套参考；标题、逐条五点、主图、附图、详情、A+ 仍分别保留，允许从不同候选中组合选择。网站作为来源及可选筛选字段，不把不同网站的商品合并成一个商品。

当前五套共含 65 图片、107 条特征，生成 5 个 768 维整体文字向量。图片理解复用历史 GPT 审阅，没有执行新视觉 API；前期来源均为美国亚马逊。独立站目录和组合选择结构已预留，但独立站采集/理解适配器未接入。无视频输入，视频状态明确跳过。

## 整体向量配方

配方 `listing-role-balanced-chunks-v1`：

1. 图片和商品采用已审阅的英文语义描述；标题、五点、普通详情、A+ 使用已有对应原文。
2. 按角色组织文字，每段超过 1800 字符则切块，无静默截断。请求本地 Ollama 时 truncate=false。
3. 同一单项的块向量平均并归一化，再在同角色内汇总，最后按角色权重合成为一个单位向量。
4. 默认商品汇总、主图、附图、五点权重为 2，其余为 1。权重只是初始实验配方，尚未人工校准。角色内归一化避免图片数量和文案长度直接支配结果。

这是基于完整分析文字的聚合向量，不是把所有单项简单等权平均，也不是图片像素向量或新的大模型整体理解。主图/附图在旧 payload 的 main/secondary 与第一阶段 gallery 之间做显式映射，并用第一阶段 is_main_image 证据确认主图。

相关商品、品牌图标等归属不属于 current_or_family 的图片保留在 parts，但不直接纳入整体向量。current_or_family 可能仍含系列表达，使用前需运营复核；这里不能验证变体所有权、功效和认证真实性。

排名不参与聚合；匹配相似度不是质量评分。每套保存配方、角色权重、模型 digest、输入哈希、参与项和块数。新模型空间不能与旧向量直接比较。当前 bundle_id 与 run_id 固定到输入及配方；修改实现语义时应升级配方版本。

## 已实现代码

| 文件 | 功能 |
| --- | --- |
| listing_bundles.py | 整体组包、角色汇总、向量合成、目录/HTML导出、整套匹配、局部选择 |
| local_encoder.py | 本地 Ollama 编码、模型摘要、磁盘缓存、维度和数值校验 |
| prepare_report.py | 第一阶段报告生成按国家/网站/品类组织的待分析任务 |
| match_preview.py | 整套匹配及跨候选选取的 CLI 预览 |
| pipeline.py | 在原有试验上增加整体向量、交接文件及 MySQL 写入 |
| storage.py | 原子 JSON 写入和数据库浮点读回容差比较 |
| tests/test_listing_bundles.py | 整体数量、主图/五点归属、排名隔离、输入变更、过滤/空间及跨候选选择 |

原有单项图片聚类仍作为辅助分析输出，不承担第三阶段整体排序。model_gateway、media、review 等旧占位模块不代表已经实现 API 图片理解、视频分析或审核界面。

## 运行

```powershell
& D:\ListingStage2\run_stage2.ps1
# 保存并读回验证整体特征包（需先启动现有试验 MySQL）
& D:\ListingAnalysis\start_mysql.ps1
& D:\ListingStage2\run_stage2.ps1 -MySQL
```

默认仍读取冻结前五商品 payload；可通过 `-Payload 文件路径` 指定符合当前契约且已有逐项特征和向量的 payload。该选项不会自动为新图片调用 GPT，也不会自动兼容任意 JSON。RefreshVectors 仍是旧试验单项向量的刷新入口，不能与 Payload 同用。

生成新批次分析任务：

```powershell
$env:PYTHONPATH='D:\ListingStage2\src'
& D:\python\python.exe -m listing_stage2.prepare_report 'D:\Crawl4AI\library\runs\20261029T004510Z_fdcb2277_content_a81a90\report.json'
```

目前已生成 50 个 pending_analysis 任务，位于 data/analysis_tasks；任务带原图文、来源报告哈希、快照及媒体记录，不宣称完成图片理解。人工审阅结果还需整理成既有特征 payload，尚无任意任务 JSON 到完整已审阅 payload 的自动转换器。

## 输出目录与第三阶段交接

```text
outputs/batches/<run_id>/
├─ listing_index.json
├─ listings.html
├─ catalog/US/amazon/toppers/<商品>/<快照>/listing_features.json
├─ stage3_bundle.json
├─ payload.json / clusters.json / quality.json / principles.json
└─ run.json
```

每个 listing_features.json 包含 identity、全部 parts、原始图文和媒体清单、aggregate_documents、整体 embedding、覆盖信息、审核和质量状态。原图只通过本地路径引用，不重复下载或复制。HTML 为整套卡片浏览，不是交互审核页面；分享给同事仍需要媒体打包或网络存储。

stage3_bundle.json 明确 retrieval_unit=whole_listing，并通过 listing_index.json 找到整套特征包。latest.json 的 viewer 指向 listings.html，parts_viewer 指向旧逐图浏览页。

## 匹配与组合示例

```powershell
$env:PYTHONPATH='D:\ListingStage2\src'
& D:\python\python.exe -m listing_stage2.match_preview --query 'soft comfortable topper, hand press softness' --country US --category toppers --include-pending
& D:\python\python.exe -m listing_stage2.match_preview --selections D:\ListingStage2\config\selection-example.json --output D:\ListingStage2\outputs\reference-pack-example.json
```

检索默认排除未批准素材；当前五套均待审核，因此试验需显式 include-pending。命中结果包含整套 parts，不只返回单图；跨网站在结构上允许，但当前样本全为亚马逊。输出仅是语义排序预览，未实现自有产品事实硬筛选、匹配分校准及推荐理由生成，不能视为完整第三阶段。

组合选择输入为 bundle_id、part_id、planned_use，可选不同商品的主图、五点和附图。输出保留完整来源及快照，状态始终 draft_pending_review；选择不会自动批准。亚马逊主图规则及最终商品真实性仍由后续生成/质检检查。

## MySQL 与验证

新增 stage2_listing_bundles，联合主键为 run_id + bundle_id，bundle_json 保存整套特征和整体向量。写入后读回所有字段，对 JSON 浮点采用 1e-12 容差，其他字段严格比对。旧六表及 stage2_exports 继续兼容；索引仍为 JSON 向量，不是 ANN 数据库。

已实际运行整体编码、卖点检索、跨候选选择、MySQL 保存及读回。固定样本原图/报告哈希校验通过。本地模型调用无付费 API 费用，仍有本机计算成本。质量分继续 null。文件与数据库仍无跨系统原子事务，正式部署的审核、增量版本与失败恢复需后续完善。
