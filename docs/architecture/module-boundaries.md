# 模块边界

本文描述当前物理模块与允许的依赖方向。目录职责、稳定入口和新增需求的放置规则见[项目结构与变更归属](project-structure.md)。

## 依赖方向

```text
World Package → Compiler → CompiledWorld / WorkflowIR / ExperienceContract
                                      ↓
Participation → Application → Runtime Kernel / Simulation
                                      ↓
                         Event Log → Projections
                                      ↓
                  Narrative Curator / Delivery
                                      ↓
                              PresentationStore

Contracts ← Adapters ← Bootstrap composition root
```

`engine/world` 不依赖 Runtime。Runtime 不依赖具体模型供应商、Renderer 或 UI。具体模型与磁盘存储只由 `engine/bootstrap` 组合。

## 模块契约

### World Package / Compiler

- 输入：目录世界包 revision、assets、capabilities 和四类 Workflow 文档。
- 输出：不可变 `CompiledWorld`、typed `WorkflowIR`、content hash、握手与诊断。
- `experience_profile` 编译为彼此隔离的 Runtime/Editorial 子契约；显式 profile
  与旧 presentation 配置冲突、未知 catalog ID 或跨包角色引用均 fail closed。
- Workflow 仅允许固定 genesis/evolution/intervention/presentation steps、顺序和 policy 字段。
- 禁止：调用模型补设定、读取 run、执行作者文本或把 Workflow 当任意 DSL。

### Runtime Workflow

- 输入：已编译 `WorkflowDefinition` 与 typed context。
- 输出：封闭 `STEP_HANDLERS` registry 中已注册 step 的执行结果及事件 provenance。
- 失败：未知 op、缺失 handler、没有对应 runtime operation。
- 禁止：动态导入作者代码、注册包内函数、执行任意表达式。

### Runtime / Resolver

- 输入：`CompiledWorld`、当前投影、seed、合法 opportunity 或 `ActionAttempt`。
- 输出：typed Event/Delta 或结构化拒绝。
- 同 Tick 候选基于同一快照，经 reservation 后由共享 Resolver 复核。
- 禁止：写呈现文本、让角色自述决定事实、让 Avatar 绕过 NPC 门禁。

### Entity Scene Runtime

- 输入：世界终局问题、角色志向与行事方式、地点/scene seed、当前实体投影、
  第一人称感知与这一手意图。终局问题和场景问题都不是这一回合的任务清单。
- 输出：一次性 `SCENE_INSTANTIATED`、重访/时序事件，或带通用组件补丁的
  `TURN_RESOLVED`。
- 地点是稳定地图节点；场景是地点下按 scene key 懒生成、可重访并持续演化的实体。
  一个地点可以有门槛场景和里间。每一处只生成这里看得见的一层。
- 调度按 think / address / act 加载对象。想和说不调用环境裁决。做只能改意图
  范围内、capability 允许的组件。物件只有一个持有人。完整角色的回应进入其后续回合。
- 离开当前地点的 `scene_transition` 必须是相邻通路，由运行时沿通路旅行并同步
  地图位置与 Presence。同一地点换里间才用 scene key。不能把离开写成原地迈步。
- `dramatic` 组件只保存阶段问题、压力、收束信号、进度和已提交结果。阶段问题是
  这一处的限度。环境生成器可提出压力来源，角色仍决定行动，裁决器只认已发生且
  满足收束信号的结果。`resolved` 是内部节拍，不是章节边界。
- 压力间隔、上限、决定阈值和收束模式来自已编译的通用 Runtime 契约；本模块
  不读取 `genre_id`、Voice、世界 ID 或角色 ID 来改变算法。
- 禁止：把自然动作还原成固定动作枚举、每次重访重生成场景、用正文代替状态补丁，
  让一个角色决定另一个完整角色的行动，或把终局条件展开成预写事件序列。

### Event Log / Projections

- Event Log 输入通过版本、world hash、pre-state hash 与 Delta 校验的事件，并原子追加。
- JSONL adapter 支持私有权限、锁、fsync、尾损坏隔离、加载、replay 与 fork。
- Projection 输出 state、位置、关系、Memory、Soul overlay 与 phase snapshot。
- 禁止：原地更新历史；让 Projection 成为第二事实源。

### Simulation Director

