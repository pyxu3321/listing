# 细粒度提取 v6

> 更新：独立试验库已扩大到50套，8766已切换到新发布；新增42套的审阅程度与位置见[扩容说明](独立试验库扩容50套.md)。下方8套数据为最初试验记录。

保留“先选整体、后选组件”的流程。整体仍为一条独立向量，图片、视频、标题、五点等组件分别保存并关联父版本。此次修改提取内容与证据结构，未接入用户查询改写LLM。

## 最初8套试验范围

- 通用提取、校验、任务生成、独立编码和Qdrant发布流程已实现。
- 已对历史采集1、3、6、22、25、28、36、44号做新版试验：8套、110张当前/家族产品图片、292条原子属性、195条组件。
- 图片复核采用当前对话中的逐图拼图观察，适合明显颜色与构图；未做全部细小文字的高分辨率OCR。
- 原始标题、五点及详情用于精确引句。视频本轮未重新逐帧和转录，视频组件保留旧版本，不冒充完成了新视频分析。
- 另42套已生成待审任务，没有自动继承旧配色作为新观察。
- 原50套v5库和8765前端没有被覆盖；v6试验前端为 http://127.0.0.1:8766 ，仅8套。向量相似度仍可能排序不当，不能声称补细属性后颜色和否定条件已自动解决。

## 原子属性

配置由 `config/feature-schema.json` 管理，可增减字段；变更会使旧审阅的配置指纹失效，需重新核对。

目前覆盖卖点、材质、结构、厚度、软硬、护理、认证来源声明、售后来源声明、客群、场景、六类颜色、构图、表达手法和风格。

每条属性包括字段、对象、英文标准值、中文标签、准确含义、适用范围、条件、状态和具体证据。状态分为positive、negative、conflicting、unknown，不能把“不允许卷起长期存放”转成“便于折叠收纳”。

负面、冲突和未知完整保存在结构化属性中，不作为正向卖点编码。正向条件随属性保存并进入正向提炼文本，但单个向量不会自动执行条件判断，仍需未来的语义复核层。

认证、功效、售后等来源内容只记录为来源声明，不能变成自有产品事实。

## 逐图提取

每张符合策略的当前/家族产品原图单独保存：

| 角色 | 含义 |
| --- | --- |
| product_surface | 画面中产品表面颜色 |
| product_core | 明确露出的内部材料颜色 |
| scene_background | 房间、床、窗帘等物理场景背景色 |
| layout_background | 设计版面的色块、底板颜色 |
| text | 文字颜色 |
| icons | 图标颜色 |

每个角色标明observed、not_visible或not_assessed，未看清不等于不存在。另存该张图的构图、场景、表达手法、组件编号和原图SHA256。第44号绿色截面示意图属于图形编码，不能当成绿色乳胶产品。

文本证据要求精确引句存在于所引用原文中；视觉证据要求引用已复核图片、文件摘要及区域角色。产品颜色不能引用仅有标题的文字证据，蓝色文字不能绑定为产品颜色。程序验证归属与格式，不保证引文语义完全支持结论，仍需人工/LLM复核。

## 任务生成与发布

```powershell
cd D:\ListingStage2
./run_detailed_stage2.ps1 -Source D:\ListingStage2\outputs\batches\all50-full-evidence-20261103 -Output D:\ListingStage2\outputs\batches\new-review-tasks -Prepare
```

该命令不调用模型。当前50套任务在 `outputs/batches/detailed-features-20261104/tasks`。

填写/生成审阅JSON后，使用 `-Reviews <审阅目录> -StorePath <新数据库目录>` 发布到新Output目录。默认缺任何一套审阅就拒绝发布；明确做样本实验时才加 `-AllowPartial`。不会用空字段或旧整套描述假装审阅完成。

已生成试验发布在 `outputs/batches/detailed-features-20261104/release-v6`；清单为 `library/library_index.json`。数据库为 `data/vector_store/detailed_20261104`，集合为listing_wholes_v6和listing_components_v6，查询必须按manifest的数据集标识过滤。

新审阅过的110张图片各自重编码；整体对提炼后的原子属性单独编码一次。没有平均组件向量。未重审文字/视频等组件的原独立向量保留，不声称所有组件都重新分析过。v5/v6整体配方不可混在一次排序中。

## 未来图片/全文模型API

复制 `config/detailed-model-api.example.json` 为本地配置，填写供应商地址和实际支持图片输入的模型ID，按供应商接口填写token参数。密钥放LISTING_MODEL_API_KEY环境变量；启用前先执行：

```powershell
$env:PYTHONPATH='D:\ListingStage2\src'
& D:\ListingStage2\.venv\Scripts\python.exe -B -m listing_stage2.detailed_model_review --bundle <listing_features.json> --config <本地配置.json> --plan
```

预检输出待发原图数、完整文字数、计划调用数，不发模型请求。每套预计逐图调用N次，再用全部文字与逐图结果综合1次。当前只读原图，不从旧描述补造颜色。--execute才执行，必须同时启用配置及提供新输出文件；失败无自动重试，已发请求可能已计费。当前试验没有付费API调用。

## 未来用户输入LLM

此层与提取模型不同，本轮仅生成接口契约和约束，不接入实际请求路径。

每次发布同时生成：

- `feature-vocabulary.json`：字段定义、实际正向标准值、对象、条件、版本关联，以及负面/冲突/未知约束。
- `query-contract.json`：由同一份字段配置生成的JSON Schema。
- `query-system-prompt.txt`：保留原话、英文归一、近义表达、否定/数值/对象保留、不强行套词等约束。

建议流程：用户原话 → LLM参考词表进行英文归一与意图拆解 → 保留known/out_of_catalog/ambiguous状态 → 后续整体召回。候选是否真正满足要求另做证据复核，不能把输入改写当成最终审查。

例如输入blue，应保留产品表面色、背景色、文字色等歧义，不暗中决定是哪一种；输入“不要紫色”，不能丢掉否定；输入“App自动调温”，不能为了命中词表改写成普通清凉透气。国家、品类等未填写时不自动补充。

词表是“库里观察到什么”，不是唯一允许输入的世界。库里没有的概念应保留并标记，不能映射为看似接近却不同的卖点。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| config/feature-schema.json | 统一字段、对象和颜色角色配置 |
| src/listing_stage2/detailed_extraction.py | 审阅验证、逐图描述、独立编码、整体属性与词表 |
| src/listing_stage2/detailed_batch.py | 50套任务、完整性检查和独立发布 |
| src/listing_stage2/detailed_model_review.py | 未来逐图＋完整文字API入口，默认预检 |
| src/listing_stage2/query_contract.py | 未来输入LLM的提示约束与动态输出Schema |
| run_detailed_stage2.ps1 | 新版任务/发布启动脚本 |
| tests/test_detailed_extraction.py | 颜色角色串用、错引文、过期审阅、独立编码等回归 |

## 验证界限

格式与证据类型验证不等于视觉/文本语义百分之百正确。当前八套是人工观察试验，后续需要高分辨率逐图复核、细字OCR与视频关键帧/字幕分析，才能扩大到全库并稳定使用。
