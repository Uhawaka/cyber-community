# 配置驱动体验契约 v1

日期：2026-10-17

## 目的

验证世界运行机制与文学表达可以由世界包配套选择，而不在执行器中加入世界、
角色或题材分支。

## 纵切

- 黑松岭：`demythologized-dark-myth` +
  `scene-pressure-v1` + `demythologized-dark-myth-v1`；
- 回声码头：`mystery` + `scene-pressure-v1` +
  `restrained-mystery-v1`；
- 临时第三世界 fixture：只替换配置，选择 `neutral-observer-v1`，不修改引擎。

黑松岭的类型承诺定义为“去魅式黑暗神话 / 神权政治悬疑 / 道德灰度志怪”。
它通过世界规则、场景物证、角色动机、类型发展编辑 Skill 与通用 Voice 配套实现；
具体制度痕迹和角色声音留在世界包，宿主 catalog 不含示例专名。

## 自动证据

- 全量测试通过；
- 两个世界分别完成 8 seed × 20 Tick probe，replay、知识来源、地图、资源、
  对话共址及事件约束全部通过，均得到 8 个唯一历史 hash；
- 双世界发布与独立重渲染保持来源事件不变；
- ExperienceProfile 的未知 mode/bundle/Skill/Voice、未知角色引用、旧配置冲突、
  不完整场景压力素材均 fail closed；
- `compileall`、`git diff --check`、架构导入边界、500 行模块门禁通过；
- `engine/` 对两个示例世界 ID 和示例角色 ID 的静态扫描无命中。

## 结论与限制

配置替换、编译隔离和执行兼容已验证。黑松岭与回声码头共享同一通用运行模式，
但得到不同 EditorialContract、Voice、Episode 策略和编辑 Skill。

该结果不等于文学质量达标。确定性重渲染只能证明事实与契约；类型专项 Skill
仍需在冻结 Digest 上进行模型 A/B、盲评和多 seed 素材质量评估。世界运行 probe
也尚未证明 100–1000 Tick 的长期剧情连续性。
