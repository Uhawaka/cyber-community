# ADR-0009：配置驱动的体验契约

- 状态：Accepted
- 日期：2026-10-17

## 决策

世界包用 `experience_profile/v1` 配套声明类型、通用运行模式、编辑 bundle、
typed 文风 override 和角色声音档案。编译器把它解析为不可变的
`CompiledExperienceContract`：

- Runtime 只读取 `RuntimeNarrativeContract` 的压力递增间隔、压力上限、决定阈值
  和收束模式；
- Presentation 只读取 `EditorialExperienceContract` 的 Episode 策略、固定
  stage 图、Skill 选择、WorldVoice、文风和角色声音；
- `genre_id` 只用于编译一致性与质量报告，执行器不得按题材、世界或角色 ID
  分支；
- 世界包只能选择宿主 manifest 已注册的 mode、bundle、Skill 和 Voice，不能
  提供代码、自由 Prompt、任意 Workflow step 或新事件类型。

显式 profile 是体验配置的唯一事实源。旧包可以从 presentation policy 合成
legacy contract；如果显式 profile 与旧 style/episode/pipeline 双写且不一致，
编译器以 `EXPERIENCE_POLICY_CONFLICT` 拒绝，而不是静默选择一边。

## 理由

世界运行和文学编辑是两个生命周期，但同一世界的目标、阻力、类型承诺和表达
方式不能彼此割裂。把题材判断写进 Runtime 会造成换世界即修改引擎；把全部要求
塞进 Prompt 又无法编译校验、重放或定位责任。编译后的两个子契约让世界作者在
一处配套设计体验，同时保持运行事实与文学表达的权限隔离。

## Catalog 与边界

- `engine/world/experience_catalog.py` 保存通用 runtime mode 和 editorial
  bundle 默认值，不含示例世界或角色专名；
- Skill 与 Voice ID 分别由资源 manifest 单源加载；
- Voice 的 lexicon、标题模式和质量门禁位于 `voice_library` 资源，不在 Renderer
  中形成 `if voice_id` 分支；
- 角色注意点、词汇边界、句法和保留信息属于世界包，不能进入宿主 Voice；
- `scene-pressure-v1` 要求世界 horizon、角色 motivation，以及每个 scene seed
  的问题、拖延压力和可观察收束信号齐全。

## 后果

- 修改体验配置会改变 `CompiledWorld.content_hash`；
- 固定编辑 stage 图仍是
  `developmental_edit → scene_draft → line_edit → fact_continuity`，但每个槽位
  可以选择 stage 兼容的已注册 Skill；
- 黑松岭选择“去魅式黑暗神话”编辑 bundle，回声码头选择克制悬疑 bundle，
  二者共享同一通用场景压力模式；
- 自动门禁只能证明配置、事实和执行边界，不能证明成稿已达到专业文学水平。
