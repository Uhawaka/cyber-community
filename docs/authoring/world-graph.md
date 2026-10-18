# 目录世界包作者格式

目录世界包是当前唯一支持的作者格式：

```text
目录世界包
→ manifest capability 握手
→ schema、引用与禁用字段检查
→ 确定性编译
→ CompiledWorld
→ Autonomous Runtime Tick
```

Runtime 只消费不可变 `CompiledWorld`，不直接读取作者文件。编译器不调用模型补齐缺失设定；未知 capability、缺文件、非法引用或不支持字段都会产生结构化诊断。

当前格式是 `world-package/v1alpha2`；不兼容 `v1alpha1`。

## 目录结构

以 `worlds/echo-quay/` 为参考：

```text
my-world/
├── manifest.yaml
├── world.yaml
├── locations.yaml
├── passages.yaml
├── resources.yaml
├── characters/
    └── <character-id>/
        ├── profile.yaml
        ├── soul.yaml
│       └── memory.seed.json
└── workflows/
    ├── genesis.yaml
    ├── evolution.yaml
    ├── intervention.yaml
    └── presentation.yaml
```

当前 `.yaml` 文件使用 JSON-compatible YAML，必须可由 JSON 解析器读取；不要使用 YAML 专属语法、锚点或自定义 tag。

## Manifest 与 capability

```json
{
  "schema_version": "world-package/v1alpha2",
  "package_id": "my-world",
  "revision": 1,
  "capabilities": [
    "world.core.v1",
    "world.characters.v1",
    "world.memory-seed.v1",
    "world.resources.v1",
    "world.topology.v1",
    "world.fate-interventions.v1"
  ],
  "assets": {
    "world": "world.yaml",
    "locations": "locations.yaml",
    "characters": "characters",
    "resources": "resources.yaml",
    "passages": "passages.yaml"
  },
  "workflows": {
    "genesis": "workflows/genesis.yaml",
    "evolution": "workflows/evolution.yaml",
    "intervention": "workflows/intervention.yaml",
    "presentation": "workflows/presentation.yaml"
  }
}
```

capability 是包与宿主之间的显式握手，不是题材标签。宿主不认识的 capability 会得到 `UNKNOWN_CAPABILITY`，编译结果不可运行。

## 受限工作流

四类 workflow 都包含 `schema_version`、`kind`、`steps`、`policy`；编译后
`WorkflowDefinition` 另带确定性的 `content_hash`。工作流不是任意 DSL：
步骤和策略只能来自宿主注册表，未知项一律拒绝。

- `genesis`：按固定顺序装载五类资产。
- `evolution`：固定执行 environment update、incident scheduler、`scene_turns`
  或兼容的 `actor_windows`、scheme progress、memory consolidation、phase
  check，并定义需求衰减、各项预算、catch-up 和 hot/cold 范围。
- `intervention`：声明 Avatar 离线策略以及 incident、UserGate、Fate 权限。
- `presentation`：使用 `world-workflow/v1alpha3`，固定执行
  source filter、curate、plan、render、validate、publish，并声明交付阈值、
  renderer 和默认 audience。其余三类仍使用
  `world-workflow/v1alpha1`。

显式世界应在 `world.yaml` 用 `experience_profile/v1` 配套声明运行与编辑体验：

```json
{
  "experience_profile": {
    "schema_version": "experience-profile/v1",
    "genre_id": "mystery",
    "runtime": {"mode_id": "scene-pressure-v1"},
    "editorial": {
      "bundle_id": "restrained-mystery-v1",
      "style_overrides": {
        "point_of_view": "observer",
        "imagery_domains": ["潮声", "灯影"],
        "forbidden_phrases": ["显而易见"]
      },
      "episode_overrides": {
        "max_events": 10,
        "max_world_time_span": 6,
        "min_narrative_events": 2,
        "max_repeated_action": 1,
        "min_arc_events": 4
      },
      "character_voice_registers": {
        "character-id": {
          "first_attentions": ["首先注意什么"],
          "diction": "词汇边界",
          "syntax": "句法习惯",
          "withheld": ["不会主动说出的信息"]
        }
      }
    }
  }
}
```

bundle 提供完整默认 pipeline、Voice、style 与 Episode 策略，override 只接受
既有 typed 字段。`episode_overrides` 仍须合法，但长篇发布接上内容分章器后，
不用 `max_events` 或 `max_world_time_span` 切章。编辑 stage 图固定为发展编辑、场景写作、行文编辑和事实连续性，
但每个槽位可选择 stage 兼容的宿主 `SKILL.md`。Skill/Voice 均由宿主 manifest
注册；世界包不能提供自由 Prompt、Python 代码或动态 Skill。意象域只影响来源
事实的取舍，不授权 Renderer 虚构环境细节。旧包可暂时从 presentation policy
合成 legacy contract；显式 profile 与旧字段双写不一致会被拒绝。

## 作者文件

