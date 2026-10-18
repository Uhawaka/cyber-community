# Soul 与 Memory 边界契约

## 权威来源

- 世界包中的 `soul.yaml` 是不可变作者定义。运行时不得改写世界包或编译产物。
- `WorldState.CharacterState.soul_overlay` 是版本化运行投影；只有带 typed `SoulDelta` 的 `soul_evolution_approved` 事件能更新它。
- Event Log 保留完整历史。遗忘、预算和压缩只改变 Memory 投影视图，不删除来源事件。

## Soul

作者 schema 明确为 `identity`、`self_view`、`values`、`taboos`、
`protective_style`、`drives`、`voice`、`relationship_stance`。字段可按角色需要
选用，但 `values`、`voice`、`drives` 是最低身份输入；缺失或类型错误由 compiler
给出结构化诊断。

ActorPolicy 读取“作者 Soul + 当前 overlay”的合并视图。overlay 按 trait 覆盖作者
值，但不改变世界包。演化提案必须引用至少三条角色可见的高强度来源事件；普通对话
不计入证据。冷却读取 `soul_overlay.last_evolution_tick`，不能靠扫描自由文本判断。

批准事件必须包含角色、trait、期望版本、值和来源 sequence 的 `SoulDelta`。应用时
版本加一并保存 trait 与 evidence。拒绝事件没有 Soul Delta，因而状态不变。相同 seed、
初始状态和事件可重建完全一致的 overlay。

## Memory

`memory_consolidated` 是有语义的投影事件，不是 marker。其 data 必须包含：

- `source_sequences`：非空且均为该角色可见的既有事件；
- `target_tier`：`semantic` 或 `core`；
- `belief_type`：`fact`、`inference` 或 `misbelief`；
- `confidence`：0 到 1；
- `summary`：只由来源事件的既有摘要、描述或实际话语确定性压缩。

Working 与 episodic 直接按角色可见历史和固定预算投影；semantic 与运行时 core 只
消费合法的 consolidation 事件。错误认知仍属于角色私有信念，不能变成客观事实，也
不能泄露给未观察来源事件的角色。没有来源 sequence 的运行时新事实必须拒绝。

删除 MemoryProjection 后，使用作者 seed 与 Event Log 重建，结果必须逐项一致。
