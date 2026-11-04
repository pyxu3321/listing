# 当前依赖

- Python：本机 D:/python/python.exe。
- NumPy：向量校验、归一化和原有聚类。
- Pillow：验证输入图片格式。
- 模型API：使用Python标准库HTTP，无需额外供应商SDK；按model-api.example.json配置。
- Ollama：启用本地编码时需要单独运行，并安装配置中的nomic-embed-text模型。
- PyMySQL/MySQL：仅保留的历史数据库实验依赖，旧加载器从D:/ListingAnalysis读取环境。

当前没有部署FiftyOne、Qdrant、Langfuse或LangGraph。API入口配置和限制见 [API文档](../docs/API接入配置.md)。
