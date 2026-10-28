# Adapters

具体基础设施适配器：OpenAI-compatible 文本模型、受约束的 `ModelCommunityPolicy`，
以及复用内核持久化实现的 JSONL 存储薄适配。旧场景和文学适配器已退役。

这些模块只由 `engine.bootstrap` 装配；领域层和应用层不得导入本目录。模型适配器
只有在调用方显式提供模型配置或 `TextModel` 时启用。
