# 项目结构与变更归属

本文说明代码、世界内容、测试和文档各自放在哪里，以及新增需求应由哪个模块承担。具体依赖规则见[模块边界](module-boundaries.md)，架构决策原因见 `docs/architecture/adr/`。

## 1. 顶层结构

```text
cyber-community/
├── engine/                    通用引擎代码
│   ├── application/           用例编排
│   ├── bootstrap/             唯一组合根
│   ├── catalogs/              宿主资源 manifest 的共享只读索引
│   ├── contracts/             跨边界 ports
│   ├── adapters/              模型与磁盘适配器
│   ├── world/                 世界包读取、校验与编译
│   ├── runtime/               世界事实与模拟
│   ├── participation/         Avatar 和用户介入
│   └── narrative/             只读叙事交付
├── worlds/                    可安装、编译和运行的世界包
├── tests/                     契约、行为、失败路径和架构测试
├── scripts/                   面向开发者的 CLI 与 benchmark
├── docs/                      设计蓝图、架构、规格、实验和状态
├── outputs/                   本地模拟与评估产物，不进入版本库
└── README.md                  仓库入口和最短运行路径
```

## 2. 引擎模块

### `engine/world`

负责把不可信的作者目录编译为确定性、不可变的 `CompiledWorld`。

- 应放：schema、实体定义、引用校验、capability 握手、content hash、Workflow IR
  与 ExperienceProfile 编译。
- `experience_catalog.py` 只保存去专名化的通用 runtime mode 和 editorial bundle；
  `package_experience*.py` 负责合并、跨层冲突和完整性诊断。
- 不应放：Tick、角色决策、叙事渲染、模型补全、用户会话。
- 公共入口：`engine.world`。

### `engine/runtime/kernel`

负责世界事实的最小内核。

- 应放：typed Event/Delta、Event Log、状态归约、生命周期、replay、持久化协议。
- 不应放：具体角色策略、文学文本、世界题材规则。
- 变化要求：任何事件 schema 变化都必须说明兼容性、归约语义和 replay 测试。

### `engine/runtime/simulation`

负责时间推进、候选规划、冲突预留、结算和冷热模拟。

- 应放：Tick phases、Planner、Reservation、Resolver、预算、catch-up、观测报告。
- 不应放：具体世界角色名、预写场景、Presentation。
- 共享事实：NPC 与 Avatar 最终都通过这里的行动约束和 Resolver。

### `engine/runtime/character`

负责角色长期状态与决策输入。

- 应放：Soul/Memory contracts、记忆巩固、角色 policy、长期演化服务。
- 不应放：模型供应商客户端、正文台词模板、世界专属人格代码。
- 约束：作者 Soul 不可变；运行中变化进入有来源、版本化的 overlay。

### `engine/runtime/space`

负责地点、机会与地点历史。

- 应放：affordance、共址与可达性机会、公开地点历史。
- 不应放：地图编辑 UI、渲染地图、跨边界直接修改状态。

### `engine/runtime/scene`

负责地点内部的实体场景运行。

- `generation.py`：根据世界/地点/scene seed 首次懒渲染并提交实体；
- `lifecycle.py`：场景进入、重访与本地时序；
- `perception.py`：第一人称投影。场景问题是这一处的限度；本地人说过这一层之后，投影要求离开而不是再问一遍；
- `dispatch.py`：按 think / address / act 加载对象。想和说不请环境；离开且这一层已有别人回答时，补上相邻通路；
- `turns.py`：提交裁决结果、交互队列和场景共享历史。同一人重复已做的决定记为无进展；
- `capabilities.py`：组件能力包，不是动作枚举；
- `npc.py`：轻量环境 NPC。只说本地见闻，不编别人的经历，说过的事实不再当新内容；
- `labels.py`：读者可见的人名和地名，正文不暴露实体编号；
- `egress.py`：收束后沿作者通路选择下一处；
- `executor.py`：`scene_turns` 的有界回合。同一时刻只跟一处尚未落地的场景。

不应放：文学正文、世界专名分支、物理路径微操作、模型供应商客户端。

### `engine/runtime/autonomous_director.py`

负责作者授权的 incident、UserGate 与 Fate 的运行时入口。

- Incident 是世界自主机制；
- UserGate 是阻塞式用户选择；
- Fate 是用户主动调用的结构化介入；
- 三者不能共享模糊的“导演可以改任何事”权限。

### `engine/runtime/workflow.py`

负责四类 Workflow 的封闭 step registry 与 dispatch。

- 新增 step 前必须有稳定输入、输出和失败语义；
- 包内不得注册 Python 函数或动态导入代码；
- Workflow 编译与执行需分别测试。

### `engine/participation`

负责 AvatarPackage、生命周期、授权和用户意图入口。

- 只定义“谁可以以什么身份提交意图”；
- 不复制 Runtime 行动规则，不建立 Avatar 特权结算路径。

### `engine/narrative`

负责从只读历史选择来源、形成 digest、渲染、校验和持久化 Presentation。

- `source.py`：受众可见来源。没有公开决定的思考、重复决定和场景规格句不进正文；
- `curation.py`：读者事件过滤；
- `division.py`：按内容和离开处分章，不用事件条数或时间跨度配额；
- `exchange.py`：双方都有原话时，直接装配已提交对话；
- `digest.py`：结构化事实摘要；
- `planning.py`：typed NarrativePlan 与文风档案；
- `skill_library/*/SKILL.md`：宿主版本化发展编辑、场景写作、行文编辑和事实
  连续性编辑方法；
