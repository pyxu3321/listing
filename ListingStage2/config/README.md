# 配置核对入口

更新：2026-11-03。原始JSON保持严格格式及原值不变。

先打开 [配置逐项注释.jsonc](配置逐项注释.jsonc)，其中按原文件名逐项附中文说明，包含嵌套字段和示例ID。该文件只供阅读，不是程序输入。实际运行仍使用对应的.json；修改原文件后要同步核对本对照快照。

| 原始配置 | 用途 | 读取位置 |
| --- | --- | --- |
| model-api.example.json | API地址、模型、密钥变量、调用/输出上限、本地编码 | model_gateway.load_config；由api_analysis/encode_analysis使用 |
| components.json | 类型开关和数量上限 | component_policy；仅显式传--policy时应用 |
| components.override.example.json | 指定版本与组件的单项覆盖 | component_policy；独立示例，不自动与components.json叠加 |
| generation-recipes.example.json | 表达模板、适用范围、约束和验证记录 | reference_library的--recipes；不会执行生图 |
| pilot.json | 冻结旧五商品payload哈希 | phase1_reader.load；旧实验必须与原文件匹配 |
| rank1-whole-review.json | 第一名整体及视频人工审阅结果 | rank1_experiment；属于输入数据，不是通用API配置 |
| selection-example.json | 旧v2跨Listing组件组合 | match_preview的--selections；不是v3新索引配置 |

关键规则：

- API enabled=false默认不调用；真实执行还需-Execute、有效模型和同会话密钥环境变量。
- 组件仅关闭embed不一定减少API分析费用：只要参与整体或生成参考，仍需提取特征。
- enabled=false软禁用，原素材保留；数量上限按来源顺序，不代表质量排名。
- 修改已有v3整体参与范围后必须重审/重编码；只关闭检索不用重算整体。
- validated不是手工改一个状态即可生效，必须有同条件试验和版本绑定审核；示例仍为draft。
- JSON不要写//、尾逗号或明文密钥；密钥只从环境变量读取。

完整试跑方法见 [API配置文档](../docs/API接入配置.md)，代码职责见 [文件说明](../docs/file-map.md)。

## 当前v5整体模型接口

`structured-model-api.example.json`用于完整文字和既有视觉特征的整体语义归纳；默认`enabled=false`，不填密钥。执行方式、字段和范例见[整体组件双集合与API](../docs/整体组件双集合与API.md)。组件数量没有固定上限，由来源与原components配置决定。
