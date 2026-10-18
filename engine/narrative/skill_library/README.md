# Literary Skill Library

这些文件是运行器实际加载的宿主 Skill，不是供开发者参考后再手工复制到 Prompt
的文档。`manifest.json` 固定阶段、版本和输入输出 Schema；每个 `SKILL.md`
定义一个编辑岗位的方法与失败边界。

首版方法参考并重新组织了以下公开 Agent Skill：

- `cjdavis62/claude-creative-writing` 的 developmental editor、fantasy writer
  和 line editor 分工。
- `pavelkudrna83/creative-writing-skill` 的场景目标、冲突、感官细节与修订检查。
- `tanaka-naoki/japanese-creative-writing` 的小说/怪谈类型约束分离方式。

本项目没有直接执行第三方 Prompt。所有方法都经过事实来源、段落 provenance、
世界 Voice 和不可写回 Event Log 的边界改写。世界包只能选择注册 Skill ID，
不能提供自由 Prompt 或可执行代码。
