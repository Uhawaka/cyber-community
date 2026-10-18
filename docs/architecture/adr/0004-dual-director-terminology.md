# ADR-0004：采用双导演术语

- 状态：Superseded（术语已由现行架构取代）
- 日期：2026-10-17

## 取代说明

本 ADR 保留为历史设计记录，但“双导演”术语不再用于当前实现：

- Runtime 侧使用 **Simulation Director**，仅指作者授权的结构化 incident 选择；角色机会、reservation 和 Resolver 分别承担规划与结算职责。
- 叙事侧使用 **Narrative Curator**，只从已提交历史中选择来源、焦点和交付窗口。
- 当前没有 Scene Contract、Story Promise 或可创建事实的 Narrative Director。

现行权威口径见 `docs/design.md`、`docs/architecture/module-boundaries.md` 和 `docs/product/narrative-delivery-spec.md`。下文仅描述被取代的目标架构，不应作为新增代码的命名依据。

## 决策

统一使用两个互不重叠的名称：

- **Simulation Director / 模拟导演**：决定“接下来优先结算哪些已有可能性”。
- **Narrative Director / 叙事导演**：决定“已发生或正在形成的变化如何被组织为值得观看的场景”。

模拟导演输出调度候选、优先级和预算；叙事导演输出视角、Scene Contract、来源范围和验收维度。二者都不能直接提交事实、替角色决定行动或声明结果。

## 理由

“导演”同时指运行调度和剧情交付时，容易让场景规划反向制造世界事件。双术语明确 Runtime 内环中的职责顺序。

## 输入、输出与失败

- 模拟导演输入目标、Clock、义务、计划和预算；无合法候选或阶段关闭时停止。
- 叙事导演输入已提交历史、叙事宪法、Story Promise 和可见投影；无事实支持时拒绝合同。
- 两者引用未知角色、压力、秘密或事件时均失败，不允许自动发明。

## 后果

- 现有同时承担两类责任的组件应在后续里程碑迁移；本 ADR 不宣称拆分已完成。
- Resolver 仍决定后果，Event Log 仍决定事实，Renderer 仍只负责表达。
- Director 配置可以位于 Workflow，但权限不能随模板扩大。

## 验收

1. 每个 director 接口的输出都不含状态 Delta 或既成结果。
2. 关闭 Narrative Director 后模拟仍能推进。
3. 关闭 Simulation Director 后仍能呈现指定的已提交事件。
