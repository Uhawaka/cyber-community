# 自主世界产品规格

## 目标与当前边界

标准 Runtime 加载目录世界包后，在没有用户逐场指挥的情况下产生可回放、可解释、有成本的状态变化；用户可以观察或以 Avatar 介入；叙事层只整理已经提交的历史。

技术 M0–M7 已完成。当前交付是可验证的引擎纵切，不是完整内容产品，也不承诺文学质量、长期吸引力或真实用户留存。

## 两个迭代环

```text
Workflow 外环：
作者资产/策略 → 编译 → probe → 对比事件与失败 → 新 revision / fork

Runtime 内环（`scene_turns`）：
Projection → 第一人称感知 → think / address / act
→ 只有 act 进入环境裁决 → Event Log → 按内容分章

兼容内环（`actor_windows`）：
Projection → opportunity → reservation → Resolver → Event Log
```

外环中的 Workflow 是四条 typed、封闭执行链，不是任意 DSL。`genesis`、`evolution`、`intervention`、`presentation` 只能使用各自固定 step registry、顺序与 policy schema。黑松岭走 `scene_turns`，回声码头仍走 `actor_windows`。两条路径都不能把世界名或角色名写进执行分支。

## 核心契约

### 世界与历史

- 世界包是作者源；`CompiledWorld` 是确定性、不可变运行输入。
- Event Log 是 run 的动态事实源。
- State、位置、关系、Memory、Soul overlay 与 phase snapshot 可重建。
- 世界包修改形成 revision；既有历史 restart 或从事件边界 fork。
- Run 可写入锁定 JSONL，并在进程重启后 replay；尾损坏可显式隔离恢复，中间损坏 fail closed。

### Simulation Director

Simulation Director 可从作者定义的 incident 规则中选择到期、预算内且效果合法的候选，并将 typed incident Event/Delta 原子追加到 Event Log。它不能指定角色台词、角色反应或绕过 Resolver/Event Log 直接改状态。

UserGate 和 Fate Intervention 是独立参与机制，不等同于 incident。

### Narrative Curator

Narrative Curator 只读已提交历史及受众可见来源，过滤内部调度事件，并按内容和
离开处分章。双方都有原话的章节装配已提交对话。typed NarrativePlan、宿主多遍 LiterarySkill 和项目 WorldVoice
分别决定事实组织、写作方法与世界声音；世界包只能选择已注册 Skill/Voice 和
typed 文风档案。Narrative Delivery、
Renderer 与 PresentationStore 不能推进 Tick、调用 Resolver 或把文本写回世界事实。

### Avatar

- NPC 与 Avatar 共用 opportunity、行动 schema、地图/知识/资源/成本门禁和 Resolver。
- Avatar 只在意图来源上不同；离线 `pause` 时不能被调度器代演。
- AvatarPackage 不能携带工具、网络权限或预制 Delta。
- join/leave/rejoin、UserGate 和 Fate 均形成可 replay、可 fork 的 typed events。

### 模型

默认场景生成、意图、裁决与 Renderer 完全确定性。模型能力位于显式 adapters；只有组合根收到模型配置或 `TextModel` 才启用。角色提示把志向、行事方式和眼前这一手分开。模型 Renderer 仍须通过事实校验。兼容路径上的模型 Actor 仍受 typed opportunity 限制并可回退。

模型技术接通不等于文学质量或用户留存得到验证。

## M0–M7

- **M0 边界：完成。** 权威链、依赖方向、导演职责与 adapter 边界固定。
- **M1 最小 Runtime：完成。** typed Event/Delta、Tick、Event Log、replay、fork、持久化恢复。
- **M2 自主相遇：完成。** 地点/通路/资源、opportunity、reservation、共享 Resolver、incident。
- **M3 叙事：完成。** 只读来源、digest、事实校验、确定性/模型 Renderer、持久化 PresentationStore。
- **M4 长期：完成。** 预算、catch-up、冷热模拟、计划去重复、Memory/Soul、phase snapshot、可观测性。
- **M5 Avatar：完成。** 严格包、授权入口、同规则行动、离线 pause、生命周期、Gate/Fate。
- **M6 迁移：完成。** 两个目录包、四 typed Workflow、ports/adapters/bootstrap 与 CLI。
- **M7 门禁：完成。** 8-seed、扰动、安全、恢复、冷热、Fate/Avatar、Presentation、benchmark 与全量回归。

详细退出证据见[最终报告](../experiments/m0-m7-final-report.md)。

## Capability 晋升

新机制默认留在世界数据、封闭 Workflow policy 或实验层。要晋升通用 capability，须有至少三个独立实验轮次、覆盖两个世界包、稳定输入/输出/失败方式、确定性测试，且实现不含世界专名。安全、完整性与 replay 修复可直接进入内核，但仍须有回归。

## 明确后置

World IDE、任意 Workflow DSL、自定义节点生态、完整《西游后传》、多媒体生产、公共市场、文学质量评估和真实用户留存实验均不属于已完成技术 M0–M7。