- 输入：作者定义的 incident 规则、当前 Tick、预算与合法效果。
- 输出：无事件，或 `INCIDENT_OCCURRED` / `INCIDENT_RESTED` typed Event。
- 允许：选择合法 author incident，并通过 Event Log 原子写入结构化 Delta。
- 禁止：预写角色台词/反应、绕过效果合法性、直接修改 Projection。

UserGate 与 Fate Intervention 属于同一 intervention Workflow 的独立操作，不与 incident 混为一类。

### Participation / Avatar

- 输入：严格 `AvatarPackage`、授权地点、用户选择或标准行动尝试。
- 输出：生命周期事件、Avatar opportunity、Resolver 事件或结构化拒绝。
- NPC 与 Avatar 共用地图、知识、资源、成本、ActionAttempt 和 Resolver。
- 禁止：调度离线 Avatar、把 Creator 全知写入 Avatar Memory。

### Narrative Curator / Delivery

- 输入：已提交事件、受众可见性、presentation policy 与只读来源视图。
- 输出：来源过滤、按内容收束的章节、typed NarrativePlan、带段落来源的
  Presentation 候选和用户剧情文档。
- 长篇发布使用内容分章器：读当前这一处和下一处开头，在真正离开处收束。
  子场景不算换地方，只有赶路不成章，同一条调度链不拆开。体验契约里的事件数
  和时间跨度字段仍然校验，但不拿来切章。
- 已有双方原话的章节装配已提交对话，不根据摘要另写一篇。其余材料仍可走四段
  文学管线。首次 `scene_instantiated` 的规格句不进入正文。
- presentation workflow 依次执行真实的 curate、plan、render、validate；
  render 内的 `editorial_pipeline` 由发展编辑、场景写作、行文编辑和事实
  连续性编辑四个固定 stage 组成，各槽位选择兼容宿主 Skill，各阶段只消费前一阶段 typed 输出。
- Delivery 只读取编译后的 Editorial 契约，不从世界名或题材猜测文风。
- Skill 从宿主 `SKILL.md` 资源加载；WorldVoice 从资源 manifest 加载，
  角色声音由世界包 typed register 提供。自由 Prompt、
  包内代码以及 Skill 对事实权限的扩张均不具备执行权限。
- 禁止：推进 Tick、调用 Resolver、创建世界事件或将文本回写为 Memory。

### PresentationStore

- 输入：通过事实校验的 Presentation、来源 id、audience cursor 与 render version。
- 输出：内存对象，或原子持久化的 `presentation-store.v1` JSON。
- 失败：schema/来源不一致、越界事实、磁盘写入失败；整体 fail closed。
- 禁止：修改 Event Log、Projection 或世界包。

### Contracts / Adapters / Bootstrap

- ports 定义 SceneGenerator、IntentPolicy、WorldAdjudicator、ActorPolicy、
  NarrativeRenderer、TextModel、RunStorage 与 PresentationStorage。
- 默认组合使用确定性 Actor 与 Renderer。
- 模型 Actor/Renderer 只有显式配置时启用；磁盘 run/presentation 只有显式路径时启用。
- adapter 不能扩大 Runtime capability，也不能绕过 Delivery 事实校验。

## 跨模块不变量

1. 只有 Event Log 成功追加能改变运行事实。
2. 世界包修改产生新 revision；历史以 restart/fork 关联。
3. 四类 Workflow 由封闭 typed registry 执行，不是任意 DSL。
4. NPC 与 Avatar 共用行动和结算路径。
5. Simulation Director 只能写作者授权且合法的 incident Delta。
6. Narrative Curator、Renderer 和 PresentationStore 对 Runtime 只读。
7. Memory 摘要不能授予来源事件之外的新知识。
8. 模型默认关闭；显式启用后仍受 typed 输入、回退与事实校验约束。
9. 场景首次生成后以实体与事件为准；重访不得静默重新随机。
10. 文学层只能策展已提交场景/回合事实，不能修补缺失的持有或空间迁移。
11. 文学阶段可重写表达但不能改变段落 provenance；最终发布门禁属于 Delivery。
12. Runtime 与 Narrative 分别只读体验契约的运行和编辑子结构，不得跨层解释
    `genre_id`。

## 边界验收

- 替换世界包无需修改标准执行器，执行器不含世界专名。
- 删除 Projection 后可从 `CompiledWorld + Event Log` 重建同一 state。
- 缺 Workflow handler、非法 Delta 与损坏持久化数据均 fail closed。
- 对等 NPC/Avatar 非法行动得到同类拒绝。
- PresentationStore 写入失败或模型越界不撤销世界事件。
