# 第三阶段输入与配置

## request.example.json

| 字段 | 含义 |
| --- | --- |
| country_code/category_id | 必须匹配的国家和内部品类 |
| site_ids | 可选站点列表；空列表允许同国家/品类跨站点，来源仍保留 |
| product_description | 自有产品描述，用于生成整体查询向量 |
| product_form | 可选结构硬筛选；null不限制，须与第二阶段标签一致 |
| selling_points | 用户希望表达的卖点，不自动视为已核验事实 |
| style | 单独用于整体视觉风格评分，也用于组件查询 |
| retrieval_terms | 可选补充检索词，可写双语；不自动写入商品文案 |
| product_facts | 用户自行提供的可核验事实，当前只随参考包传递，未自动核验 |
| own_images | 自有图片路径，当前只随参考包传递，不调用图片模型 |
| reference_needs | 每项有role和purpose，说明想找什么组件、用于什么表达 |
| reference_needs[].entity_kind | 可选image/text/video；A+配图指定image，避免返回FAQ文字 |
| reference_needs[].preferred_themes | 可选英文用途标签列表，与组件themes忽略大小写精确匹配；示例hand press、softness |

角色使用main_image、gallery、aplus、bullet、title、description、video。组件仅从入选整体中选择，不能凭某一张附图得分高跳过整体筛选。

## runtime.json

| 字段 | 含义 |
| --- | --- |
| library_indexes | 第二阶段导出的library_index.json列表。重复Listing按先出现的投影处理，不合并恢复旧开关 |
| encoder.stage2_project | 第二阶段源码目录，用于复用LocalEncoder |
| encoder.ollama_url/model | 本地向量服务及已安装模型，摘要必须与特征库一致 |
| encoder.cache_directory | 查询编码缓存 |
| retrieval.whole_top_k | 最多选几个整体，不足时按实际返回 |
| retrieval.components_per_need | 每项用途最多返回几个组件 |
| retrieval.minimum_similarity | 整体产品卖点余弦分及组件余弦分下限，范围-1到1，不是合格率 |
| retrieval.include_pending | 是否允许待审核数据进入预览，示例true便于实验；正式已审核库可设false |

JSON不支持注释，实际字段保持严格JSON。没有密钥配置，当前只使用本地Ollama。

2026-11-03：默认库改为前五名实验，whole_top_k=3。结构硬筛选示例见request.pillow_top.example.json与request.memory_foam.example.json。

配置preferred_themes时，组件用途排序分为0.85×向量相似度+0.15×标签命中比例；未配置则只按相似度排序。相似度阈值始终先执行。结果保留similarity、relevance_score、theme_matches和ranking_method，标签不会替换原始输入或产品事实。结构未知时使用null，不应猜测自有产品是填充垫还是海绵垫。

## 整体双路评分更新

`retrieval.whole_score_weights`默认`{"product":0.65,"style":0.35}`，自动归一化；`style_evidence_top_n`默认3，取最接近的合格图片描述的风格分均值。没有风格或合格图片时只用产品卖点分。结果展示两路分数、实际权重与证据原图。整体`similarity`现在为综合分，详见[整体双路评分](../docs/整体双路评分.md)。

## 相近候选与组件延后

`retrieval.rank_tiebreak_tolerance`默认0.02；先按综合分选前`whole_top_k`套，再在分数接近组内按历史采集排名升序。`retrieval.match_components`默认false，组件用途匹配延至生成规划。`reference_needs`可省略；显式启用组件匹配时再填写用途。详见[规则、示例与边界](../docs/相近候选排序与组件延后.md)。

## 当前默认库更新

`config/runtime.json`现指向完整证据v4的50套素材；历史实验目录的配置保留旧版以便复现。相近排名规则和组件延后不变。v3与v4不得在同一次整体排序中混用。

## 当前v5配置

默认清单指向`structured-whole-components-20261104/release/library/library_index.json`，实际读取本地Qdrant双集合。国家、品类、产品描述可省略，至少提供非空卖点、产品描述或补充检索词之一；不自动推测。`request.selling-points-only.example.json`是仅卖点示例。使用`run_match.ps1`自动选择第二阶段独立环境。

整体配方为`reviewed-structured-whole-v5`，不能与旧整体配方混在同一次排序中。查询的模型摘要必须一致。中文编码模型本轮未更换。
