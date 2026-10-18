# Bootstrap

`composition.py` 是唯一具体装配点。`build_application` 默认建立完全确定性的
Actor、Renderer 和内存存储；只有显式模型配置/注入才装配模型适配器。

bootstrap 可以依赖所有内层模块和 adapters，其他模块不得反向依赖 bootstrap。
