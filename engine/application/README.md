# Application

## 职责
社区只读观察、机制诊断与独立人工评审。

## 输入
已编译社区世界、持久化运行记录与人工标注。

## 输出
公共观察、私有机制报告与评审材料。

## 禁止事项
不得实现世界规则、事件归约或叙事事实生成；不得绕过 runtime 公共 API 修改状态。

## 公共 API
以 `engine.application` 导出的生命周期与 `observe_community` 为准。

具体社区模型策略、模型客户端和持久化适配器统一由
`engine.bootstrap.composition.build_application` 装配；application 不导入
`engine.adapters`。CLI 默认使用确定性装配，只有显式 `--model-config` 才启用模型。
