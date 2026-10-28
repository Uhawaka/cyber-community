# Narrative

`community_threads.py` 从只读社区历史提取有来源的后果线索，并呈现已经提交的
行动和原话。它不创建事实、不调用角色策略、不推进 Tick，也不反向写入记忆。

公共入口为 `project_threads` 和 `render_thread`。旧 Episode、Presentation、
文学渲染与发布执行链已退役。

`skill_library/` 和 `voice_library/` 的 manifest 仍供作者体验配置编译校验使用；
它们不是当前运行器执行的文学管线。
