> 2026-11-02 更新：已新增整套 Listing 向量、同第一阶段的分类目录、整套检索与组合选择 CLI，以及 MySQL 整体包读回验证。当前行为和新增文件以 [最新实现说明](整体Listing实现.md) 为准；下文保留早期状态与后续规划。

# 存储设计

## 已实现的试验存储

原始素材保留在 D:/Crawl4AI，第二阶段不重写。D:/ListingAnalysis 提供历史审阅、冻结 payload、文本编码和 MySQL 工具；D:/ListingStage2 保存当前衍生结果。

当前 MySQL：127.0.0.1:3307，listing_analysis_pilot。连接凭据在旧项目本地配置中，不纳入文档。

| 表 | 当前作用 |
| --- | --- |
| analysis_batches | 来源报告、审阅和批次出处 |
| product_snapshots | 商品及快照 |
| image_assets | 去重图片资产 |
| image_references | 商品/快照到图片的具体引用 |
| feature_records | 图文和商品分析特征 |
| embeddings | 模型/配方/输入及 JSON 向量 |
| stage2_exports | run_id 主键、result_json，保存聚类/空评分/候选原则 |

前六表复用旧工具写入并读回验证；stage2_exports 在另一个事务写入，尚未独立读回验证。当前无 MySQL ANN 向量索引，不能称为已经部署向量检索数据库。

## 正式版建议（未建表）

| 逻辑实体 | 建议关键关系/索引 |
| --- | --- |
| analysis_jobs / job_items | 任务状态、输入版本、重试、错误；按状态和更新时间索引 |
| media_assets / media_references | sha256 唯一资产；快照+模块+序号定位出现位置 |
| text_blocks / video_segments | 原文/视频时间片段到快照和媒体引用 |
| feature_versions | 实体、版本、标签版本、证据、生产方式；历史不可覆盖 |
| embedding_records | 特征版本+编码空间+输入哈希唯一，避免错误缓存命中 |
| cluster_runs / cluster_members | 算法版本、成员特征版本、相似度 |
| quality_reviews | 评分标准版本、各维度、理由、审核状态 |
| principles / principle_evidence | 原则、支持/反例、多商品覆盖及适用范围 |
| review_events / export_versions | 修订、批准、审核人、目标版本和交接版本 |

这些是目标逻辑实体，不要求立即建立完全同名的新表。实现时通过迁移脚本演进试验表，先验证数据回迁和恢复，再切换应用读写。

对象存储保存原图/视频及分析副本，MySQL 保存 key、类型、大小、校验值，不保存短期签名 URL 为永久地址。规划 key 可为 assets/sha256/前两位/哈希.ext；分析副本另存并记录父资产和变换。

Qdrant 为可选索引副本：point 绑定特征版本与向量空间，payload 携带市场/品类/角色/审核状态。新增或撤销审批时更新索引；MySQL 保留业务事实，以便重建。

## 版本、备份和失败恢复

当前相同批次和阈值覆盖同一导出目录，不能替代完整历史版本系统。正式版应固定输入与代码/配置版本，审核锁定不可变导出；数据库采用事务记录状态，媒体和索引用幂等任务补偿，不承诺跨三套系统原子提交。

备份必须同时覆盖数据库、素材/对象和版本清单，并定期做恢复验证。当前尚无自动备份或清理任务。不得只备份 HTML，否则原图路径失效后无法复核。
# 2026-11-02 架构增补：整体、组件与生成方案

当前新增导出在 outputs/reference_library/rank1，尚未执行数据库迁移。存储职责如下：

| 主数据对象（目标表名，未建表） | 主键/关联 | 内容 |
| --- | --- | --- |
| reference_listings | listing_version_id | 国家/站点/品类/商品/快照、整体特征及向量、覆盖度、审核状态 |
| reference_components | listing_version_id + part_id | 角色、特征、组件向量、原图原文证据、模块位置 |
| generation_recipes | recipe_id + version | 模板、变量、约束、范围、状态、所属 Listing 版本 |
| recipe_references | recipe_id + version + part_id | 参考组件及 expression_reference 职责 |
| recipe_trials | trial_id | 实际输入/输出/模型/逐项检查/审阅记录 |
| reference_reviews | review_id | 审阅目标类型、版本、人员、时间、结论 |

MySQL 作为主数据源，媒体继续引用第一阶段对象存储/文件及哈希；Qdrant 仅作为可重建的整体/组件检索投影。数据库先提交主记录，再异步更新索引；同步需有幂等任务、版本标识、失败重试和删除标记。这些同步机制仍待实现，不能假设数据库与 Qdrant 已具备跨系统事务。

模板和试验记录先存结构化数据，适用卖点/场景可参与检索；没有必要把完整提示词直接当作产品特征向量。旧实验 JSON 表继续保留；迁移前应确认字段、外键和实际检索量。

以下保留早期存储说明；当前目录及接口以上述新增契约和 architecture.md 为准。

