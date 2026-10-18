# 叙事交付规格

## 目标

叙事交付把已提交历史变成可阅读产物，同时保证文本永远不是新的世界事实。M3 技术纵切已经完成：来源过滤、digest、确定性与显式模型 Renderer、事实校验、回退、受众隔离、重渲染和持久化 `PresentationStore` 均有实现与测试。

文学质量和真实用户留存仍是产品验证，不由技术接通推导。

## 输入与输出

输入：

- 已提交 Runtime events；
- `audience_id` 与 omniscient/avatar 可见性模式；
- presentation Workflow policy；
- 只读 `SourceEventView` 及其因果、变化和来源 id；
- 显式选择的 Renderer。

输出：

- `NarrativeDigest`；
- `Episode`：episode id、来源 id、时间范围、版本和 audience；
- `Presentation`：presentation id、digest、标题、正文、来源 id、版本、audience 与 render diagnostics。
- 用户剧情文档：由已校验 `Presentation` 导出的独立 `story-document.v1` Markdown，正文可直接阅读，front matter 保留世界、Episode、版本与来源数量。

当前没有任意场景合同执行层，也不以预排剧情术语驱动章节。长篇发布接上内容
分章器：窗口收在当前这一处真正离开之前，同一地点的里间不算新章，只有赶路不成章，
同一条调度链不拆开。`episode_overrides` 的最大事件数和时间跨度仍通过编译校验，
但有内容分章器时不拿它们切章。没有写作模型时，有下一处就收到离开之前；否则退回
一段已经结束、并且已经产生后果的内容。

## 交付流程

```text
Event Log
→ audience source filtering
→ internal event filtering
→ read-only Narrative Curator 按内容和离开处分章
→ deterministic digest
→ typed NarrativePlan（场景目标 / 阻力 / 转折 / 结果 / beats）
→ developmental-editor-v1 → EditorialBrief
→ scene-writer-v1 → SourcedDraft
→ line-editor-v1 → SourcedDraft
→ fact-continuity-editor-v1 → SourcedDraft
→ registered WorldVoice + Renderer candidate
→ paragraph provenance / factual / literary anti-pattern validation
→ publish / deterministic fallback
→ PresentationStore
```

Narrative Curator 只读。它与 Delivery、Renderer 都不能推进 Tick、调用 Resolver、提交 Delta 或把呈现文本写回 Memory。

## Renderer

- 默认 `StructuredLiteraryRenderer` 按世界选择的 LiterarySkill 确定性运行。
- `ModelNarrativeRenderer` 是显式 adapter，只在组合根接收模型配置或 `TextModel` 时启用，并作为该次装配的主 Renderer。
- 模型只接收 typed Plan、文风档案与结构化来源事实，并被要求返回
  `title/paragraphs` JSON；每段必须声明有序 `source_event_ids`。
- 新实体、无来源事实、错误类型、异常或超时进入 diagnostics，并回退到确定性来源化文本。
- 模型被接通不代表文学质量已经达到产品标准。

LiterarySkill 与 WorldVoice 均由宿主封闭注册。Skill 是实际运行的版本化资源包，
包含 `SKILL.md`、阶段、输入输出 Schema、方法和失败边界；不是附加到 Renderer
总 Prompt 的文案。Voice 定义项目专属 POV、优先注意、声音范例和禁用句式。
世界包可用 `editorial_pipeline` 选择已注册阶段，并选择 Voice 与 typed 文风，
但不能携带自由 Prompt、代码或插件；它们都不能扩大事实来源。

各阶段独立调用、计时和解析。发展编辑只选择场景脊柱，不写正文；场景写作建立
初稿；行文编辑不能改变段落来源；事实连续性编辑只删除或收窄越界表达。最终
事实门禁仍由 Delivery 所有，Skill 不能自行宣布候选可发布。

确定性回退也必须按场景 beat 合并多个事件。`一事件一段`、重复“却说/正此时/
未几/少顷”以及“发生关系变化”等运行元数据表达属于发布前可自动拒绝的反模式。

## PresentationStore

`PresentationStore` 同时支持无路径实例和独立 JSON 持久化。持久化格式为 `presentation-store.v1`：

- 原子替换、目录 fsync 与 `0600` 权限；
- audience cursor 隔离；
- Episode/Presentation 来源和 render version 一致性校验；
- schema、来源、版本或事实不一致时整体拒绝；
- `clear`、`rebuild`、`rerender` 的磁盘失败不会先污染内存状态。

Store 可清空并从来源事件重建。发布、重渲染、清空和持久化失败均不改变 Runtime Event Log 或 Projection。

`scripts/literary.py` 可复制现有 PresentationStore，用同一 Digest 重跑文学
管线，输出正文、阶段 trace 和输入 SHA-256。该入口不加载或推进世界 run，
用于把素材质量与编辑质量分开评测。

`PresentationStore` 是内部可重建交付状态，不能代替用户产物。CLI 的 `--story-output-dir` 必须从已经通过事实校验的 Presentation 导出 `episode-*.md`；导出过程不得重新生成事实或反向修改 Store。

## 失败方式

- 来源不可见：过滤或拒绝，不泄露给 Avatar。
- 事件不足：不发布，或生成确定性摘要；不补写高潮。
- Renderer 越界/异常：记录 diagnostics 并确定性回退。
- Store 数据损坏：加载 fail closed。
- Store 写入失败：世界历史保留，交付操作失败且可重试。
- 重渲染缺少来源：拒绝，不从旧正文反推事实。

## 验收

1. Avatar 与 omniscient audience 的来源严格隔离。
2. 每条正文事实可追溯到 `source_event_ids`。
3. 模型越界会回退，且 Event Log 不变。
4. 同一来源重渲染只增加 render version。
5. Store 清空后可确定性重建相同来源范围与正文。
6. 持久化 round-trip、损坏拒绝和写失败原子性均通过测试。

多媒体 artifact、通知/收藏产品面、编辑工作台、文学质量评分与真实用户实验明确后置。
