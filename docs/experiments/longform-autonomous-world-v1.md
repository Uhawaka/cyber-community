# 长篇自主世界验证 v1

## 结论

状态：**通过运行完整性门禁，文学质量仍需继续提高。**

黑松岭 seed 83 使用 DeepSeek 跑到 20 章。最终报告位于
`outputs/longform/black-pine-ridge-seed83-v5/report-20.json`，故事文档位于同目录
`stories/`。运行在 Tick 54 达到 20 章，没有位置错位、事件断序或 replay 差异。

## 验证口径

- 章节不能由重复环境更新虚构成剧情；
- 角色须依据目标自主离场，经作者声明的通路探索未收束场景；
- 地图位置与 Entity Presence 必须在同一事务更新；
- 已收束场景不得成为来回摆动的剧情目的地，但可以作为前往未决场景的过境点；
- 精确行动签名最多重复 3 次；
- 模型文学回退率不高于 10%；
- Presentation 游标、Episode id、来源事件与 replay 必须连续。

## 失败轮次与机制调整

1. 初始 15 章虽完成发布，却发生 145 次迁移、142 次回访，角色在两个已收束地点
   间摆动；文学回退率为 53.3%。修复方式不是改提示词，而是把已收束目的地移出
   普通离场候选。
2. 移除回摆后，有限的 3 地点、6 场景很快耗尽；后续章节只剩松涛和光线变化。
   Runtime 因此停止演化已收束场景，黑松岭 Workflow 扩展为 8 地点、16 场景的
   征供证据链。
3. 角色分流后会被已收束中间地点隔断。离场器改为在 authored passage 图上寻找
   最近未决地点，允许把已收束地点仅作为过境节点。
4. 模型场景曾提交不属于 Scene Layout 的入口/NPC 锚点。Blueprint 校验现要求
   入口和所有 Presence 锚点都属于声明的 Layout，失败时回退到安全生成器。
5. 文学回退本身也曾因逐事件段落形态被门禁拒绝。确定性回退现在合并相邻 beat，
   保留完整来源但不再一事件一段；模型回退章节会在后续 chunk 自动重渲染。

## 20 章结果

- Episode：20，停止原因 `target_episodes_reached`
- Tick：54；Event：340；未发布事件：0
- 地点覆盖：6；场景覆盖：12
- 跨地点迁移：14；回访：1
- 最大完整角色精确行动重复：1
- `dramatic_progress=none`：20.47%
- 已收束后无合法离场：0
- 位置同步违规：0
- replay：一致
- 当前文学回退：1 / 20，5%；另一章经来源不变的段落合并与重渲染恢复

20 章报告的 `longrun_validation.passed=true`。这证明当前 Workflow 与 Runtime
能够形成一次有限但连续的自主探索，不证明已经达到专业长篇小说水平。一章仍依赖
事实安全回退，且本轮只实际覆盖 8 个地点中的 6 个；后续文学迭代应修复来源顺序
异常并继续降低回退率，而不是放宽事实或文学门禁。

## 复现

使用同一 `events.jsonl`、`presentations.json`、seed 83 和无密钥
`model-config.json`：

```bash
PYTHONPATH=. python scripts/world.py longform worlds/black-pine-ridge \
  --target-episodes 20 --max-ticks 80 --chunk-ticks 5 --seed 83 \
  --gate-choice bank-the-embers \
  --model-config outputs/longform/black-pine-ridge-seed83-v5/model-config.json \
  --output outputs/longform/black-pine-ridge-seed83-v5/report-20.json \
  --run-output outputs/longform/black-pine-ridge-seed83-v5/events.jsonl \
  --presentation-output outputs/longform/black-pine-ridge-seed83-v5/presentations.json \
  --story-output-dir outputs/longform/black-pine-ridge-seed83-v5/stories \
  --resume
```
