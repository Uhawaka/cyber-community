# 世界包验证规格追踪矩阵

| 规格 | 实现 | 验证证据 |
|---|---|---|
| 两个世界包声明固定 seed、tick 预算和性质 | `worlds/*/tests/invariants.yaml`、`probes.yaml` | `test_package_validation_runs_eight_isolated_replayable_seeds` |
| compile-first、独立 probe、结构化逐 seed 报告 | `engine/application/package_validation.py` | `test_package_probe.py`、CLI validate 输出 |
| probe 不成为玩家 run | probe 使用无持久化路径的内存 `AutonomousRun` | probe 前后世界包文件快照一致 |
| 至少 8 seed；replay、知识、地图、资源、共址约束 | `validate_package` 的七项 seed checks | 两个包各 8 seed 全通过 |
| 历史 hash 多样性 | `minimum_unique_history_hashes` 门禁 | 两个包均为 8 个唯一 hash |
| 资源/通路规则扰动改变结构化事件链 | 编译 IR 与 runtime affordance/resolver | `test_resource_and_passage_perturbations_change_structured_event_chain` |
| 路径穿越与 symlink 逃逸 fail closed | `_safe_ref`、`_read_json` 包根校验 | `test_package_security.py` |
| 作者文本大小、深度、实体数量限制 | `package_compiler` 的 `MAX_*` 限制与结构化诊断 | 超大、过深、memory 上限测试 |
| 未知字段和 schema 外 effect/delta 被拒绝 | 文档、实体、规则、effect 白名单 | unknown/effect 安全测试 |
| 工具、路径、网络提示仅是文本 | 编译器只做 JSON 解析/规范化，不调用模型或能力适配器 | inert author text 测试 |
| `engine.world` 不依赖 runtime | probe 编排位于 `engine.application` | `tests/architecture/test_import_boundaries.py` |

实验结论见 [世界包 probe 与安全门禁实验](../../outputs/experiments/package-probe-security-v1.md)。
