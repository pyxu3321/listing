> 2026-11-02 更新：已新增整套 Listing 向量、同第一阶段的分类目录、整套检索与组合选择 CLI，以及 MySQL 整体包读回验证。当前行为和新增文件以 [最新实现说明](整体Listing实现.md) 为准；下文保留早期状态与后续规划。

# 数据契约

## 当前 payload（已实现）

顶层包含 batch_id、source_report_sha256、review_sha256、provenance、snapshots、assets、references、features、embeddings。

| 集合 | 关键字段 | 含义 |
| --- | --- | --- |
| snapshots | snapshot_key 及商品来源信息 | 商品在一次采集中的观察 |
| assets | asset_sha256、local_path、width、height | 去重后的图片文件 |
| references | reference_id、snapshot_key、asset_sha256、source_role、source_metadata | 图片在具体商品/模块里的出现 |
| features | feature_id、batch_id、snapshot_key、entity_key、entity_kind、image_reference_id、features、source_text | 图片或文本及商品级分析 |
| embeddings | embedding_id、feature_id、model、model_digest、recipe、dimensions、input_sha256、input_text、vector | 对应特征文字的编码 |

entity_kind 当前包含 image、title、bullet、description、aplus_dom、product。文本和商品级特征不必存在 image_reference_id。107 条特征对应 107 条向量。

图片 features 当前包含 observation_zh、semantic_description_en、composition、palette、scene、themes、visible_claims、identity_scope、limitations、evidence_basis、quality_score、approval_status 等。字段不代表已获得人工批准或真实质量分。

contracts.py 校验来源/审阅/文件哈希、引用存在性、ID 唯一性、向量覆盖、数值和模型摘要；未实现完整 JSON Schema、所有枚举和每条推断的证据语义核验。现有输入没有凭文档自动新增字段。

## 目标契约（待开发）

共同元数据增加 schema_version、created_at、producer_type、model_version（未知可空）、prompt_version、taxonomy_version、analysis_version、review_status 和 supersedes_id。

证据对象包含 source_url、snapshot_id、reference_id 或 text_block_id、原文位置；视频增加 start_ms/end_ms、frame_id。时间使用带时区的 ISO 8601；ASIN 必须与 marketplace、snapshot_id 一起解释。

观察、竞品宣称、推断分别存放。未知值用 null/unknown 与 reason，不用空字符串或零分假装存在。缺失普通详情、未采集视频及无法解码图片分别记录原因。

向量契约增加 vector_kind 和 embedding_space_id，并绑定具体 feature_version。当前辅助函数能补部分字段，但主导出尚未使用它。不同编码空间禁止直接相似度比较。

分组保存 cluster_version、算法、阈值、向量空间、成员版本和代表。评分保存 rubric_version、各项分数、理由、证据、是否可评价、校准状态；总分规则在评分标准批准后确定。原则保存支持与反例、独立商品数、适用范围及限制。

人工审核保存 reviewer、reviewed_at、decision、reason、target_version。修改内容生成新版本，旧审批不能直接沿用。

## 第三阶段契约

当前交接文件为索引，详见 [完整方案第 13 节](第二阶段完整方案.md)。正式契约需校验所有路径/对象 key 可访问、版本一致、向量空间清楚、审核状态可用；不得把排名作为质量分，或把竞品参数作为自有事实。
# 2026-11-02 新增契约：listing-reference-library-v1

本节描述 reference_library.py 的实际输出；下文旧 payload/v2/v3 契约保留。

| 层次 | 关键字段 |
| --- | --- |
| Listing 主记录 | schema、listing_version_id、source_bundle_sha256、identity、overall_features、overall_embedding、components、generation_recipes、coverage、approval_status、quality_score、usage_boundary |
| 组件 | 保留原 part_id/role/features/reference/asset/module_placements，增加 listing_version_id、identity_scope、retrieval_status、usage_boundary |
| 向量 | model、model_digest、recipe、dimensions、vector、index_space_id；整体和组件空间分开 |
| 生成方案 | recipe_id、version、listing_version_id、reference_part_ids、reference_roles、goal、template、variables、product_constraints、acceptance_checks、applicability、status、validation_trials |
| 试验记录 | trial_id、prompt_sha256、reference_sha256、model、output_sha256、check_results、reviewer |

索引文件 library_index.json 包含 whole_index 与 component_index，每条关联 record_path、embedding 和分类元数据。目录为 catalog/国家/网站/品类/商品/快照/Listing版本/reference_listing.json。

整体仅接受 explicit_reviewed_whole_listing_narrative 来源的 v3 向量；组件证据、模板引用必须属于对应版本。check_results 覆盖全部 acceptance_checks，值为 pass/fail/unverified。validated 要求至少三次不同试验、同条件、全通过、validation_scope 和绑定版本的 review_record；记录完整性不等于其真实性已验证。

第三阶段查询使用对应 index_space_id 和编码配方，先选整体，再按 listing_version_id 限制组件。此接口只导出数据，没有执行自动检索或数据库同步。竞品只能作为表达参考；自有产品事实另行输入。

# 组件策略扩展：listing-reference-library-v1.1

新增 --policy，契约及配置示例见 architecture.md 和 config/components.json。组件 controls 保存 enabled、include_in_overall、embed、retrieve、generation_reference 及自动约束原因；类型规则可设置 max_components。listings 按 Listing 版本、part_id 定位单个组件，不对全库同名素材套用。

主记录新增 projection_version_id、component_policy、overall_basis、overall_status。投影版本由完整源记录、解析后的策略和方案产生；不同配置不覆盖旧投影。路径使用源版本哈希前20字符/投影ID前20字符，并在写入时检测投影ID冲突。

embed=false 时不输出活动组件向量，自动关闭 retrieve；原始源文件不变。generation_reference=false 时引用它的方案 availability=blocked_reference_disabled，生命周期 status 保持原值。改变整体参与集合时 overall_status=requires_review_and_reencode，原整体向量仅留审计，不进入 whole_index，组件也暂停索引导出。policy_report 记录源组件数、活动向量数和暂停模板数。

此策略处理已分析结果，不执行真正的视觉分析或重新编码。新范围需要重新审阅/编码为新 v3，再导出。当前尚未执行数据库或 Qdrant 同步；未来同步不得继续使用失效的旧投影。