- `world.yaml`：世界 id、标题、前提、ExperienceProfile、终局问题、规则和元数据。
- `locations.yaml`：具有唯一 id 的地图地点，以及可选的高层 `scene_seeds`。
- `passages.yaml`：有方向的通路、起终点和正数耗时。
- `resources.yaml`：资源位置、数量和属性。
- `characters/<id>/profile.yaml`：身份、位置、目标、动机、技能和初始需求。
- `characters/<id>/soul.yaml`：相对稳定的价值、气质和偏好。
- `characters/<id>/memory.seed.json`：初始 Memory 作者种子，不是已发生的 Event Log。

Memory seed 可用 `visibility: "private"` 标记不可主动披露的经历。角色决策只能
从公开的 `observation` / `experience` 生成 `information_ids`；私有经历、Soul
belief 和 secret 仍可影响角色，但不会被对话模板自动说出。

所有引用必须指向已存在的实体。修改运行语义必须增加 package revision。

地点必须显式声明 `capacity`、`access_tags`、`allowed_roles`、`danger`、
`metadata`，以及 `affordances` 中的 `observe/rest/gather/social` 四个布尔开关。
未开启的能力不会成为候选行动。通路 `properties` 可声明
`required_access_tags`、`allowed_roles`、`required_skills`；资源也可声明
`required_skills`，且 `owner_id`、`container_id` 必须与 `location_id`
一致。编译器会拒绝初始超容量、无权进入和引用不一致的包。

`scene_seeds` 不是预写场景剧本，而是地点内部可发现空间的高层大纲：

```json
{
  "scene_seeds": [
    {
      "key": "default",
      "name": "半扇后门",
      "premise": "庙内外人物相遇和交换线索的门槛空间。",
      "tags": ["threshold", "public"],
      "dramatic_question": "众人是否交换足够事实并决定铃片保管与去向？",
      "failure_pressure": "雨水正在冲淡痕迹，持续猜疑会失去追踪时机。",
      "closure_signals": [
        "角色明确约定铃片保管责任",
        "角色共同选择下一处场景",
        "角色明确分开并实际改变去向"
      ]
    },
    {
      "key": "bell-corridor",
      "name": "悬铃夹廊",
      "premise": "循异常铃声深入后才首次显现的夹廊。",
      "tags": ["interior", "discoverable"],
      "dramatic_question": "悬铃是警戒、标记还是误导？",
      "failure_pressure": "穿堂风正在改变铃位。",
      "closure_signals": ["角色确认一枚悬铃的作用", "角色放弃查验并改变去向"]
    }
  ]
}
```

Runtime 第一次进入某个 scene key 时，才依据世界种子、地点种子、scene seed、
世界时刻和已存在的同地点场景生成布局、物件与轻量 NPC，并提交
`scene_instantiated`。同一 scene id 重访时读取已提交实体，不重新生成；时间推进、
角色出入、物件持有与对象交互继续写事件。scene seed 只能规定空间前提和约束，
不能预写角色走位、台词、冲突结果或剧情结局。

选择 `scene-pressure-v1` 时，编译器要求世界提供 `dramatic_horizon`、每个角色
的完整 `motivation`，并要求每个 scene seed 都有 `dramatic_question`、
`failure_pressure` 和非空 `closure_signals`；缺失时不会让模型自行补齐。

`world.yaml.dramatic_horizon` 只定义中央问题、成功条件、失败条件和不可违反的
世界叙事原则；它不指定哪一种结局发生，也不作为角色每一回合的任务单。角色
`profile.yaml` 的 `goals` 写整段路的志向，一处地点完成不了。`motivation` 定义
`terminal_desire`、`fear`、`sacrifice_boundary`、`active_commitment` 和
`completion_signals`。`soul.yaml` 写稳定的行事方式：怎么看、怎么说、冲突里
怎么站。眼前这一手由运行时从现场推出来，不要把门口的差事写进志向。这些字段
不能包含预写对白、走位或结果。

重要线索分开放到不同地点。每个 scene seed 只写这一处肉眼能看见的一层、催人
离开的时限，以及取到这一层之后如何离开。`dramatic_question` 是这一处的限度，
不是第二个志向。门槛场景过路就能看见；里间要有人决定进去才生成。scene seed
不能把下一处才看得见的事实写进前提。

Runtime 将 scene seed 投影为 `dramatic` 组件。连续无信息、关系、持有、位置或
承诺增量的回合会提高压力。同一人把已经做过的决定再说一遍，记为无进展，正文
也不再收这一句。裁决器只能在已发生行动满足 `closure_signals` 时提交阶段结果。
收束信号描述状态变化，不描述实现它的动作序列。阶段收束是这一处的内部节拍，
不是章节刀口。写了 `location_id` 的 incident 和 UserGate，要等有人在该地点才发生。

Evolution 的 `phase_predicates` 由 `tick`、`resource`、`relationship`
三类 typed predicate 构成。全部满足时 Runtime 只写入一次
`phase_snapshot`：保存当前状态、作者目标、谓词结果和未决项，不装载下一阶段
剧情，也不生成预写事件。

## 反剧本约束

目录世界包禁止用作者字段预排运行结果，包括：

- `conflict`、`stakes`
- `character_arc` / `character_arcs`
- `obligation` / `obligations`
- `dialogue` / `dialogues`
- `blocking`
- `outcome` / `outcomes`
- `script`

