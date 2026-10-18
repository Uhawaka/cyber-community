# 项目文档导航

本文是文档入口。阅读顺序取决于目的，不需要从头读完所有材料。

## 快速入口

- 想理解产品为什么这样设计：读[设计理念与整体质量模型](product/design-principles-and-quality.md)。
- 想了解现在做到哪里：读[当前进度与后续重点](status/current-status.md)。
- 想开始开发：读[项目结构与变更归属](architecture/project-structure.md)和[协同迭代流程](development/iteration-process.md)。
- 想理解设计蓝图：读 [设计蓝图](design.md) 与[模块边界](architecture/module-boundaries.md)。
- 想制作世界包：读[目录世界包作者格式](authoring/world-graph.md)。
- 想查看技术证据：读[实验索引](experiments/README.md)和[M0–M7 最终报告](experiments/m0-m7-final-report.md)。

## 文档层级

### 产品层

- [设计理念与整体质量模型](product/design-principles-and-quality.md)：不变量、反模式与质量评估口径。
- [自主世界产品规格](product/autonomous-world-spec.md)：当前 Runtime 纵切的产品契约。
- [叙事交付规格](product/narrative-delivery-spec.md)：历史如何转化为只读 Presentation。

[设计蓝图](design.md) 可以随开源分支发布。当前完成度以状态文档和可执行规格为准。未纳入版本库的愿景笔记只留在本地，不作为开发依据，也不进入开源分支。

### 架构层

- [设计蓝图](design.md)：权威链和主要机制。
- [项目结构与变更归属](architecture/project-structure.md)：目录职责和需求放置规则。
- [模块边界](architecture/module-boundaries.md)：允许的依赖和跨模块不变量。
- `architecture/adr/`：已接受架构决策及其原因。

ADR 记录当时为什么做决定；如果当前实现改变，应新增 ADR 或明确废弃旧决策，不静默改写历史。

### 契约与作者层

- [Soul 与 Memory 边界](contracts/soul-memory-boundary.md)；
- [目录世界包作者格式](authoring/world-graph.md)。

这些文档描述数据语义与作者输入。实现与文档冲突时，应先停止扩展，确认是代码缺陷还是规格需要显式升级。

### 开发与实验层

- [Workflow 与 Runtime 协同迭代流程](development/iteration-process.md)；
- [实验模板与 Capability 晋升规则](experiments/README.md)；
- [世界整体质量评审模板](experiments/quality-review-template.md)；
- [验证追踪矩阵](experiments/traceability.md)；
- [M0–M7 技术重建最终报告](experiments/m0-m7-final-report.md)；
- [M0–M7 历史路线图](world-mechanics-roadmap.md)。

路线图和最终报告是历史技术阶段；新的优先级以[当前状态](status/current-status.md)为准。

## 权威顺序

发生冲突时按以下顺序处理：

1. 安全、事实完整性和 replay 不变量；
2. 已接受 ADR 与模块边界；
3. 当前产品规格和数据契约；
4. 设计理念与质量目标；
5. 当前状态和迭代计划；
6. 长期愿景、参考材料与历史实验。

这不是说愿景不重要，而是愿景不能直接覆盖已经运行的事实契约。需要改变高优先级契约时，必须通过新 ADR、迁移策略和回归证据完成。

## 状态词

项目文档统一使用：

- **目标**：产品希望达到，尚不表示存在实现；
- **已实现**：代码路径存在；
- **已验证**：有自动化测试或可重复实验；
- **质量验证**：多 seed 与人工评审达到质量线；
- **用户验证**：目标用户实验达到预设结果；
- **后置**：当前阶段明确不做；
- **废弃**：不再使用，但保留历史原因和替代方案。

“已实现”不得简写成“已完成”，除非上下文已经明确完成的是哪一层。

## 哪些文档可以公开

开源分支发布当前引擎和下面这些文档：

- `docs/design.md`，以及 `docs/architecture/`、`docs/authoring/`、`docs/contracts/`、`docs/development/`、`docs/experiments/`、`docs/status/`
- `docs/product/` 里的三份规格。它们写的是运行边界和质量口径，可以公开
- `README.md`、`engine/`、`worlds/`、`tests/`、`scripts/`

只留在本机、不进入开源分支：

- `docs/reference/生成式世界引擎_产品设计.md` 已在 `.gitignore` 中
- `.env`、`outputs/`、编辑器目录

本地开发用 `dev`。`open` 从远端 `main` 拉出，树与 `dev` 的公开内容一致，但历史里不含上述本地笔记。发布时只推这条分支：

```bash
git push origin open:main
```

不要推送 `main` 或 `dev`。那两条本地历史里曾经出现过未公开笔记，推上去会把笔记带进开源仓库。

## 维护规则

- 新增通用机制：更新规格、测试、实验和当前状态；涉及边界时增加 ADR。
- 修改世界包格式：更新作者格式、schema 版本、迁移说明和编译测试。
- 修改 Event schema：说明 replay/持久化兼容性并补恢复测试。
- 修改叙事策略：保留来源与事实校验，并更新质量评估。
- 完成阶段目标：将证据写入实验报告，再更新状态；不要删除失败实验。
- README 只保留最短入口，细节链接到这里，避免多处维护不同版本的事实。
