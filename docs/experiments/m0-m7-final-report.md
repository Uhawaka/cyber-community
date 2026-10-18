# M0–M7 技术重建最终报告

日期：2026-10-17
结论：M0–M7 技术门禁完成；产品质量与生态工作后置。

## 口径

统一编号为 M0 边界、M1 最小 Runtime、M2 自主相遇、M3 叙事、M4 长期、M5 Avatar、M6 迁移、M7 门禁。“完成”表示代码、失败路径和自动化验证存在，不表示完整内容产品、文学质量或用户留存已经验证。

## 分阶段产物与测试

### M0 边界

产物：World Package/Compiler/Runtime/Event Log/Projection/Narrative/Presentation 权威链；ports、adapters 与 bootstrap 组合根；默认确定性、模型显式启用；Simulation Director 与只读 Narrative Curator 分责。

测试：`tests/architecture/test_import_boundaries.py`、`tests/test_entrypoints.py`、`tests/test_m6_composition.py`。

### M1 最小 Runtime

产物：typed Event/Delta/WorldState、append-only Event Log、原子校验、Tick、replay、fork、JSONL 持久化与恢复。

测试：`tests/test_autonomous_runtime.py`、`tests/test_autonomous_persistence.py`、`tests/test_autonomous_observability.py`。进程重启前后 events、state 与 history hash 一致；无换行坏尾可隔离恢复，中间坏记录与 world hash 不匹配 fail closed；文件权限为 `0600`。

### M2 自主相遇

产物：地点 affordance、通路与资源约束、opportunity、同快照 reservation、共享 Resolver、冲突拒绝/重规划、author incident。

测试：`tests/test_location_affordances.py`、`tests/test_reservations.py`、`tests/test_incident_user_gate.py`、`tests/test_package_probe.py`。

8-seed 结果：`echo-quay` 与 `black-pine-ridge` 各运行 8 个固定 seed、每次 20 tick；两包均通过 replay、Memory 来源、地图引用、资源/库存非负与对话共址不变量，且历史 hash 均为 8/8 唯一。

扰动结果：只修改资源数量或通路耗时都会改变 content hash 与结构化事件链，证明 Runtime 消费作者规则而非固定剧本。

### M3 叙事

产物：受众来源过滤、NarrativeDigest、确定性 Renderer、显式模型 Renderer、事实校验/回退、Episode/Presentation、持久化 `PresentationStore`。

测试：`tests/test_narrative_delivery.py`、`tests/test_narrative_visibility.py`、`tests/test_presentation_persistence.py`、`tests/test_autonomous_story_delivery.py`。模型新增事实会得到 `fact_validation_failed` 与 `fallback`；Avatar/omniscient 游标隔离；Store 可原子 round-trip、清空重建，写失败不改变内存或 Runtime。

### M4 长期

产物：action/opportunity/incident/memory/catch-up 预算；热区详细模拟与冷区粗粒度摘要；长期短计划与去重复；Memory/Soul 演化；phase snapshot；TickReport 与 causal trace。

测试：`tests/test_character_long_term.py`、`tests/test_cold_simulation.py`、`tests/test_runtime_budgets.py`、`tests/test_phase_snapshot.py`。

长期结果：两个包、seed `3/17/29` 的 20-tick 实验均出现 dialogue、move 和 gather；按角色同类动作最大连续数为 2，同类同目标最大连续数为 1。

冷热结果：2 个详细 tick 加 8 个粗粒度 tick 后最终 tick 为 10；导出再加载后的 state 与 Memory projection 一致。冷区不补写对话、关系、秘密或 Soul 细节。

### M5 Avatar

产物：严格 `AvatarPackage`、授权 join/leave/rejoin、离线 `pause`、NPC/Avatar 共享 opportunity/ActionAttempt/Resolver、UserGate 与 Fate Intervention。

测试：`tests/test_autonomous_avatar_runtime.py`、`tests/test_avatar_security_lifecycle.py`、`tests/test_autonomous_participation.py`、`tests/test_fate_intervention.py`。Avatar 缺席不被调度；对等 NPC/Avatar 非法移动返回相同错误；Fate 条件、once、cooldown 与成本失败均原子；Gate/Fate 支持 replay、fork 与 explain。

### M6 迁移

产物：两个目录世界包、capability 握手、稳定 content hash、四类 typed Workflow、封闭 `STEP_HANDLERS` registry、CLI、ports/adapters/bootstrap。

测试：`tests/test_world_package_compiler.py`、`tests/test_workflow_execution.py`、`tests/test_workflow_step_runtime.py`、`tests/test_black_pine_package.py`、`tests/test_package_cli.py`。四类 Workflow 均实际 dispatch 并记录 provenance；未知 op、乱序、缺 handler fail closed。

边界说明：这是四条固定 typed 执行链，不是任意 DSL、动态插件系统或公共生态。

### M7 门禁

产物：compile-first 安全 probe、路径/容量/schema 防护、8-seed 与扰动门禁、持久化恢复、冷热、Avatar/Fate、Presentation、模型回退、架构边界、CLI 与 benchmark。

测试：2026-10-17 执行 `python -m pytest -q`，131 个测试全部通过。

## Benchmark

命令：

```bash
python scripts/benchmark_runtime.py --ticks 3 --seed 17
```

固定 policy：`action_budget=12`、`opportunity_budget=32`、`incident_budget=1`、`memory_budget=1`。本机观测：

- 10 角色：21.833 ms，61 events，最终 tick 3；
- 50 角色：358.262 ms，171 events，最终 tick 3；
- 100 角色：1988.456 ms，321 events，最终 tick 3。

三档均只评估 96 个 opportunities，执行 3 ticks，无截断；报告正确暴露预算耗尽状态。耗时是单次环境观测，脚本明确 `timing_assertions=false`，不能解释为生产 SLA 或跨机器性能承诺。

## 明确后置

- World IDE、节点画布、创作者工作台与可视化 diff；
- 任意 Workflow DSL、自定义节点、公共 capability/内容生态；
- 完整《西游后传》地图、阵营、人物、长季内容与运营；
- 插画、漫画、配音、视频及其他多媒体管线；
- 更大规模的性能工程与生产部署承诺；
- 模型文学质量、内容吸引力、可理解性、真实用户留存和付费验证。

这些是下一阶段产品/生态目标，不影响 M0–M7 技术门禁完成；同样不得把它们描述成已经完成。
