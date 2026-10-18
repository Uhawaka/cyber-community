# Application

## 职责
编排运行时、参与者、世界包验证与叙事交付用例。

## 输入
已编译世界、用户命令、运行记录、交付策略。

## 输出
应用服务结果、观察视图、验证报告与已发布叙事。

## 禁止事项
不得实现世界规则、事件归约或叙事事实生成；不得绕过 runtime 公共 API 修改状态。

## 公共 API
以 `engine.application` 导出的运行、参与、观察、交付和验证函数为准。

具体 Actor、Renderer、模型客户端和持久化适配器统一由
`engine.bootstrap.composition.build_application` 装配；application 不导入
`engine.adapters`。CLI 默认使用确定性装配，只有显式 `--model-config` 才启用模型。
