# EXP-20261018-001：征供链按地点分层

## 元数据

- 状态：passed（世界包假设成立；离场补丁有一条回归，呈现仍有一章失败）
- 日期：2026-10-18
- 世界包：`worlds/black-pine-ridge`（本轮正文）；`echo-quay` 只经全量测试编译，未跑长篇
- 模型：DeepSeek，temperature 0.35，max_tokens 3000；角色/场景/裁决超时 60 秒，交付 90 秒
- RNG seed：83
- 用户门：`bank-the-embers`
- 历史哈希（评估这一次）：`061d765a13df3e070a0fac0f9b0d68ffad9fa12d5356ce597c3caa551a32467b`
- 复现命令：

```bash
PYTHONPATH=. python scripts/world.py longform worlds/black-pine-ridge \
  --target-episodes 4 --max-ticks 24 --chunk-ticks 4 --seed 83 \
  --gate-choice bank-the-embers \
  --model-config outputs/longform/black-pine-ridge-seed83-leave/model-config.json \
  --output outputs/longform/black-pine-ridge-seed83-leave/report.json \
  --run-output outputs/longform/black-pine-ridge-seed83-leave/events.jsonl \
  --presentation-output outputs/longform/black-pine-ridge-seed83-leave/presentations.json \
  --story-output-dir outputs/longform/black-pine-ridge-seed83-leave/stories
```

## 单一假设

如果每一处只写征供链的一层，角色的志向大到一间屋子完不成，那么新目录里的正文不会在门口写出窑、天衡或灰库，并且会有人走到林间和废驿。否则先改世界包，不改调度和分章。

## 范围

- 包含：黑松岭 premise、地点场景问题、三个角色的志向、残火观察、演化阶段未闭合项。
- 不包含：回声码头行为、按集数切章、文学质量评分。
- 固定不变项：调度链、分章器、事件日志回放。只有模拟证明“这一层已经回答过，人还是走不出去”时才改离场。

## 两次运行

第一次只改世界包，目录 `outputs/longform/black-pine-ridge-seed83-chain/`，历史 `fdc43e280662d793deae38187bf29141cdfbeccce8bc9f0d08f053d121208694`。8 tick，3 章，地点只有后门和林间。林间采药人已经说出粉在哪一侧，孙悟空的决定是“沿粉痕较完整的一侧离开小路”，`scene_transition` 仍为空，随后在同一条石路上重复迈步。假设的后半不成立，触发离场补丁。

补丁在 `engine/runtime/scene/dispatch.py`：当前回合的决定或目标里有“离开”，并且这一处已经有别人说过的话，裁决又没有给出转移时，沿已有通路去一个还没去过的相邻地点。没有别人回答过，则留在原地。测试：`test_a_spent_layer_turns_leaving_into_the_next_place`、`test_leaving_before_anyone_answers_stays_in_place`。

第二次目录 `outputs/longform/black-pine-ridge-seed83-leave/`。12 tick，4 章，4 个地点。沈砚的路径是后门 → 林间小路 → 征供废驿（tick 12 的 `moved`，目的地 `levy-outpost`）。白灵和孙悟空去了破庙大殿。四章正文都没有出现窑、天衡、灰库、铜衡或索桥。

## 仍未解决

- 第 3 章不是双人对话，文学门禁失败后回退，标题和正文露出 `scene:ruined-temple`，同一句说了两遍。`fallback_rate` 0.25。
- 白灵在 tick 7 把破庙大殿收束之后没有离场（`resolved_without_egress`）。她要去的是庙内深处，不是下一路口。
- 沈砚在林间把粉的方向问了第二遍，NPC 回答没有新内容，然后才离开。同一层没有再查第三遍。
