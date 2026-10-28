# 社区运行与恢复

## 创建和运行

使用 `community-authoring/v1` 作者源创建世界包，目标目录必须不存在：

```bash
python -m scripts.world create worlds/sources/stone-step.json \
  --output outputs/experiments/my-community
python -m engine community outputs/experiments/my-community \
  --log outputs/experiments/my-community.jsonl --seed 17 --ticks 12 --json
python -m engine community outputs/experiments/my-community \
  --log outputs/experiments/my-community.jsonl --resume --ticks 12 --json
```

默认使用离线生活策略，不调用模型。每 Tick 为一个模拟小时；`--ticks` 是本次
执行次数。未闭合的 Tick 先继续其已保存进度，不重置预算或重新推进时间。
日志包含私人认知与行动理由，不要公开。

Python 调用可使用 `engine.runtime.simulation.community.run_community_catchup`：
默认最多推进 24 个完整 Tick，超出部分在报告中标记为延后，不以粗略结算替代。
托管运行继续使用已记录的策略与预算。

## DeepSeek

模型配置为 JSON，凭据通过 `DEEPSEEK_API_KEY` 或本地环境文件提供，不写入配置、
日志或仓库。例如：

```json
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "temperature": 0,
    "max_tokens": 1024
  },
  "community_max_requests": 120,
  "community_timeout_seconds": 120
}
```

使用 `--model-config <配置文件>` 显式启用模型；该操作会产生外部请求。新建时可用
`--action-budget` 和 `--memory-budget` 设置每 Tick 上限；续跑继承原有预算，
不得修改模型身份、超时、请求预算、策略版本或引擎源码。源码变化后创建新运行。

当前模型决策以个人感知、Soul、记忆、知识、目标和计划为输入。提示附带本人允许的
来源列表；本人当前可见的声明编号会解析到它的真实来源，不能引用他人的私人知识、
未暴露或已过期的声明。决策只产生行动提案，实际效果仍由规则裁决。

## 恢复和安全

事件以追加方式提交。模型请求、响应和后续行动或拒绝分别持久化：已保存响应可在
恢复后复用，已保存请求但缺少响应时结果不确定，系统拒绝自动重试。
持久化错误会中断运行，不伪装成角色拒绝。`--recover-tail` 仅用于显式恢复不完整
末行，仍须先通过托管配置检查；不应手工改写历史或重置预算。

当前入口只接受当前社区作者和运行契约，不提供旧格式迁移或兼容续跑。世界 hash、
引擎指纹和事件校验不匹配时保留原日志并创建新运行；只读重放也可能拒绝不受支持的
旧历史。

## 观察和评审

```bash
python -m engine community-observe outputs/experiments/my-community \
  --log outputs/experiments/my-community.jsonl --json
python -m engine community-diagnose outputs/experiments/my-community \
  --log outputs/experiments/my-community.jsonl --include-private
python -m scripts.community_model_probe outputs/experiments/my-community \
  --logs outputs/experiments/my-community.jsonl --ticks 12 \
  --output outputs/experiments/my-model-report.json
```

观察、诊断和模型探针只读历史，不调用模型。诊断和模型报告可能包含私人信息；
探针要求完整闭合的 Tick，并检查重放、库存、来源、请求配对和恢复。
模型错误与行动拒绝单独统计，不能视为人物或剧情质量判断。

`python -m scripts.community_quality --help` 列出匿名盲评、私有证据和人工标注入口。
空白评分始终为未评估；角色和剧情评审需真实、独立的人工判断。
`community_review_pack` 和 `community_review_summary` 可处理一个或多个已通过机制门禁的
100 Tick 样本，不强制生成其他 seed；报告中的样本必须唯一且与原始历史一致。
当前阶段优先修复机制，不进行多 seed 扩样；正式 100 Tick 质量门禁通过前不运行
1000 Tick 质量实验。
