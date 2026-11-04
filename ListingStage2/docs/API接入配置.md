# 第二阶段 API 接入配置与试跑

更新：2026-11-02。代码已提供可执行入口，当前完成离线 dry-run、模拟接口及既有流程回归测试；没有使用真实密钥调用付费服务。真实供应商的模型能力、参数和返回兼容性需要你取得 API 后验证。

## 本次可运行的数据流

第一阶段 report.json → 指定历史排名的一个商品 → 组件配置 → 每个活动组件一次图文分析 → 整体综合一次 → 待审阅特征文件 → 可选本地 Ollama 向量化 → 现有 reference_library 导出。

模型负责提取特征，不生成商品图。整体向量来自整体叙述，组件向量分别生成，二者独立。生成方案模板目前仍由人工整理，本入口不自动写已验证模板。

## 1. 准备配置

在 PowerShell 中复制：

```powershell
Copy-Item -LiteralPath 'D:\ListingStage2\config\model-api.example.json' -Destination 'D:\ListingStage2\config\model-api.local.json'
```

编辑 model-api.local.json，重点修改：

| 字段 | 填写方法 |
| --- | --- |
| enabled | 真正试跑时改为 true；示例为 false |
| protocol | 当前固定 chat_completions |
| base_url | 接口前缀，如 https://api.openai.com/v1；代码会追加 /chat/completions，不要重复填写完整路由 |
| api_key_env | 密钥所在环境变量名，默认 LISTING_MODEL_API_KEY |
| model | 你的账户可调用、支持图像输入和所需 JSON 模式的真实模型 ID；不填聊天产品的显示名称 |
| json_mode | json_object；供应商不支持时可改 prompt_only，但返回仍须是纯 JSON |
| token_parameter | max_completion_tokens 或 max_tokens，按模型支持情况选择 |
| max_output_tokens | 每次输出上限，默认 2500；截断会报错，不自行补全 |
| timeout_seconds | 每次请求超时，默认 120 秒；不是整项任务总时限 |
| max_calls | 每次运行调用次数上限，默认 30；计划超限在请求前终止 |
| max_image_bytes | 单张源图上限，默认 8388608 字节；不会自动缩图 |
| embedding.provider | 当前固定 ollama_local，尚未提供远程 Embeddings API |
| embedding.url/model | 本地 Ollama 地址和已安装的向量模型 |

其他 Chat Completions 兼容服务可修改 base_url 和 model，属于协议适配能力，不保证所有供应商完全兼容。当前没有 Responses、Azure 专用认证、原生 Gemini/Anthropic、云端嵌入或视频直传适配器。

请求用 system/user 消息，图片以 image_url 内的 Base64 data URL 发送；当前支持 JPEG/PNG/WEBP。图像内容会上传至你配置的服务地址。URL 必须为 HTTPS，本机测试允许 localhost/127.0.0.1/::1 的 HTTP；拒绝携带用户名/密码/查询密钥，拒绝 HTTP 重定向。

## 2. 配置密钥

只在自己的 PowerShell 中设置，勿发送到聊天。可使用隐藏输入：

```powershell
$listingSecret = Read-Host '输入模型 API Key' -AsSecureString
$env:LISTING_MODEL_API_KEY = [System.Net.NetworkCredential]::new('', $listingSecret).Password
Remove-Variable listingSecret
```

该变量只在当前 PowerShell 会话及其子进程有效。配置文件只填环境变量名，不填 api_key。程序不自动读取 .env，也不把 Authorization 或图片 Base64 写入运行记录。*.local.* 已由项目 .gitignore 排除。

## 3. 先做无费用预检

```powershell
& 'D:\ListingStage2\run_api_analysis.ps1' `
  -Report 'D:\Crawl4AI\library\runs\20261029T004510Z_fdcb2277_content_a81a90\report.json' `
  -Rank 1 `
  -Config 'D:\ListingStage2\config\model-api.local.json' `
  -Policy 'D:\ListingStage2\config\components.json' `
  -Output 'D:\ListingStage2\outputs\api_analysis\my-first-plan'
```

不加 -Execute 时不联网、不读取密钥、不访问 Ollama。检查媒体哈希、图片格式/大小、组件配置及预计调用次数，并输出 plan.json/input_task.json。每次使用新的空输出目录，防止混用结果。

项目已运行的真实来源预检见 outputs/api_analysis/rank1-dry-run/plan.json：17 个可用组件（11 图、标题1、五点5），预计18次调用（组件17次+整体1次），付费调用0。旧第一名 v3 的18组件包含另外补充的视频；新入口未发送视频，因此不是丢失一个组件。

## 4. 控制组件与费用

使用 config/components.json 的类型规则；单项覆盖见 components.override.example.json。新任务的 part_id/task_version_id 在 input_task.json 与 plan.json 中，不一定等于历史人工分析的 ID。单项配置必须绑定本次 task_version_id，不能直接照抄旧 v3 ID。

只有组件四个使用开关全部关闭时才跳过分析。embed=false 只关闭组件向量；如果 include_in_overall=true，仍需付费提取其特征，用于整体综合。generation_reference=true 也意味着需要该组件特征。enabled=false 会关闭全部使用开关；max_components 依源组件顺序限制数量。

首次可将 aplus 类型 enabled 设为 false，仅保留主图、少量附图、标题和五点试跑。此时整体叙述只概括启用部分，缺失范围必须结合 plan 和原始快照查看。每个活动组件一次调用，最后整体一次。

max_calls 和输出 token 上限不能保证固定金额；真实费用取决于供应商和输入图文长度。没有自动重试或自动续跑。超时后供应商可能已计费，先查后台记录再决定是否重跑。

## 5. 真正执行

确认 enabled=true、模型/接口参数已填好、当前会话密钥存在后：

```powershell
& 'D:\ListingStage2\run_api_analysis.ps1' `
  -Report 'D:\Crawl4AI\library\runs\20261029T004510Z_fdcb2277_content_a81a90\report.json' `
  -Rank 1 `
  -Config 'D:\ListingStage2\config\model-api.local.json' `
  -Policy 'D:\ListingStage2\config\components.json' `
  -Output 'D:\ListingStage2\outputs\api_analysis\my-first-live-run' `
  -Execute
