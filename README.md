# 赛博社区

赛博社区是一套生成式世界引擎的可执行纵切：作者提交目录世界包，编译器生成不可变 `CompiledWorld`，Runtime 先产生可回放的客观历史，叙事交付再把已提交事件变成可读产物。仓库已经完成技术 M0–M7 门禁，但这不等于完整内容产品已经完成，也不证明文学质量或真实用户留存。

产品与开发决策以[设计理念与整体质量模型](docs/product/design-principles-and-quality.md)为最高层评估依据；当前完成度和已知缺口见[当前进度](docs/status/current-status.md)。

## 已实现主路径

```text
目录世界包
→ schema / 引用 / capability 检查
→ 确定性 CompiledWorld
→ typed WorkflowIR
→ World → Location → 懒生成且持久化的 Scene instances
→ 第一人称这一手：想、说，或对共享事实动手
→ 环境裁决只处理 act；离开落到相邻通路
→ append-only Event Log
→ 可重建 Projection / Memory
→ 只读 Narrative Curator / Delivery
→ 可持久化 PresentationStore
```

`manifest.yaml` 分开引用 assets 与四类 Workflow：`genesis`、`evolution`、`intervention`、`presentation`。它们不是任意 DSL 或第三方节点生态：每类都必须使用固定顺序的 typed steps、已知 policy 字段和 Runtime 内封闭的 step registry；未知操作、乱序或缺失 handler 均 fail closed。

Presentation Workflow 进一步把交付固定为
`source_filter → curate → plan → render → validate → publish`。世界可选择宿主
注册的版本化 Literary Skill 管线、项目专属 WorldVoice 和 typed 文风档案，
但不能注入自由 Prompt 或代码。默认四个独立 Skill 依次执行发展编辑、场景写作、
行文编辑和事实连续性编辑；方法从 `SKILL.md` 加载，每阶段有 typed 产物与诊断。

默认装配完全确定性。模型 SceneGenerator、IntentPolicy、WorldAdjudicator 与
Renderer 是 `engine/adapters/` 中的显式适配器，只有传入模型配置或
`TextModel` 时启用；模型失败有安全回退，Renderer 候选仍须通过事实校验。

## CLI

```bash
pip install -r requirements.txt

# 编译、8-seed probe 与结构化诊断
python scripts/world.py validate worlds/echo-quay

# 查看编译摘要与 content hash
python scripts/world.py compile-inspect worlds/black-pine-ridge

# 默认确定性模拟
python scripts/world.py simulate worlds/echo-quay --ticks 8 --seed 17

# 同时发布到独立叙事交付层
python scripts/world.py simulate worlds/black-pine-ridge \
  --ticks 20 --seed 17 --episode --gate-choice bank-the-embers \
  --output outputs/simulations/black-pine/summary.json \
  --run-output outputs/simulations/black-pine/events.jsonl \
  --presentation-output outputs/simulations/black-pine/presentations.json \
  --story-output-dir outputs/simulations/black-pine/stories

# 显式启用模型适配器
python scripts/world.py simulate worlds/echo-quay \
  --ticks 8 --seed 17 --episode --model-config model.json

# 不推进世界，只用冻结 Digest 迭代文学 Skill
python scripts/literary.py worlds/black-pine-ridge \
  --presentations outputs/run/presentations.json \
  --model-config model.json --output outputs/literary-rerender

# 按内容分章的可恢复长篇。新机制用新的 run-output，不要 --resume 旧日志
python scripts/world.py longform worlds/black-pine-ridge \
  --target-episodes 3 --max-ticks 16 --chunk-ticks 4 --seed 83 \
  --gate-choice bank-the-embers \
  --model-config model.json \
  --output outputs/longform/run/report.json \
  --run-output outputs/longform/run/events.jsonl \
  --presentation-output outputs/longform/run/presentations.json \
  --story-output-dir outputs/longform/run/stories

# 回归与诊断 benchmark
python -m pytest -q
python scripts/benchmark_runtime.py --ticks 3 --seed 17
```

