# EXP-20261017-008：叙事策展与世界文风 v1

## 元数据

- 状态：passed（技术契约）；inconclusive（文学质量）
- 日期：2026-10-17
- 世界包：`echo-quay`、`black-pine-ridge`
- Workflow：presentation `world-workflow/v1alpha2`
- seed：17 长程输出；两个世界各 8-seed package probe
- 模型：质量基线未启用模型，使用确定性 Skill 回退

## 单一假设

如果在 Renderer 前加入读者事件过滤、有限 Episode 窗口和 typed NarrativePlan，
并让世界通过 typed profile 选择宿主 LiterarySkill，那么长运行可以输出多篇
可追溯、无内部调度噪声且文风可辨识的剧情文档；否则实验失败。

## 机制

```text
Event Log
→ audience / internal source filter
→ bounded Narrative Curator
→ NarrativeDigest
→ typed NarrativePlan
→ registered LiterarySkill
→ sourced paragraphs
→ fact validation / deterministic fallback
→ Presentation + episode Markdown
```

世界包不能提供自由 Prompt、代码或动态 Skill。模型 Renderer 必须返回逐段
`source_event_ids`；来源、实体、引语、顺序或 Plan 不合法时回退。

## 结果

### 回声码头

- 请求 40 Tick，在 Tick 8 的 UserGate 正常暂停；
- 53 个 Runtime 事件；
- 生成 2 篇 Episode；
- 单篇最多 10 个读者来源事件；
- 使用 `restrained-mystery-v1`；
- 剧情文件位于 `outputs/simulations/echo-quay-seed17/stories/`。

### 黑松岭

- 完成 40 Tick；
- 267 个 Runtime 事件；
- 生成 10 篇 Episode；
- 单篇最多 12 个读者来源事件；
- 使用 `strange-tale-v1`；
- 剧情文件位于
  `outputs/simulations/black-pine-ridge-seed17/stories/`。

### 通用门禁

- `action_rejected`、`action_replanned` 不进入任何剧情文档；
- Episode 来源范围互不重叠，受众 cursor 最终推进到已交付边界；
- 两种 Skill 的标题、转场和语体可确定性区分；
- 未知 Skill 和自由 `prompt` 字段在编译期拒绝；
- 模型段落必须携带合法、有序来源；
- 模型越界、异常和超时不修改 Event Log，并进入确定性回退；
- 两个世界的 8-seed package validation 均通过；
- 全量 136 项自动化测试通过。

## 结论

技术假设通过。系统已经从“一次渲染整段日志”升级为可配置、多窗口、可审计的
叙事管线，且不同世界可选择不同文风而不扩大作者权限。

文学质量仍不能判定为通过。确定性 Skill 主要改变标题与转场，正文仍有逐事件
转述和“关系变化/资源变化”等系统解释；黑松岭的移动过多和对话复读来自行为层，
不应由 Renderer 掩盖。

## 下一步

1. 先修移动目的、对话主题和 Soul 演化频率；
2. 增强 NarrativePlan 的主因果线、场景结果和跨 Episode 未决线索；
3. 使用真实模型执行结构化段落协议，并进行匿名人工对照评审；
4. 将“文风可辨识”和“愿意追更”分开评分，避免把前者冒充文学质量。
