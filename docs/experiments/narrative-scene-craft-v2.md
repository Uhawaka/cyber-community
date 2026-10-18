# EXP-20261017-002：场景写作 Skill 与世界声音

## 元数据

- 状态：inconclusive
- 日期：2026-10-17
- 世界包：`echo-quay`、`black-pine-ridge`
- Presentation Workflow：`world-workflow/v1alpha3`
- Skill：`scene-craft-v1`
- Voice：`echo-quay-restrained-v1`、`black-pine-strange-tale-v1`
- 模型：未启用；本轮验证确定性回退与模型输入契约
- seed：17
- 黑松岭：40 Tick
- 回声码头：运行至 Tick 8 的 UserGate

## 假设

如果把“文风词库”拆成多遍写作方法与项目声音，并让 NarrativePlan 把事件合并成
场景 beat，那么确定性输出应消除一事件一段、机械话本转场和运行元数据解释；
模型输入应同时获得目标、阻力、转折、结果、POV 和编辑规则。

## 实现

```text
Digest
→ Scene Plan（opening / development / turn / aftermath）
→ Draft
→ Developmental checks
→ Lore / fact validation
→ Line checks
→ Publish
```

`scene-craft-v1` 包含场景规划、初稿、结构编辑和行文编辑四遍规则。WorldVoice
另行定义 POV、优先注意、声音锚点、禁用句式和标题策略。世界包只能选择注册项，
不能提供自由 Prompt。

确定性回退会合并多个来源、压缩重复移动/观察/台词，省略 Soul 和调度元数据。
文学门禁拒绝一事件一段、重复“却说/正此时/未几/少顷”及“发生关系变化”等句式。

## 结果

- 全量自动化测试通过，共 139 项。
- 黑松岭生成 10 篇 Episode，输出位于
  `outputs/simulations/black-pine-ridge-seed17-craft-v3/stories/`。
- 回声码头生成 2 篇 Episode，输出位于
  `outputs/simulations/echo-quay-seed17-craft-v2/stories/`。
- 新黑松岭正文不再出现机械话本转场、每事件独立段落或“关系变化/资源变化”解释。
- 相同 seed 的 Runtime `history_hash` 与改造前实验一致，说明呈现改造未改变世界历史。

## 结论

技术假设通过，产品文学质量仍为不确定，因此实验总判定为 `inconclusive`。

确定性回退现在是可读的场景化事实梗概，但不应冒充文学成稿：事实权限禁止它
凭空增加感官细节、人物心理或新动作。黑松岭来源仍以往返移动、观察和模板化问句
为主，即使压缩后也缺少足够的目标阻力、信息增量和局势转折。

下一轮需要分别验证：

1. 使用真实模型执行四遍写作流程，并进行人工盲评；
2. 行为层提高对话信息增量，减少无目的折返；
3. Curator 围绕因果链和转折选择来源，而不是主要依赖固定事件窗口。