`world.py` 的三个子命令均输出 JSON。`simulate` 的 `--output`、`--run-output`
和 `--presentation-output` 分别保存摘要、Event Log 和 PresentationStore；
`--story-output-dir` 导出剧情文档。`literary.py` 复制已有 PresentationStore，
只重跑已注册编辑 Skill，同时保存各阶段 trace；它不会加载或推进世界。
模型失败、越界或阶段预算耗尽都会进入确定性回退。

## 运行事实

- Event Log 是一次 run 的动态事实源；状态、位置、关系、Soul overlay 与 Memory 均可重放。
- 世界种子和角色种子是大纲与约束，不是剧本；地点可包含多个 scene seed，
  小场景首次进入时才渲染，重访保留原有布局、物件、人物和时序变化。
- 志向是整段路的方向，行事方式保持稳定，眼前这一手从现场推出来。场景问题只是
  这一处的限度。每一处只生成看得见的那一层。AI 生成环境压力，不指定人物反应。
- `scene_turns` 按 think / address / act 调度。想和说不请环境。离开当前地点只能
  沿通路去相邻地点。阶段收束不是章节刀口；章节由写作模块按内容和离开处划分。
  不需要为走路、交谈、交易或打斗维护固定动作词表。
- Simulation Director 可以从作者定义的 incident 规则选择合法事件，并以 typed Delta 原子写入 Event Log；它不能写台词或指定角色反应。
- Narrative Curator 只读取已提交事件和受众可见信息；Delivery、重渲染和 `PresentationStore` 失败都不能修改世界历史。
- 同一 Tick 的角色候选基于同一快照，经 reservation 与共享 Resolver 结算；冲突产生拒绝和重规划证据。
- NPC 与 Avatar 共用 opportunity、行动 schema、地图/知识/成本门禁和 Resolver。Avatar 仅由用户供给意图，离线 `pause` 时不会被代演。
- UserGate、Fate Intervention 与 author incident 是三种不同机制；它们都有结构化条件、成本/效果、原子失败和 replay 证据。
- 详细模拟、冷区粗粒度结算和 catch-up 都有显式预算；停止与截断是合法结果。

## 模块树

```text
engine/
├── application/           用例入口：校验、运行、参与、叙事发布
├── bootstrap/             唯一组合根；选择确定性或模型适配器
├── contracts/             Actor、Renderer、模型与存储 ports
├── adapters/              模型、JSONL run、JSON presentation 适配器
├── world/                 目录包读取/校验/编译、四 Workflow 定义
├── runtime/
│   ├── kernel/            typed events、Event Log、state、持久化/replay
│   ├── simulation/        Tick、冷热模拟、预算、reservation、Resolver
│   ├── scene/             场景生成/重访、感知、think/address/act 调度与裁决
│   ├── character/         policy、Soul/Memory 长期投影
│   ├── space/             地点 affordance、机会与公开历史
│   ├── workflow.py        四类 Workflow 的封闭 step registry
│   └── autonomous_director.py  incident、UserGate、Fate
├── participation/         Avatar 与介入契约
└── narrative/             只读来源、内容分章、对白装配、校验、Delivery、Store

worlds/echo-quay/           反剧本主探针
worlds/black-pine-ridge/    第二目录包与跨世界探针
scripts/world.py            世界包 CLI
scripts/benchmark_runtime.py 预算化规模诊断
```

## 完成边界

技术 M0–M7 已按[开发计划](docs/world-mechanics-roadmap.md)完成，证据汇总见[最终报告](docs/experiments/m0-m7-final-report.md)。明确后置：World IDE、任意 Workflow DSL/节点生态、完整《西游后传》内容、多媒体生产、公共市场，以及文学质量和真实用户留存验证。

## 文档

- [完整文档导航](docs/README.md)
- [设计理念与整体质量模型](docs/product/design-principles-and-quality.md)
- [当前进度与后续重点](docs/status/current-status.md)
- [设计蓝图](docs/design.md)
- [项目结构与变更归属](docs/architecture/project-structure.md)
- [模块边界](docs/architecture/module-boundaries.md)
- [Workflow 与 Runtime 协同迭代流程](docs/development/iteration-process.md)
- [开发计划](docs/world-mechanics-roadmap.md)
- [目录世界包作者格式](docs/authoring/world-graph.md)
