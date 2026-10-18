# ADR-0003：模拟与呈现分离

- 状态：Accepted（核心门禁已实现）
- 日期：2026-10-17

## 决策

模拟负责合法性、结算和 Event Log；呈现只消费已提交事件与只读投影。呈现产物写入独立 `PresentationStore`，不作为 Event Log 的 Delta，也不参与 replay 的客观状态。

呈现可以失败、重试、替换或生成多种媒介，而不重新结算世界。模拟也可以在没有任何呈现服务时继续。

## 理由

文本生成容易添加未经结算的动作和结果。存储与执行分离才能安全重渲染、切换媒介，并独立处理已读、缓存和交付失败。

## 输入、输出与失败

- 输入：连续来源事件、受众可见性、Scene Contract、呈现 Workflow。
- 输出：带来源、版本和校验状态的 `PresentationArtifact`。
- 失败：来源缺失、越权可见、合同未满足、事实不支持、存储不可用；均不得修改世界事实。

## 后果

- `PresentationStore` 保存正文、artifact 版本、渲染诊断和受众游标；已读与通知状态保留为后续扩展。
- Renderer 不得调用 Resolver、推进 Tick 或提交事件。
- 改结果必须 fork；只改表达则重渲染同一来源事件。

## 实现状态

- `engine.narrative` 不导入 runtime 或 application；runtime 事件只在 application 边界适配为只读来源视图。
- `PresentationStore` 支持独立文件、原子写、`0600`、schema/render version、严格加载和按受众独立游标。
- Avatar 来源按事件 `observers` 过滤，全知 Observer 使用显式 `omniscient` 模式；摘要不携带 Event Log 中的私有 seed 数据。
- renderer 异常、超时、错误返回和事实越界均记录诊断并确定性回退。直接引语、来源 ID、关键实体和因果顺序由发布前校验器检查。
- 存储可清空，并从 Event Log 与 delivery policy 重建相同来源范围；`get_observer_home` 只读返回世界摘要、近期变化、待处理 gate 与 Episode 到期判断。
- `non_factual_atmosphere` 字段已保留但当前禁用，非空内容会被拒绝，且不参与知识投影。
- 尚未实现的目标能力：Scene Contract、hook、通知/已读状态及通用多媒介 artifact。

## 验收

1. 两种 renderer 对同一事件生成不同产物，世界 replay 相同。
2. 清空 PresentationStore 不影响运行，可从来源事件重建。
3. 呈现写入失败不回滚已提交世界事件。
