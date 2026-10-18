# 生成式世界引擎：M0–M7 路线图

本文采用唯一编号：M0 边界、M1 最小 Runtime、M2 自主相遇、M3 叙事、M4 长期、M5 Avatar、M6 迁移、M7 门禁。

本文是技术重建阶段的历史路线图。产品质量迭代与最新优先级见[当前进度与后续重点](status/current-status.md)，开发方法见[Workflow 与 Runtime 协同迭代流程](development/iteration-process.md)。

## 当前结论

技术 M0–M7 均已完成并有自动化证据。这里的“完成”只表示本仓库定义的架构纵切与门禁通过；不把 World IDE、Workflow 生态、完整《西游后传》、多媒体内容、文学质量或真实用户留存计入技术完成。

## M0：边界 — 完成

产物：

- World Package → `CompiledWorld` → Event Log → Projection → PresentationStore 权威链；
- Runtime、Resolver、参与、叙事与适配器的依赖边界；
- 模型作为显式 adapter，默认确定性；
- Simulation Director 可投放 author incident 并写 Event Log；Narrative Curator 只读。

退出证据：导入边界测试、结构化诊断、不可变 revision/fork 约束。

## M1：最小 Runtime — 完成

产物：

- typed Event、Delta、WorldState、append-only Event Log；
- Tick、环境推进、共享 Resolver、原子校验；
- JSONL run 持久化、replay、fork、损坏尾恢复与 fail-closed 加载。

退出证据：相同 world/seed/log 重建相同 state 和 history hash；非法 Delta 不半提交；磁盘文件 `0600`。

## M2：自主相遇 — 完成

产物：

- 地点 affordance、通路、资源、感知与共址门禁；
- Actor opportunity、同快照 reservation、冲突拒绝与重规划；
- 移动、采集、对话、观察、等待及地点公开历史；
- author incident 的预算化确定性选择与事件写入。

退出证据：两个世界包各 8 seed 全部通过，均得到 8/8 唯一历史；资源量和通路耗时扰动会改变结构化事件链。

## M3：叙事 — 完成

产物：

- 只读 Narrative Curator / source filtering / digest；
- 确定性 Renderer、显式模型 Renderer adapter、事实校验与回退；
- 受众隔离的 Episode、Presentation、重渲染与独立持久化 `PresentationStore`。

退出证据：越界模型文本回退到来源化摘要；Avatar/omniscient 可见性隔离；清空可重建；呈现写入失败不改变 Runtime。

## M4：长期 — 完成

产物：

- action/opportunity/incident/memory/catch-up 预算；
- 热区详细 Tick 与冷区粗粒度摘要；
- 长期短计划、去重复、Memory consolidation、Soul overlay；
- typed phase predicates/snapshots、可观测 TickReport 与 causal trace。

退出证据：20-tick 长期行为实验通过；详细 2 tick + 冷区 8 tick 可 replay；10/50/100 角色工作量受预算约束。

## M5：Avatar — 完成

产物：

- 严格 `AvatarPackage`、授权入口、join/leave/rejoin 生命周期；
- NPC/Avatar 共用 opportunity、ActionAttempt 与 Resolver；
- 离线 `pause`、私有 Memory、受众感知；
- 独立 UserGate 与 Fate Intervention，支持条件、冷却、成本、原子失败、fork 和 explain。

退出证据：对等非法移动产生同类 Resolver 拒绝；Avatar 缺席不被调度；Fate 与 Gate 可 replay 且分支历史不同。

## M6：迁移 — 完成

产物：

- `echo-quay` 与 `black-pine-ridge` 均迁移到目录世界包；
- assets/workflows 命名空间、capability handshake 与稳定 content hash；
- genesis/evolution/intervention/presentation 四个 typed Workflow；
- 四条 Workflow 由封闭 step registry 执行，未知 op、乱序和缺 handler fail closed；
- ports/adapters/bootstrap 组合根，运行与呈现磁盘 adapter，显式模型 adapter。

退出证据：两个包无需世界专名执行器即可编译运行；四类 Workflow 均通过实际 dispatch/provenance 测试。当前并非任意 DSL 或 capability 生态。

## M7：门禁 — 完成

产物：

- 编译/probe 安全、8-seed replay、扰动、持久化恢复；
- 冷热、预算、Fate/Avatar、Presentation、模型回退；
- 架构 import boundary、CLI 与规模 benchmark；
- 最终证据报告。

退出证据：全量自动化测试通过；benchmark 只记录规模与预算行为，不设置不可靠的毫秒阈值。

## 持续门禁

- 未知 capability、字段、Workflow op、路径逃逸和越界 effect 必须结构化拒绝。
- Runtime 只消费 `CompiledWorld`；编译器不调用模型补全。
- Event Log 追加是改变运行事实的唯一方式。
- 同 seed 可 replay；不同 seed 可分支；资源/通路扰动可观察。
- NPC 与 Avatar 使用同一行动和结算规则。
- Simulation Director 的 incident 必须来自作者规则并通过合法 Delta；不得指定角色台词或反应。
- Narrative Curator、Renderer 与 PresentationStore 不得修改 Runtime。
- 模型必须显式启用；模型失败或越界不得破坏确定性事实边界。
- 标准执行器不得包含具体世界专名。

## 明确后置

- World IDE、节点画布、导演工作台和可视化 diff；
- 任意 Workflow DSL、用户自定义节点、市场与公共生态；
- 完整《西游后传》地图、阵营、长季内容和运营工具；
- 插画、漫画、配音、视频及地图画面；
- 大规模生产性能承诺与后台无限生成；
- 文学质量、内容吸引力、可理解性和真实用户留存验证。

后置项属于下一阶段产品与生态工作，不得回写成 M0–M7 技术未完成，也不得冒充已完成。详细证据见[最终报告](experiments/m0-m7-final-report.md)。
