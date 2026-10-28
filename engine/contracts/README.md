# Contracts

跨层端口的依赖根。这里只允许 Python 标准库和通用 `Protocol`/泛型，不得导入
world、runtime、narrative、application、adapters 或 bootstrap。

当前主链使用 `CommunityPolicy`、`TextModel` 和 `RunStorage`，采用结构化实现，
不要求实现类继承端口。事件、实体、认知和作者体验配置的共享数据契约保留在此，
它们不会装配或启动已经退役的场景、导演及文学发布执行链。
