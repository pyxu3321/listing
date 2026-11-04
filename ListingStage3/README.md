> 当前默认：v5本地Qdrant双集合，50套整体、1277条组件；先选整体，组件暂缓。支持仅填写selling_points，不补产品描述或筛选条件。[说明](D:/ListingStage2/docs/整体组件双集合与API.md) · [读取与检索验证](outputs/structured-v5-release-check-20261104/index.html)。旧段落为历史实验记录。

> v6细粒度特征试验另运行在 http://127.0.0.1:8766 ，仅8套，支持逐图颜色角色和属性条件核对。示例配置为config/runtime.detailed-pilot.example.json；与v5整体配方不可混排。输入LLM尚未接入。

> 当前默认库：完整证据v4的50套Listing，配置为config/runtime.json。历史段落中的前五套、旧50套结果保留作实验记录。

# Listing 第三阶段：按用户输入匹配参考

接收产品描述、卖点、市场、品类、风格及需要的素材类型，先匹配整套Listing，再从这些整体候选内选择组件。结果供运营确认后进入第四阶段；不在此生成图片或自动发布。

## 运行

```powershell
# 只检查输入和库，不调用模型
& 'D:\ListingStage3\run_match.ps1' -Output 'D:\ListingStage3\outputs\plan' -Plan

# 实际匹配，使用本地Ollama
& 'D:\ListingStage3\run_match.ps1' -Output 'D:\ListingStage3\outputs\my-match'
```

修改 config/request.example.json，或者用 -Request 指定自己的JSON；输出使用新的空目录。config/runtime.json配置特征库和检索阈值。

[前五名最新匹配](outputs/first-five-refined-20261103/index.html) · [输入与配置说明](config/README.md) · [架构和接口](docs/architecture.md)

## 项目目录

```text
config/                    用户输入示例与运行配置
src/listing_stage3/
  __main__.py              CLI及流程编排
  encoder.py               复用第二阶段本地编码器
  library.py               特征库加载与完整性校验
  matcher.py               整体排序及候选内组件匹配
  output.py                JSON参考包和离线核对页面
tests/test_matching.py     离线回归测试
docs/architecture.md       数据流、分数、边界及后续接口
data/query_cache/          本地查询向量缓存
outputs/                   每次参考包、页面和来源清单
run_match.ps1              启动脚本
```

## 已跑通与边界

当前v3库只有第一名一个整体，含18个已分析组件；本轮将A+/视频等组件全部开放。示例返回1套整体、1个主图、3个附图、3个A+、3条五点和1个视频候选。具体分数与数量随输入和阈值变化，不代表这些素材已批准使用。

当前支持 reviewed-whole-listing-summary-v3 和 component-semantic-text-v1，不混用历史v2聚合向量。更多整体候选需要先在第二阶段完成分析，再把新library_index.json加入运行配置。第一阶段补下载的新素材不会自动获得向量。

仅请求本地Ollama，未接远程查询API、Qdrant或业务MySQL。复用 D:/ListingStage2/src 的编码实现，不是独立复制即可部署的发行包。

模型相似度不是质量分、销量或真实性评分。用户输入卖点属于待核验陈述；竞品参数、认证及功效不得转为自有事实。自有产品资料和图片不完整时仍可检索，但结果明确提示缺失项且generation_ready=false。
# 前五名实验更新（2026-11-03）

当前默认库包含前五名的5个整体向量及118个活动组件检索向量，来源共132个组件。默认先选3套整体，再按用途给组件候选。[完整实验说明](D:/ListingStage2/docs/前五名第二三阶段实验.md)。

- 最终页面：`outputs/first-five-refined-20261103/index.html`。
- 结构筛选示例：`config/request.pillow_top.example.json`、`config/request.memory_foam.example.json`。
- 用途可指定`entity_kind`，区分A+图片和A+文字。
- 可配置`preferred_themes`用于途标签精排，分数和原始相似度分别保存。
- 图片/视频向量来自GPT视觉语义描述的本地文本编码，当前没有使用原生视觉嵌入模型。
- 所有结果待审核；视频仅抽帧，缺少自有事实与图片，尚未执行生成。


## 整体产品与风格分开评分（2026-11-03）

默认65%产品卖点+35%视觉风格；风格依据候选内合格图片的描述向量，页面展示证据图。详见[配置、输出字段和限制](docs/整体双路评分.md)。[50套库12案例重跑结果](outputs/split-scoring-20261103/index.html)，16项单元测试通过。默认库仍为前五套，50套测试配置单独保存。

## 当前默认行为：先选整体，组件延后

整体先按综合分取前N套，再把分差在0.02以内的同范围候选按采集排名排序；N可配置。组件用途匹配默认关闭。[详细说明](docs/相近候选排序与组件延后.md) · [柔软、轻便实测](outputs/soft-lightweight-whole-only-20261103/index.html)。

## 完整来源文字整体向量

默认配置现已切换到第二阶段all50-full-evidence-20261103库。支持v3旧摘要或v4完整证据，但同次排序禁止混用。[完整来源处理说明](D:/ListingStage2/docs/完整原文整体编码.md)。
