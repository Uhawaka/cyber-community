# Runtime

## 职责
承载事件内核、角色状态、空间机会和自主模拟执行。

## 输入
版本化社区 `CompiledWorld`、seed 与 `CommunityPolicy`。

## 输出
可重放事件历史、`WorldState`、`TickReport` 与因果追踪。

## 禁止事项
不得依赖 narrative/application；simulation 不得绕过 kernel 直接持久化；不得引入剧本或预定结果。

## 公共 API
以 `engine.runtime` 为稳定入口；simulation 子包只提供社区创建、执行、追赶和解释接口。
旧执行器、场景、导演、参与者与冷热模拟路径已退役。
