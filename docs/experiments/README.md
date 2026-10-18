# 自主世界实验记录

实验同时服务两个循环：Workflow 外环验证机制是否值得保留，Runtime 内环验证一次运行是否符合事实与结算契约。一次实验只验证一个主要假设。

本文件模板适合验证单项机制与契约。需要评估多个机制组合后的行为、叙事和追更质量时，使用[世界整体质量评审模板](quality-review-template.md)，评分口径见[设计理念与整体质量模型](../product/design-principles-and-quality.md)。

当前质量纵切见[雨夜破庙单场景文学纵切](single-scene-literary-vertical-v1.md)；
冻结素材与可执行编辑阶段见[文学 Skill 管线 v1](literary-skill-pipeline-v1.md)；
机制分层诊断与循环结果见[文学质量循环 v1](literary-quality-loop-v1.md)；
长篇自主探索、离场寻路与 20 章交付证据见
[长篇自主世界验证 v1](longform-autonomous-world-v1.md)；
按需调度与章节装配见
[调度驱动章节 v1](dispatch-driven-chapters-v1.md)；
线索分层与离场见
[2026-10-18 征供链](2026-10-18-dispersed-levy-chain.md)；
前序管线实验见[场景写作 Skill 与世界声音 v2](narrative-scene-craft-v2.md)和
[叙事策展与世界文风 v1](narrative-curation-literary-skills-v1.md)。

## 使用规则

1. 先复制下方模板，文件名使用 `YYYY-MM-DD-短名称.md`。
2. 固定世界包 revision、Execution IR hash、种子、Workflow/模型版本和命令。
3. 至少记录一次成功路径和一次预期失败路径。
4. 结论必须引用事件 id、诊断或可重复输出，不能只评价文本“好不好”。
5. 不满足假设时先删减或修改实验层规则，不直接扩张 Runtime。

## Capability 三次原则

候选能力每次有效实验记一条证据。只有同时满足以下条件才进入晋升评审：

- 至少三个独立实验轮次；
- 至少两个不同世界包；
- 每次都具有稳定输入、输出、失败方式和确定性测试；
- 实现不含世界专名，且无法更合理地留在 Workflow 或世界包。

安全、数据完整性和 replay 正确性修复不受三次门槛限制，但仍要记录回归证据。

## 实验模板

```markdown
# EXP-YYYYMMDD-NNN：标题

## 元数据

- 状态：planned | running | passed | failed | inconclusive
- 负责人：
- 日期：
- 关联里程碑：M0–M7
- 世界包 / revision：
- Execution IR hash：
- Workflow 版本：
- Runtime 版本/commit：
- 模型与参数（如使用）：
- RNG seed：
- 复现命令：

## 单一假设

如果【机制/Workflow 变化】，那么【可观察结果】；否则本实验失败。

## 范围

- 包含：
- 不包含：
- 固定不变项：

## 输入

- 初始状态：
- 角色与 Avatar 可见知识：
- Clock / 义务 / 地点 /资源：
- 用户行动尝试（如有）：
- 运行预算与停止条件：

## 预期输出

- 必须提交的事件类型：
- 不得出现的事件或信息：
- 应变化的投影：
- 可选呈现产物（不作为事实证据）：

## 预期失败路径

- 触发条件：
- 错误码/诊断：
- Event Log 应保持：
- Projection 应保持：

## 验收

- [ ] 相同 IR、日志和种子可 replay
- [ ] 事件因果可追溯
- [ ] NPC 与 Avatar 使用相同规则（相关时）
- [ ] 无知识泄露或角色越权
- [ ] 模拟失败不被呈现补写
- [ ] PresentationStore 变化不影响世界状态（相关时）
- [ ] 达到停止条件，没有无限生成

## 结果证据

- 事件 id / 日志片段：
- 前后投影差异：
- 失败诊断：
- 呈现校验：
- 重复运行差异：

## 结论

- 判定：passed | failed | inconclusive
- 保留/删除/修改的规则：
- 对 Workflow 外环的下一步：
- 对 Runtime 内环的下一步：

## Capability 证据（可选）

- 候选 capability：
- 这是第几次独立证据：1 / 2 / 3+
- 已覆盖世界包：
- 稳定输入/输出/失败：
- 为何不能留在 Workflow 或世界包：
- 晋升决定：继续实验 | 提交评审 | 不晋升
```

## M0 验收

- 新实验可仅靠模板复现环境和判断结果。
- 失败实验同样保留，不因文本质量差而删除证据。
- capability 晋升记录能明确数出三次证据及两个世界包。
- 呈现结果与 Event Log 证据分栏记录。
