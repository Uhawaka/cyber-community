# 社区基础设施模型
#
# 角色是能量体生命，没有实体。
# 他们的"空间"是共享的信息场——可以被感知、可以被改变。
# 基础设施不是物理建筑，是可塑的结构化信息空间。
#
# 核心概念:
#   Node (节点) = 一个信息结构单元。可以是"书房""公共区""冥想园"
#   Node 有属性: 谁创建的、什么功能、当前状态、连接哪些其他节点
#   角色可以: 创建节点、修改节点、在节点间移动、在节点中活动
#   节点影响: 可用活动类型、情绪偏置、灵感概率

# ═══════════════════════════════════════════════════════════════
# 节点类型
# ═══════════════════════════════════════════════════════════════

node_types:
  study_chamber:      # 私人研究空间
    creator_attuned: true   # 创建者在此有加成
    activities: [deep_study, computation, writing]
    modifiers:
      focus: +20%
      energy_cost: -10%
    aesthetics: ""    # 创建者可以定义美学——一个充满质数可视化的空间 vs 一个箭头构成的回廊

  commons:            # 公共区 / 集会空间
    activities: [discussion, gathering, debate, casual_talk]
    modifiers:
      social_energy: +15%
    shared: true      # 所有人平等访问
    history: []       # 在此发生的对话会留下"回响"——后来者能感知到之前的讨论残余

  archive:            # 知识库 / 图书馆
    activities: [research, arxiv_search, reading]
    modifiers:
      inspiration_rate: +10%
    contents: []      # 存入的知识片段——论文、计算结果、笔记
    growth: "accumulates as characters deposit knowledge"

  contemplation_garden:  # 冥想/发呆/恢复
    activities: [rest, idle_thought, reflection, entertainment]
    modifiers:
      energy_recovery: +30%
      idle_thought_rate: +25%
    mutable: true     # 可以被改造成任何东西

  workshop:           # 实验/计算空间
    activities: [run_code, numerical_experiment, data_visualization]
    modifiers:
      computation_speed: +20%
    resources: []     # 可用的计算资源

# ═══════════════════════════════════════════════════════════════
# 节点操作
# ═══════════════════════════════════════════════════════════════

node_actions:
  create_node:        # 角色花费大量能量创建新节点
    energy_cost: 40
    cooldown: "2 days"
    requires: "角色有一个明确的意图——'我需要一个什么样的空间'"

  modify_node:        # 改变节点的属性/美学/功能
    energy_cost: 15
    example: "Elias 把冥想园的一角改造成了数值可视化墙"

  connect_nodes:      # 在两个节点间建立连接
    energy_cost: 5
    effect: "节点间可以传递信息/回响"

  deposit_knowledge:  # 把研究成果存入 archive
    energy_cost: 5
    effect: "archive 增长，后来者可以引用"

  leave_echo:         # 在公共区留下一个想法/问题
    energy_cost: 3
    effect: "后来者进入该节点时感知到回响"

# ═══════════════════════════════════════════════════════════════
# 活动类型扩展
# ═══════════════════════════════════════════════════════════════

activities:
  # 研究工作
  deep_study:         { energy: 20, produces: "reasoning_chain" }
  computation:        { energy: 15, produces: "numerical_result" }
  writing:            { energy: 10, produces: "paper_or_note" }

  # 社交
  discussion:         { energy: 15, produces: "dialogue + memory" }
  gathering:          { energy: 25, produces: "group_discussion" }
  debate:             { energy: 20, produces: "dialogue + tension" }
  casual_talk:        { energy: 5,  produces: "social_bond" }

  # 恢复/娱乐
  rest:               { energy: -15, produces: "energy_recovery" }
  idle_thought:       { energy: 3,  produces: "inner_monologue" }
  reflection:         { energy: 8,  produces: "deep_think" }
  entertainment:      { energy: 5,  produces: "mood_boost + random_insight" }
  exploration:        { energy: 10, produces: "node_discovery_or_creation" }

  # 基础设施
  create_node_action: { energy: 40, produces: "new_node" }
  modify_node_action: { energy: 15, produces: "node_change" }
  connect_action:     { energy: 5,  produces: "node_connection" }

# ═══════════════════════════════════════════════════════════════
# 默认初始社区
# ═══════════════════════════════════════════════════════════════

default_community:
  nodes:
    - id: "commons"
      type: "commons"
      name: "中央大厅"
      description: "一个圆形空间。中央有一块共享白板，上面留着所有人的笔迹。"
      created_by: "community"
      echoes: []

    - id: "elias_study"
      type: "study_chamber"
      name: "Elias 的计算室"
      description: "数轴上漂浮着质数标记，密度波动像慢动作的波浪。墙角堆着算到一半的草稿。"
      creator: "Elias"
      aesthetics: "数值的、密集的、像一条数据构成的河流"

    - id: "yuki_study"
      type: "study_chamber"
      name: "Yuki 的箭头回廊"
      description: "无数箭头在空间中构成交换图。每一条箭头都是一次'所以...'的逻辑跳转。"
      creator: "Yuki"
      aesthetics: "抽象的、极简的、像一座用箭头搭建的教堂"

    - id: "pavel_study"
      type: "study_chamber"
      name: "Pavel 的实验室"
      description: "湍流的可视化在空间中旋转。方程写在流动的表面上，像水面的波纹。"
      creator: "Pavel"
      aesthetics: "物理的、动态的、像站在风暴中心观察涡旋"

    - id: "garden"
      type: "contemplation_garden"
      name: "静思园"
      description: "一片空旷的场域。每个人看到的都不一样——取决于ta此刻的心境。"
      mutable: true

    - id: "archive"
      type: "archive"
      name: "知识库"
      description: "所有研究成果的汇聚之地。像一座不断生长的图书馆，书架自己会重新排列。"

    - id: "workshop"
      type: "workshop"
      name: "计算工坊"
      description: "共享的计算资源池。数值实验在这里运行，结果直接投射到中央大厅的白板上。"

  connections:
    - [commons, elias_study]
    - [commons, yuki_study]
    - [commons, pavel_study]
    - [commons, garden]
    - [commons, archive]
    - [commons, workshop]
    - [archive, workshop]
    - [garden, commons]
