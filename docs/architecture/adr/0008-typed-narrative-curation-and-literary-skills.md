# ADR-0008：Typed 叙事策展与宿主文学 Skill

- 状态：Accepted
- 日期：2026-10-17

## 决策

叙事交付拆分为六个固定步骤：

```text
source_filter → curate → plan → render → validate → publish
```

- Source Filter 只暴露受众可见且具有读者价值的已提交事件。
- Narrative Curator 按时间窗、焦点、变化和因果关系形成 Episode 窗口。
- NarrativePlan 只能引用窗口内来源，描述焦点、beats、转折与未决点。
- LiterarySkill 是宿主注册、版本化且可执行的编辑阶段，不是拼入总 Prompt 的
  检查清单。默认管线固定为发展编辑、场景写作、行文编辑、事实连续性编辑；
  每个阶段从独立 `SKILL.md` 加载方法，并有 typed 输入输出和独立诊断。
- 世界包通过编译后的 Editorial ExperienceContract，为四个固定 stage 槽位
  选择兼容 Skill，并选择 `voice_id`、typed 文风和角色声音档案。
- Plan 把来源合并为开场、发展、转折、余波等场景单元，并记录来源内已有的
  目标、阻力和结果；禁止一事件一段的机械翻译。
- Renderer 逐阶段生成 `EditorialBrief` 与 `SourcedDraft`；每一段来源在后续
  编辑中不可删除、增加或重排。Validator 执行事实门禁与行文反模式门禁，
  诊断只返回负责该问题的编辑阶段，并受有限重试预算约束。
- Publish 只写 PresentationStore 与可再生用户文档，不修改世界历史。

## 权限边界

世界包不得提供自由 Prompt、可执行代码或动态 Skill。LiterarySkill、模型和
Renderer 均不能创建 Event、Delta、Memory 或角色台词。世界/地点描述只有在
成为编译后的授权 lore source 时才可作为环境描写依据。

文学迭代使用已冻结的 `presentation-store.v1` 或 Event Log，只复制输入后
重渲染；不得调用 Tick。世界运行证据与文学质量证据分别报告。

模型可以是主 Renderer，但不是事实裁决者。异常、超时、未知 Skill、非法来源、
越界实体或新增引语必须留下诊断并进入确定性回退。

## 理由

单次把全部未呈现事件交给一个 Renderer，会把事件日志变成长篇流水账。仅增加
Prompt 不能解决 Episode 边界、焦点选择、因果闭包和事实权限问题，也无法让不同
世界稳定复用专业表达能力。Typed Plan、通用 craft Skill 与配置选择的类型 Voice 将
“讲什么”“怎样写”“这个世界怎样说话”分离，同时不扩大作者代码权限。

## 后果

- presentation Workflow 升级为 `world-workflow/v1alpha3`；其他三类 Workflow
  继续使用 `v1alpha1`。
- 长运行可以一次发布多篇 Episode，每篇独立推进受众游标。
- 被过滤的内部事件仍保留在 Event Log 和诊断中，但不进入正文来源。
- 自动校验只能证明来源和边界，不能独自证明文学质量；仍需人工盲评。

## 验收

1. 40 Tick 运行产生多篇有上限的 Episode，而不是一篇全量日志。
2. `action_rejected`、`action_replanned` 等调度事件不进入正文。
3. 每个模型段落声明合法且有序的来源事件。
4. 两个世界使用不同 Skill 时输出可辨识，但事实来源保持一致。
5. Skill 或模型失败时，Event Log 不变且可发布确定性回退。
