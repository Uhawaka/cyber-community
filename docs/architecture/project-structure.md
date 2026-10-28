# 当前版本结构

当前只维护自主社区运行链，不保留旧场景执行器、导演、Avatar、冷热模拟或
Presentation 发布入口。历史代码、测试和旧世界已归档到忽略的 `outputs/experiments/`，
不参与当前编译、运行和回归。

## 调用链

1. `python -m scripts.world create`：
   `community-authoring/v1` 作者 JSON → `build_community_package` →
   `compile_package` → 唯一 `world-package/v1alpha3` 社区包。
2. `python -m engine community`：
   `engine.cli.run_community_package` → 编译世界 → 新建托管配置或恢复预检 →
   `create_run` / `load_run` → `run_managed_community_ticks`。
3. 模型装配：
   `build_application` → `ModelCommunityPolicy` + `OpenAICompatibleTextModel`；
   显式模型配置才调用模型，可选 `JsonlRunStorage` 保存日志。
4. Tick：
   `run_community_ticks` → 世界时间与需求 → 活动、过程与社会结算 →
   本人 `decision_context` → 提案 → 注册动作裁决 →
   `community_events.commit` → `EventLog` → 记忆巩固 → 关闭 Tick。
5. 恢复：
   创建记录绑定世界 hash、引擎指纹、策略与预算 → 日志校验与重放 →
   从未完成 Tick 的事件前缀继续。已记录模型响应复用；未决请求不自动重试。
6. 只读：
   `community-observe` / `community-diagnose` → `load_run` →
   观察、机制诊断和有来源线索；评审工具读取同一历史，不推进世界。

## 归属

- `engine/world/`：作者输入、目录编译、引用与能力校验、世界内容 hash。
- `engine/bootstrap/`：唯一模型与磁盘适配器组合根。
- `engine/adapters/`：模型决策、供应商客户端与 JSONL 存储。
- `engine/runtime/kernel/`：事件、Delta、状态、原子持久化、恢复与 fork。
- `engine/runtime/simulation/community*.py`：社区 Tick、注册动作、物质和时间结算。
- `engine/runtime/character/community*.py`：本人知识、记忆、目标、计划及策略。
- `engine/runtime/space/community_perception.py`：本人实际可见范围。
- `engine/application/community*.py`：观察、机制报告和独立人工评审。
- `engine/narrative/community_threads.py`：只读呈现已经发生且有来源的后果。
- `engine/contracts/`：跨模块不可变契约；共享事件与实体类型不是旧运行入口。

## 世界与产物

正式世界仅有 `worlds/echo-quay`、`worlds/stone-step-commons`、
`worlds/black-pine-ridge`，对应作者源在 `worlds/sources/`。
新增世界统一用作者源构建，不增加专名 builder 或兼容分支。

`tests/` 保留当前契约、安全、原子失败、物质、私人知识和恢复验证。
旧功能专属测试不计入当前回归；不能用历史通过数量声称新版本已验证。
`docs/` 存规范与状态；实验、模型日志、评审材料和回归报告放 `outputs/`。

人物与剧情质量需真实独立人工评审，机制测试不能替代。