这些约束要求变化从角色需求、资源、地点、通路、规则和 seed 中产生，而不是把预写场景伪装成自主性。

## 编译与 CLI

成功编译得到 `CompiledWorld`，其中包含：

- `PackageManifest`
- `WorkflowIR`
- `AutonomousWorldSpec`
- `content_hash`

Python API：

```python
from engine.world import compile_package

result = compile_package("worlds/echo-quay")
if not result.ok:
    for issue in result.diagnostics:
        print(issue.code, issue.path, issue.message)
compiled = result.compiled
```

CLI：

```bash
python scripts/world.py validate worlds/echo-quay
python scripts/world.py compile-inspect worlds/black-pine-ridge
python scripts/world.py simulate worlds/echo-quay --ticks 8 --seed 17
python scripts/world.py simulate worlds/echo-quay --ticks 8 --seed 17 \
  --story-output-dir outputs/echo-quay/stories
python scripts/world.py simulate worlds/black-pine-ridge --ticks 12 --seed 17 \
  --gate-choice bank-the-embers --story-output-dir outputs/black-pine/stories
```

`--gate-choice` 在模拟停到 UserGate 后应用指定 choice，并继续剩余 Tick。choice
可选的 `observation` 是选择提交后立即成为客观历史的可观察结果，不得写角色
反应、台词、心理或后续结局。

## Tick、Avatar 与呈现

世界包定义模拟输入，不定义 Episode：

```text
CompiledWorld → Tick / Resolver → Event Log → Projection
→ 可选 Narrative Delivery → PresentationStore
```

`scene_turns` 下，每个完整角色只得到当前场景的第一人称投影，包括可见对象、
对象当前锚点与唯一持有人、最近公共回合、待回应交流和最近外部异变。投影里的
场景问题写成“这一处只能看清这一层”。本地 NPC 已经说过这一层之后，投影会要求
带着听到的离开，不要再问第二遍。角色提交这一手，调度只有三种：

- `think`：只更新自己，不请环境。没有真正公开承担的决定时，不进入正文。
- `address`：原话提交，并立刻加载被点名的角色或 NPC。说话的人不能替对方回答。
- `act`：只有离开、取放物品或改变大家都能看见的事实时，才请环境裁决。提到物件不等于动手。

一条调度链结束之前不切章。离开当前地点时，裁决只能落到相邻通路的默认场景，
不能跳到更远的地点，也不能把离开写成原地迈步。同一地点的里间用 `inner_scenes`。
还没有别人回答这一层时，运行时不会把“离开”自动补成旅行。场景首次进入、重访、
时序更新和裁决回合都进入同一 Event Log，可 replay/fork。旧 `actor_windows` 的
opportunity/reservation/Resolver 路径仍用于兼容世界。NPC 保持轻量，只说自己
亲眼见过、且还没说过的本地事实，不编别人的经历。

`actor_windows` 路径上，NPC 与 Avatar 使用相同的行动 schema、知识门、capability、地图约束、成本和 Resolver。`scene_turns` 里的环境 NPC 不走完整角色意图。Avatar 仅意图来源不同，缺席时不被自主调度器代演。

Avatar 只能携带经过边界校验的 `AvatarPackage`（profile、soul、私有
memory seed）。入口地点必须带 `entry`（兼容 `avatar-entry`）tag，或显式声明
`allow_avatar_entry: true`。首版离线策略只支持 `pause`：离开和再加入都写入
Event Log，再加入保留已有位置、状态和记忆；离线期间环境规则仍可共同影响
其状态，但调度器和 catch-up 不会代演其行动。

`world.fate-interventions.v1` 启用独立 `fate_intervention` 规则。规则包含
`id`、`conditions`、`once`/`cooldown_ticks`、结构化 `effects` 和
`costs`。它由用户按 id 主动调用，不打开或阻塞 UserGate，不能指定角色台词、
反应或结果。条件或成本不足时不会追加事件，也不会部分修改状态；成功事件与
其他 Runtime 事件一样可 explain、replay 和 fork。

`episode_overrides` 里的 `max_events`、`max_world_time_span` 仍会通过校验，
但长篇发布接上内容分章器之后，不用它们切章。分章器过滤内部调度，读当前这一处
和下一处开头的已提交材料：同一地点的里间不算换地方；只有赶路、还没有阅读弧时
不成章；同一条 `chain_id` 不拆开。已有双方原话的章节直接装配这些话，不另写一篇。
只有行动或单人材料仍走四段文学管线。`PresentationStore` 中的正文、游标和重渲染
版本不属于世界包，也不参与客观 replay。
它是内部交付状态，不是最终用户文件；`--story-output-dir` 会把已通过事实校验的
Presentation 另行导出为可直接阅读的 `episode-*.md`。

## 当前探针与历史边界

- `worlds/echo-quay/`：反剧本探针。
- `worlds/black-pine-ridge/`：多地点、多角色与私有种子记忆探针。

作者定义变更后，已有运行只能从新 revision 重新开始，或在明确事件边界 fork。禁止静默把新定义套到旧 Event Log；表现层重渲染不改变世界事实，因此不是 fork。
