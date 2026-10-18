# Narrative

## 职责
把已提交事件适配为读者来源，执行 Episode 策展、typed NarrativePlan、
可执行的宿主 Literary Skill 管线、项目 WorldVoice、渲染校验和展示状态持久化。

默认编辑管线为：

```text
developmental-editor-v1
→ scene-writer-v1
→ line-editor-v1
→ fact-continuity-editor-v1
```

方法正文位于 `skill_library/*/SKILL.md`，运行时逐阶段加载和执行，不由
Renderer 拼成一段总 Prompt。

## 输入
只读事件快照、受众身份、交付策略与渲染器。

## 输出
`NarrativeDigest`、`NarrativePlan`、`Presentation`、`Episode`、独立剧情文档与
渲染诊断。

## 禁止事项
不得依赖 runtime/application，不得续写未发生事实，不得修改客观历史。

## 公共 API
以 `engine.narrative` 导出的 digest、renderer、delivery、store 契约为准。
