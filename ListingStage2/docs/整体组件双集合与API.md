# 整体特征与组件特征双集合（v5）

当前版本沿用七阶段流程。第二阶段把完整素材综合提炼为一套结构化整体特征，再单独编码；每个原组件保留自身特征、向量和来源。第三阶段先选整体，生成规划时再按父版本选择组件。

## 实际存储

本轮已经写入真实的本地持久化Qdrant，使用两个集合：

| 集合 | 当前批次数量 | 一条记录代表什么 |
| --- | ---: | --- |
| `listing_wholes_v5` | 50 | 一套Listing的一个提炼特征版本、一个独立整体向量 |
| `listing_components_v5` | 1277 | 一张图、一条五点、一个标题、一个详情/A+文字组件或一个视频及其独立向量 |

当前可进入组件参考检索的记录为1126，其他151条按原开关保留，不删除来源。组件数量由实际采集与配置决定，不固定为18或其他数量。本轮没有把已有A+全文重新切成模块，也没有新增视频片段；现有粒度及module_placements保持原样，后续可以增加模块/片段级组件。

Qdrant客户端采用官方支持的本地持久化模式，不需要启动Docker服务：[官方本地模式说明](https://github.com/qdrant/qdrant-client#local-mode)。当前适合单机开发；多人并发使用时应切换服务端，并增加相应连接适配。

数据库目录：`D:/ListingStage2/data/vector_store/structured_20261104`。

一个库可保留不同数据集/历史版本，所以物理总记录可能大于当前批次数量。所有读取与查询必须按清单中的dataset_id限定当前发布。不能裸查整个集合后把历史记录误当当前数据。

## 整体如何生成

当前批次由GPT在对话内读取完整标题、全部五点、普通详情与A+文字，复用之前逐组件的GPT视觉审阅，归纳整体的：

- selling_points：卖点及限定条件。
- product_traits：产品形态、结构和材质来源声明。
- visual_elements：构图与表达元素。
- style：颜色、光线和整体风格。
- summary_en：供人和后续LLM阅读的整体概述。
- expression_sequence、limitations：表达顺序、排除项、冲突及未知信息。

每项正向特征都有英文检索含义、中文显示标签、证据组件ID、依据类型、对象范围及条件。不用程序按词判断“冬暖夏凉”等业务语义。数字、参数、功效与认证始终是来源声明，不转换成自有产品事实。

整体向量只编码归纳后的卖点、产品特征、视觉元素、风格及条件，单次调用向量模型生成一个向量。背景概述、排除项、原文、客服话术、冗长信息顺序不拼入这个向量；它们继续存为元数据/来源。这样避免“解释它不轻便”反而由于出现lightweight而给正向召回加分。

不拼接所有原文，不平均组件向量，也不平均原文分块向量。检索描述过长会报错，要求重新做语义归纳，绝不静默截断。完整原文仍保存在组件及原始批次中，证据可回查。

本批次50个整体编码输入长度为446～858字符，属于归纳后的特征表达，不是把正文截到这个长度。

## 组件如何存储

每个组件保存：

```text
component_version_id        该数据集内组件记录的唯一ID
part_id                     原快照内稳定组件ID
parent_listing_version_id   所属整体版本外键
listing_version_id          与父版本一致，便于兼容现有接口
role / entity_kind          主图、附图、标题、五点、A+、详情、视频等
source_text / features      完整原文及自身的既有特征
reference / asset           URL、快照、原件哈希和原文件地址
controls                    整体依据、编码、检索、生成参考等独立开关
embedding_meta              模型摘要、配方、维度、输入哈希
vector                      该组件的独立向量，存于Qdrant向量字段
```

本轮1277个组件的原有特征和向量复用，并没有宣称重新识别了每张图或完整观看视频。文字组件目前仍以原文语义编码，图片/视频向量来自既有视觉描述的文本编码，不是原生像素或视频向量。视频审阅仍受原来的关键帧范围限制。

图片和视频字节不放进向量数据库。继续引用现有本地原件归档；后续接对象存储时应保存对象地址并增加读取适配。

## 整体与部分的关联

```text
整体集合：Listing_A_版本1
  ├─ 提炼特征 + 整体向量
  └─ component_ids（只保存有序ID，不嵌入全部组件内容）

组件集合：
  主图01 ─┐
  附图01 ─┤ parent_listing_version_id = Listing_A_版本1
  标题01 ─┤
  五点01 ─┤
  视频01 ─┘
```

新旧特征、模型或实际编码输入变化，会生成新的整体版本。组件引用绑定具体父版本；同一原图出现在不同版本中，可以共用原文件，但关系记录分别保存。不同数据集发布的向量点ID也分开，避免覆盖历史发布的成员关系。

## 当前文件位置

```text
D:/ListingStage2/
  src/listing_stage2/
    structured_whole.py          审阅校验、归纳特征组织、单次独立整体编码
    structured_model_review.py   后续LLM整体分析接口，默认仅预检
    collection_store.py          双集合、父子关联、Qdrant持久化和真实查询
    structured_batch.py          批次编码、入库核对、离线预览
  config/
    structured-model-api.example.json
  requirements-vector-store.txt
  run_structured_stage2.ps1
  outputs/batches/structured-whole-components-20261104/
    whole_notes.py               本轮GPT归纳数据，非线上关键词规则
    prepare_reviews.py          将本轮归纳绑定原始组件及完整输入指纹
    reviews/rankN.json           50套可核对的语义审阅
    review_tasks/rankN.json      完整原文和已有组件特征输入
    release/
      index.html                当前总览
      rankN/whole_record.json    单条整体记录，不含组件内容
      rankN/index.html           整体特征、条件及关联组件预览
      library/library_index.json
      library/collections/whole_records.jsonl
      library/collections/component_records.jsonl
      verification.json
  data/vector_store/structured_20261104/
```

JSONL是可核对和迁移的双集合副本，不是拿JSON冒充数据库。第三阶段通过清单读取实际Qdrant两个集合，再在内存中关联整体与组件，复用原有评分和展示逻辑。当前50套规模的应用评分仍在Python执行；collection_store.query_collection也提供真实Qdrant相似查询，已与应用结果对照核验。

历史全文v4、摘要v3和早期草稿保留用于追溯；当前发布指向release。全文汇聚不再是默认整体编码路径。旧API/历史实验入口仍保留兼容，新的双集合入口使用run_structured_stage2.ps1。

## 运行本地批次

本轮已准备独立环境，继承本机已有第二阶段依赖。其他机器新增向量库依赖时：

```powershell
D:/python/python.exe -m venv --system-site-packages D:/ListingStage2/.venv
D:/ListingStage2/.venv/Scripts/python.exe -m pip install -r D:/ListingStage2/requirements-vector-store.txt
```

已有完整组件分析和语义审阅后，用新的输出目录运行：

```powershell
& D:/ListingStage2/run_structured_stage2.ps1 `
  -SourceBatch D:/ListingStage2/outputs/batches/all50-full-evidence-20261103 `
  -ReviewDirectory D:/ListingStage2/outputs/batches/structured-whole-components-20261104/reviews `
  -Output D:/ListingStage2/outputs/batches/my-structured-run `
  -StorePath D:/ListingStage2/data/vector_store/my-structured-run
```

## 后续LLM配置

复制structured-model-api.example.json为自己的*.local.json。填写实际base_url、model、api_key_env，按服务商选择token_parameter和json_mode；密钥放在本机环境变量中。模板enabled=false，不调用远程服务。

这是整体语义提炼接口：输入完整原文和既有组件视觉描述，输出可追溯结构化整体特征。不会代替初次图片理解或视频转录。每次调用只生成一套待审核JSON；没有合法审阅不会退回“原文一股脑编码”。

无联网预检：

```powershell
$env:PYTHONPATH='D:/ListingStage2/src'
D:/ListingStage2/.venv/Scripts/python.exe -m listing_stage2.structured_model_review `
  --bundle D:/ListingStage2/outputs/batches/all50-full-evidence-20261103/rank3/listing_features.json `
  --config D:/ListingStage2/config/structured-model-api.example.json --plan
```

确认本地配置后，显式执行（可能产生服务商费用；没有自动重试）：

```powershell
D:/ListingStage2/.venv/Scripts/python.exe -m listing_stage2.structured_model_review `
  --bundle D:/ListingStage2/outputs/batches/all50-full-evidence-20261103/rank3/listing_features.json `
  --config D:/ListingStage2/config/structured-model-api.local.json `
  --output D:/ListingStage2/outputs/new-reviews/rank3.json --execute
```

输出JSON结构以本轮reviews/rank3.json为完整范例。API只做文本综合，源证据指纹、组件ID、对象范围及条件由程序校验；格式通过并不等于语义或事实正确，仍待运营审核。

## 第三阶段

默认config/runtime.json指向当前release/library/library_index.json。主图/附图/五点等用途匹配仍默认暂缓，当前返回整体。

国家、品类和产品描述现在均可省略。只输入卖点时不会补入topper或其他背景；空查询会明确拒绝。

```json
{"selling_points": ["soft", "lightweight"]}
```

```powershell
& D:/ListingStage3/run_match.ps1 `
  -Request D:/ListingStage3/config/request.selling-points-only.example.json `
  -Output D:/ListingStage3/outputs/my-v5-match-01
```

每次用新的输出目录。该脚本优先使用第二阶段独立环境，以加载Qdrant依赖。直接用Python启动时也需选择同一环境。

生成规划需要组件时，通过父版本查询，不能默认把其他整体的组件混进来：

```python
from listing_stage2.collection_store import query_collection

# query_vector必须由该集合兼容的模型生成。
wholes = query_collection(manifest_path, query_vector, limit=5)
parts = query_collection(
    manifest_path, component_query_vector, limit=10,
    listing_version_ids=[confirmed_listing_version_id],
)
```

组件查询会检查父版本及启用/检索/生成参考开关；具体角色、用途和运营确认仍由后续规划决定。本轮原有第三阶段匹配逻辑还会执行组件身份与模型配方检查。

## 验证和边界

- 第二阶段49项、第三阶段25项测试通过，包含真实Qdrant持久化、父子过滤、输入完整性、过期审阅拒绝、来源归属、版本发布隔离及空查询。
- 当前批次50条整体和1277条组件均经过数据库回读核对；151条原禁用组件保留来源和向量。
- 整体向量单独编码一次，组件数值改变不会被平均进整体。
- 背景解释、未成立卖点和原文不进入正向整体检索输入，但保留元数据和证据。
- 英文soft + lightweight的当前第一套为采集第3号，条件仍限定2英寸选项；冬暖夏凉第一套为22号的手动分层方向。相关性并非全部经过人工验收。
- 本轮没有更换nomic向量模型。已确认的中文分词问题仍存在；中文短词不能因换了存储结构就自动恢复正常。
- 本轮无远程LLM API费用、无生成、无MySQL写入、无媒体搬移。
