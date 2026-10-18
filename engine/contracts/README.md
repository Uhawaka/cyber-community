# Contracts

跨层端口的依赖根。这里只允许 Python 标准库和通用 `Protocol`/泛型，不得导入
world、runtime、narrative、application、adapters 或 bootstrap。

`TextModel`、`ActorPolicy`、`NarrativeRenderer`、`RunStorage` 和
`PresentationStorage` 均采用结构化实现，不要求实现类继承端口。
