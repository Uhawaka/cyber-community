# Bootstrap

`composition.py` 是唯一具体装配点。`build_application` 默认建立完全确定性的
社区生活策略和内存存储；只有显式模型配置/注入才装配 `ModelCommunityPolicy`。
传入日志路径时使用 JSONL 存储，不装配旧场景或文学发布组件。

bootstrap 可以依赖所有内层模块和 adapters，其他模块不得反向依赖 bootstrap。
