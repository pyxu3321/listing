> 2026-11-02 更新：已新增整套 Listing 向量、同第一阶段的分类目录、整套检索与组合选择 CLI，以及 MySQL 整体包读回验证。当前行为和新增文件以 [最新实现说明](整体Listing实现.md) 为准；下文保留早期状态与后续规划。

# 第二阶段运行手册

## 环境与依赖

当前是本机试验：`D:/ListingStage2`、`D:/ListingAnalysis`、`D:/Crawl4AI` 需同时存在。Python 固定为 `D:/python/python.exe`。当前未提供独立安装发行包。

默认输入为旧项目 `data/gpt_top5/payload.json`，校验值在本项目 config/pilot.json。来源报告、历史 GPT 审阅及原始媒体需保留。MySQL 连接配置在旧项目 config/mysql.local.json，不要复制密码到文档或日志。

## 默认运行：复用已有分析和向量

```powershell
& 'D:\ListingStage2\run_stage2.ps1'
```

不产生新的视觉分析，不调用付费模型，不写 MySQL。仍会重新写本地导出文件。

## 写入本机试验 MySQL

```powershell
& 'D:\ListingAnalysis\start_mysql.ps1'
& 'D:\ListingStage2\run_stage2.ps1' -MySQL
```

此命令有数据库写入。端口 3307，数据库 listing_analysis_pilot。现有六表按键更新；stage2_exports 保存本次衍生结果。六表具有读回验证，但新增 stage2_exports 尚无独立读回验证。整个流程不是跨文件与数据库的原子事务。

## 从已有 GPT 特征重建文本向量

```powershell
& 'D:\ListingStage2\run_stage2.ps1' -RefreshVectors
```

需要本地 Ollama 可用及对应模型；复用旧 build_payload 编码逻辑，不重新识图。缓存写入 data/cache，运行中间文件写入 data/runtime。该路径不代表已支持任意新商品自动导入。

## 调整聚类阈值

根目录脚本没有 Threshold 参数；用 Python 模块入口：

```powershell
$env:PYTHONPATH = 'D:\ListingStage2\src'
& 'D:\python\python.exe' -m listing_stage2 --threshold 0.80
```

阈值范围为大于 0 且不大于 1。调整值是实验，不代表业务校准已完成。

## 看结果

查看 outputs/latest.json 定位结果目录。已保存的基线为 `outputs/batches/19225d99d8e58ee20249/`。

| 文件 | 用途 |
| --- | --- |
| payload.json | 5 商品、65 图、107 特征及向量、来源链 |
| clusters.json | 图片特征的 16 个候选分组（默认基线） |
| quality.json | 未校准的 null 评分 |
| principles.json | 5 条待审核商品级候选分析 |
| stage3_bundle.json | 第三阶段文件索引，仍为 pending_review |
| index.html | 本机只读图片/特征卡片；引用原图绝对路径 |
| run.json | 本次参数结果计数及可选 MySQL 核验结果 |
| mysql_verification.json | 执行 MySQL 加载时产生的六表验证记录 |

HTML 不能单独发给同事就保证图片可见。分享需打包媒体并改相对引用，或后续提供可访问的对象存储链接；目前没有一键分享功能。

当前 run_id 由 batch_id、stage2-v1 和阈值生成，不是每次新建的时间戳。相同输入和阈值会写入同一目录；代码变化目前也未自动纳入运行 ID。重复运行不能当作保留全部历史版本的方案。

## 测试

```powershell
$env:PYTHONPATH = 'D:\ListingStage2\src'
& 'D:\python\python.exe' -m unittest discover -s 'D:\ListingStage2\tests'
```

现有四项：拒绝重复特征 ID；拒绝 NaN 向量；修改排名元数据不改变当前分组且评分保持 null；图片特征分组完整且不重复。测试依赖本机试验数据，不是隔离的发布验收套件。此前运行通过；本次仅改文档，没有重跑业务或模型。

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| Source report changed / Review changed | 来源或分析已变化；核对来源后重建关联产物，不直接跳过哈希校验 |
| Asset changed | 图片文件与证据哈希不符，恢复原文件或创建新版本 |
| Invalid vector / Mixed embedding spaces | 检查维度、NaN、范数及模型摘要，按正确配方重建 |
| 找不到旧项目或 payload | 当前仍依赖旧试验，按既有目录恢复；不是通用导入程序 |
| MySQL 连接失败 | 确认本机 3307 实例和本地配置，不重复新建不明数据库 |
| 图片卡片空白 | 原图路径失效或浏览器本地资源限制，检查本机文件路径 |
| latest 未更新但有文件 | 中途失败可能留下部分文件；检查异常及 run.json，不据文件存在判成功 |