```

需要分析后直接生成向量，加 -Encode。默认不编码，方便先检查模型提取质量。此入口独立于旧 run_stage2.ps1，不会改变旧冻结实验。

## 6. 单独向量化，不重复付费分析

分析成功后安装并启动本地 Ollama，确保配置模型存在。项目当前使用 nomic-embed-text:latest；其本地部署仍消耗本机算力。

```powershell
$env:PYTHONPATH='D:\ListingStage2\src'
& 'D:\python\python.exe' -m listing_stage2.encode_analysis `
  --input 'D:\ListingStage2\outputs\api_analysis\my-first-live-run' `
  --config 'D:\ListingStage2\config\model-api.local.json'
```

此步骤读取已分析文件，仅请求本地 Ollama，不再请求图文模型。先核验审阅输入指纹，再独立编码整体与启用的组件，输出 listing_features.json、encoding.json。整体会保留明确待人工审核状态。

## 7. 导出为第三阶段候选库

```powershell
$env:PYTHONPATH='D:\ListingStage2\src'
& 'D:\python\python.exe' -m listing_stage2.reference_library `
  --bundle 'D:\ListingStage2\outputs\api_analysis\my-first-live-run\listing_features.json' `
  --policy 'D:\ListingStage2\config\components.json' `
  --output 'D:\ListingStage2\outputs\reference_library\my-first-api-library'
```

第一轮建议只使用类型规则。分析前后的 ID 不同，单项覆盖应根据新 listing_features.json 的 bundle_id/part_id 重新绑定。若导出策略再改变整体参与范围，会标记需要重审，不能继续沿用旧整体向量。

此步骤写本地 JSON，不写 MySQL，也不执行 Qdrant 同步或自动发布。

## 返回内容与校验

组件响应包含 semantic_description_en、identity_scope、composition、palette、scene、themes、claims、limitations。claims 必须带 basis，区分 visible_observation/source_claim/unknown；主图角色来自采集证据，不由模型随意改写。所有模型输出保持 quality_score=null、pending_operator_review。

整体响应包含 keywords、audience、scenes、style、information_order、limitations、selling_points、embedding_text_en。每条卖点引用本次允许的 evidence_part_ids；整体叙述不超过6000字符。检测为关联商品或未知身份的图片仍保存组件特征，但不自动纳入整体证据。

JSON 格式正确并不代表内容真实。认证、功效、尺寸等来源声明仍要由运营核验。当前不自动生成质量评分、批准状态或生成模板。

## 结果文件

| 文件 | 含义 |
| --- | --- |
| plan.json | 计划、分类身份、组件开关、预计调用次数，paid_calls=0 表示计划本身未调用 |
| input_task.json | 原始任务与素材引用 |
| component_reviews/*.json | 已校验组件特征、提示词哈希、图像哈希、模型与用量 |
| analyzed_bundle.json | 分析结果与组件关联 |
| review.json | 整体特征、输入指纹、调用元数据 |
| run.json | API分析成功或失败、已完成调用；失败不伪装成成功 |
| listing_features.json | 可选编码生成的 v3 结果 |
| encoding.json | 整体/组件向量数量和待审核状态 |

## 排错

| 现象 | 处理 |
| --- | --- |
| API disabled | 使用本地配置并改 enabled=true |
| Missing API-key environment variable | 在执行脚本的同一 PowerShell 会话设置变量 |
| HTTP 401/403 | 查密钥、权限、服务地址；错误记录不保存供应商原始错误正文 |
| HTTP 400 | 核对视觉输入、json_mode、token_parameter 和模型 ID；不同供应商参数不一定相同 |
| HTTP 429/连接超时 | 查供应商限流和实际计费，再决定新目录重跑；不会自动重试 |
| Model response incomplete/refused | 查看供应商记录，必要时调大输出上限或更换合适模型 |
| JSON/字段校验失败 | 模型未按契约返回；已有组件结果保留，失败任务不导出成可用整体 |
| Source image hash mismatch | 原文件已变动，回查快照或重新导入 |
| 整体输入过长 | 通过类型或单项规则减少输入；不静默截断 |
| Ollama失败 | 先检查本地服务/模型；已有 API 分析结果保留，可用 encode_analysis 单独重做编码 |

技术依据：[OpenAI 图像输入文档](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat)、[Chat Completions 创建接口](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。文档核对日期2026-11-02，不代表所有兼容服务均支持同样参数。
