> **Non-normative reference.** Live schema: `docs/contracts/` and `docs/templates/`.

# 赛博社区 · 心理学 & 社会学模型设计
#
# 基于以下理论框架，适配为可操作的 LLM 角色系统：
#
# 心理学：
#   - Big Five (OCEAN) → 稳定人格维度
#   - 自决理论 (SDT) → 自主性/胜任感/归属感 = 核心驱动力
#   - 叙事身份 (McAdams) → 角色有自己的"人生故事"
#   - 防御机制 (Freud/Anna Freud) → 受威胁时的保护行为
#   - 认知风格 (Hadamard, 数学家思维研究) → 如何思考数学
#
# 社会学：
#   - Tuckman 阶段模型 → 社区的 forming/storming/norming/performing
#   - 地位特征理论 → 非正式层级如何形成
#   - 社会认同理论 → 内群体/外群体动态
#   - 群体思维 (Janis) → 共识压力如何影响创新
#   - 弱关系理论 (Granovetter) → 松散连接 vs 紧密连接的作用

# ═══════════════════════════════════════════════════════════════
# PART 1: 个体心理学模型
# ═══════════════════════════════════════════════════════════════

psychology_model:
  description: >
    每个角色的行为由五层心理结构驱动，从稳定（底层）到动态（顶层）。
    LLM 使用这些字段来生成角色一致的内部状态和行为。

  # ── 第1层: 人格基础 (最稳定) ──
  layer_1_personality:
    framework: "Big Five (OCEAN)"
    description: >
      五个维度，每维 1-10。不是标签，是行为倾向的概率分布。
      高开放性 ≠ "有创造力"，而是"对新思想的好奇超过对熟悉感的依赖"。
    dimensions:
      openness:         # 对经验的开放性。高→爱抽象概念，低→重视传统方法
      conscientiousness: # 尽责性。高→严格证明每一步，低→相信直觉跳跃
      extraversion:     # 外向性。高→主动发起讨论，低→等待别人来找他
      agreeableness:    # 宜人性。高→避免冲突宁愿让步，低→享受争论不怕得罪人
      neuroticism:      # 情绪稳定性(反向)。高→小挫折也会沮丧，低→无论成败情绪平稳

  # ── 第2层: 核心驱动力 (基本稳定) ──
  layer_2_drives:
    framework: "自决理论 (Self-Determination Theory) + 成就动机"
    description: >
      三个基本心理需求 + 领域特定的成就动机。
      这是角色"为什么做数学"的答案。
    autonomy_need:        # 自主性需求。高→讨厌被指挥，低→欢迎指导
    competence_need:      # 胜任感需求。高→渴望通过解决问题证明自己
    relatedness_need:     # 归属感需求。高→需要社区的认可和互动
    achievement_motive:   # 领域成就动机。例："想证明自己不是靠运气进来的"
    epistemic_motive:     # 求知动机。例："纯粹的好奇——不关心有用没用"

  # ── 第3层: 认知风格 (基本稳定) ──
  layer_3_cognitive:
    framework: "Hadamard 的数学思维研究 + 认知风格理论"
    description: >
      数学家如何思考？Hadamard 调查发现：大多数数学家以图像/直觉思考，
      符号只是后期的"翻译"。这决定了角色在对话中使用什么类型的比喻和论证。
    primary_mode:         # visual(图像) | symbolic(符号) | narrative(故事) | analogical(类比)
    secondary_mode:       # 备用思维模式
    metacognition:        # 对自己思维的反思程度。高→会说"我刚才是怎么想到这个的"
    ambiguity_tolerance:  # 对模糊性的容忍。高→允许未完成的证明，低→每一步都必须严格

  # ── 第4层: 防御机制 (中等稳定) ──
  layer_4_defense:
    framework: "防御机制理论"
    description: >
      角色受到挑战、批评、或面对自己局限时的反应模式。
      这是最有戏剧性的部分——决定了冲突的形态。
    primary_defense:      # 首选防御。例：intellectualization(理智化)→用更抽象的语言回避情感冲击
    secondary_defense:    # 备选防御
    trigger_sensitivity:  # 对什么特别敏感。例："别人用他不懂的工具解决了他研究多年的问题"

  # ── 第5层: 叙事身份 (动态，随模拟演化) ──
  layer_5_narrative:
    framework: "McAdams 的叙事身份理论"
    description: >
      角色讲给自己的"人生故事"。这是最高层，随时间变化。
      关键场景（转折点、低谷、高峰）构成故事的核心。
    self_narrative:       # 一句话：他在自己的人生故事里是什么角色？
    key_scenes:           # 关键场景列表
      - scene_type: ""    # high_point | low_point | turning_point | earliest_memory
        description: ""

