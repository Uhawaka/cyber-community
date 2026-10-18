# EXP-20261017-001：离线追赶与冷热模拟门禁

## 元数据

- 状态：passed
- 日期：2026-10-17
- 关联里程碑：M2 / M3
- 世界包：`echo-quay`
- Runtime：autonomous runtime / `SimulationPolicy`
- RNG seed：`17 / 71`
- 复现命令：
  - `PYTHONPATH=. pytest -q tests/test_cold_simulation.py tests/test_runtime_budgets.py`
  - `python scripts/benchmark_runtime.py --ticks 1`

## 单一假设

如果详细模拟受热区和工作预算约束，超出详细窗口的时间以单个可重放粗粒度事件原子结算，那么离线追赶不会丢失世界时间，并且运行工作量不会随同地点角色数无界扩张。

## 范围

- 包含：详细/冷区角色选择、动作/机会/事件/记忆预算、粗粒度需求与既有本地采集计划结算、重放和 projection 重建。
- 不包含：粗粒度移动、对话、秘密、关系和 Soul 演化。
- 固定不变项：世界包内容、事件日志作为事实源、相同 seed 与 policy。

## 预期输出

- 超限追赶提交一个 `coarse_tick_summary`，其 Delta 推进全部剩余 tick 与 world time。
- 事件保留输入 state hash、seed/cursor、时间范围、冷热角色、结构化 Delta 和假设。
- 冷区不产生对话、关系、记忆或 Soul 细节；重新变热只从当前边界继续。
- TickReport 分别记录四类预算、使用量和耗尽状态。

## 结果证据

- `tests/test_cold_simulation.py`：2 个详细 tick + 8 个粗粒度 tick 后，最终 tick 为 10；导出再加载后的状态和记忆 projection 与原运行一致。
- `tests/test_runtime_budgets.py`：10 / 50 / 100 角色下，每 tick 的 `opportunities_evaluated <= 7`、`actions_used <= 3`。
- `scripts/benchmark_runtime.py --ticks 1` 输出单个 JSON 文档，包含耗时观察值但没有毫秒阈值断言。
- 零预算路径为每个未获准详细行动的角色提交合法 `waited`，运行在有限角色集合结束。
- 相同 seed、world 与 policy 的事件和 replay 状态由回归测试固定。

## 结论

- 判定：passed
- 保留规则：详细窗口之后必须提交可重放 Delta；冷区禁止补写细节；所有枚举和长期更新受显式预算门禁。
- 后续：如需粗粒度移动或事件跨区传播，必须先定义可交换、可聚合且不泄露细节的结算规则。