- `voice_library/*.json`：去专名化 WorldVoice、lexicon、标题与质量门禁；
- `skills.py`：Skill 与 Voice 资源加载；
- `delivery.py`：Episode/Presentation 交付编排；
- `rendering.py`：场景化确定性回退、事实校验与行文反模式门禁；
- `artifacts.py`：从已校验 Presentation 导出用户可读剧情文档；
- `store.py` / `persistence.py`：独立呈现状态。

它不能推进 Tick、创建世界事件或把正文写回 Memory。

### `engine/application`

负责把多个领域模块组合成可调用用例。

- 应放：创建/恢复 run、运行 Tick、参与、观察、包验证、故事发布。
- `literary_iteration.py`：复制冻结 Presentation/Digest 后独立重渲染，不加载
  或推进世界。
- 不应放：领域规则、Event 归约、供应商 SDK。

### `engine/contracts`

只存放真正跨模块、可替换实现所需的 ports 和不可变边界类型，例如
ActorPolicy、NarrativeRenderer、TextModel、存储端口及 Experience 子契约。
不要把所有 dataclass 都放入 contracts；模块内部类型应留在所有者模块。

### `engine/adapters`

实现具体外部能力，例如 OpenAI-compatible 模型、JSONL run 和 JSON Presentation 存储。Adapter 只能实现 port，不能扩大 Runtime capability 或绕过事实校验。

- `model_intent.py`：角色这一手的提示。志向、行事方式和眼前这一手分开填写；
- `model_scene_generator.py`：首次场景生成。NPC 事实只能写这一处 premise 里看得见的一层；
- `model_adjudicator.py`：环境裁决。离开只能落到 `place_choices.py` 给出的相邻地点；
- `place_choices.py`：当前位置的相邻通路和同一地点的里间；
- `model_literary_stages.py`：逐 Skill 模型调用与 typed JSON 解码；
- `literary_pipeline_renderer.py`：阶段编排、定向修订和 trace；
- `model_narrative_material.py`：把 Digest 收窄为写作可见事实。

### `engine/bootstrap`

唯一组合根。负责选择确定性或模型实现、内存或磁盘存储，并构造应用。业务模块不得自行读取供应商配置或实例化 adapter。

## 3. 非代码目录

### `worlds`

每个子目录是独立 revision 的世界包。角色拥有自己的 `profile.yaml`、
`soul.yaml` 和 `memory.seed.json`；地图、资源和四类 Workflow 位于包级目录。
`world.yaml.experience_profile` 把该世界的通用运行模式、编辑 bundle、typed
文风和角色声音配套声明；世界专名不得搬进引擎 catalog。

世界特有设定优先留在这里。只有跨至少两个世界、经过重复实验且具备稳定失败语义的机制，才考虑进入引擎。

### `tests`

测试按可观察契约命名，而非机械镜像源码目录：

- `tests/architecture/`：禁止依赖和组合根边界；
- `test_world_package_*` / `test_package_*`：作者输入与编译安全；
- `test_autonomous_*`：运行、持久化、参与和交付主路径；
- 其余文件：具体机制的成功与失败路径。

每个通用能力至少应有：正常路径、非法输入、原子失败、replay 或跨世界证据中适用的部分。

### `docs`

- `product/`：目标体验、设计原则和产品规格；
- `architecture/`：当前结构、边界和 ADR；
- `contracts/`：跨领域数据语义；
- `authoring/`：世界包作者格式；
- `experiments/`：可复现实验与技术证据；
- `status/`：当前进度、已知缺口和下一阶段。

### `outputs`

存放一次运行的事件、摘要、Presentation 和人工评估。它用于诊断，不是回归测试或世界包的一部分。值得长期保留的结论应提炼到 `docs/experiments/`，稳定基线应转成测试夹具，而不是依赖某个本地输出文件。

## 4. 变更归属判断

新增需求按以下顺序判断：

1. 只是某个世界的设定、初始数据或参数：放入对应世界包。
2. 是四类 Workflow 已有 policy 可表达的差异：修改 Workflow 与编译校验。
3. 是跨世界重复出现、需要统一结算的规则：先做实验，满足晋升条件后放入 Runtime。
4. 是用户身份、授权或意图入口：放入 Participation，结算仍复用 Runtime。
5. 是“发生什么”的事实变化：必须经过 Resolver 和 Event Log。
6. 是“怎样讲述已发生事实”：放入 Narrative。
7. 是模型、数据库或文件系统实现：定义 port 后放入 Adapters，并由 Bootstrap 装配。
8. 只是跨模块编排：放入 Application，不在此处创造新领域规则。

## 5. 禁止的捷径

- 在执行器中按 `package_id`、角色名或地点名分支。
- 在 Renderer 中触发行动、关系或资源变化。
- 在世界包中嵌入可执行 Python、表达式求值或网络请求。
- 为 Avatar 复制一套比 NPC 更宽松的 Resolver。
- 让 Projection 或 Memory 变成第二套不可回放事实。
- 从 Application 直接修改 Runtime 内部字段。
- 为一次实验立即增加公共 capability。
- 把模型 prompt 当作唯一规格，而没有 typed 输入、输出和失败路径。

## 6. 稳定入口与内部实现

外部调用应优先使用：

- `engine.world`：编译与 package contracts；
- `engine.runtime`：创建、推进、恢复和解释 run；
- `engine.application`：产品用例；
- `engine.narrative`：交付 contracts；
- `engine.bootstrap.build_application`：完整装配。

子模块路径默认是内部实现细节。若新调用方必须直接依赖子模块，应先确认公共入口是否缺少真正稳定的契约，避免用重导出掩盖错误的模块所有权。