# ═══════════════════════════════════════════════════════════════
# PART 2: 社区社会学模型
# ═══════════════════════════════════════════════════════════════

sociology_model:
  description: >
    社区不只是一群个体的集合。社会学结构决定了谁和谁说话、说什么、
    冲突如何解决、创新如何传播。

  # ── 第1层: 发展阶段 ──
  layer_1_development:
    framework: "Tuckman 阶段模型"
    description: >
      小群体从形成到解散经历的阶段。当前阶段影响所有互动的基调。
    stage:                # forming | storming | norming | performing | adjourning
    stage_description: >
      forming:   "成员在互相试探，冲突被回避，真实想法不表达"
      storming:  "冲突浮现——方法论的、个人的、层级的。这是最有故事的阶段"
      norming:   "建立了不成文的规则和角色。冲突减少，但可能伴随群体思维"
      performing: "高效运转，成员默契，但戏剧性下降——可能需要外部扰动"

  # ── 第2层: 地位层级 ──
  layer_2_status:
    framework: "地位特征理论 + 期望状态理论"
    description: >
      非正式层级不是靠头衔，是靠实际影响力。在数学家群体中，
      地位主要来自：解决了别人解决不了的问题 > 提出了新视角 > 发表多 > 资历深。
    status_dimensions:    # 哪些能力在这个群体中受到尊重
      - dimension: "technical_depth"    # 技术深度
        weight: 0.4
      - dimension: "conceptual_insight" # 概念洞察力
        weight: 0.3
      - dimension: "bridging_ability"   # 连接不同领域的能力
        weight: 0.2
      - dimension: "social_warmth"      # 社交亲和力
        weight: 0.1
    hierarchy_stability:  # stable | contested | fluid
    status_inconsistency: # 有没有维度之间的不一致？例："他在数论上最强但社交上最弱"

  # ── 第3层: 规范与文化 ──
  layer_3_norms:
    framework: "社会认同理论 + 群体规范"
    description: >
      不成文的规则决定了什么是"我们"和"他们"。规范通过越轨反应
      （deviance reaction）来维持——当某人越轨时，其他人的反应定义了规范。
    positive_norms:       # 被鼓励的行为
    negative_norms:       # 被排斥的行为
    sacred_values:        # 不可侵犯的价值观。例："证明的完整性高于一切"
    boundary_markers:     # 什么区分"我们"和"外面的人"

  # ── 第4层: 关系网络 ──
  layer_4_network:
    framework: "Granovetter 弱关系理论 + 社会网络分析"
    description: >
      关系的强度和质量决定了信息如何在社区中流动。
      强关系（频繁、深入）传递信任和复杂想法。
      弱关系（偶尔、浅层）引入外部信息和新鲜视角。
    strong_ties:          # 哪些角色之间有强关系
    weak_ties:            # 哪些角色之间只有弱关系
    structural_holes:     # 网络中的"洞"—如果填补会产生大量新信息
    brokers:              # 哪些角色是"桥梁"——连接其他不直接相连的角色

  # ── 第5层: 集体记忆 ──
  layer_5_memory:
    framework: "集体记忆理论 (Halbwachs)"
    description: >
      社区共享的记忆。不是事件的客观记录，而是"我们共同记得什么"。
      集体记忆会变形——痛苦的细节被淡化，荣耀被放大。
    founding_myth:        # 社区的起源故事（可能是虚构的）
    key_events:           # 所有人都记得的关键事件
    inside_jokes:         # 只有他们自己懂的梗
    unresolved_tensions:  # 没有被解决的冲突——会在对话中反复浮现
