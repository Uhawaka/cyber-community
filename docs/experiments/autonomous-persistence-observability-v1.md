# Autonomous persistence / observability v1 实验简记

## 假设

若 JSONL 每行都能独立校验世界身份与 typed event，加载时再经过正常 replay 校验，则进程重启不会改变确定性历史；同时，TickReport 与 CausalTrace 可以只投影事件而不污染运行。

## 方法

- 对 `echo-quay` 固定 seed 创建磁盘运行，执行后加载并继续，两边执行相同 tick。
- 分别注入无换行半条尾记录、完整中间坏记录和错误 world hash。
- 导出 fork，检查权限、parent history hash 与 fork sequence。
- 对由移动后相遇产生的 dialogue 查询 causal trace。

## 结果

- 加载前后 typed events、state 与 history hash 一致；继续执行后仍一致。
- 显式尾恢复隔离坏字节并保留最后完整事件；中间损坏和 world hash 不匹配均 fail closed。
- 导出文件为 `0600`，fork 来源元数据可重新加载。
- tick/catch-up 报告覆盖 tick 范围、请求/执行、详细/粗事件、角色动作、incident/gate、预算与截断。
- dialogue trace 返回 opportunity、pre-state hash、rule basis、target、seed/cursor，并列出前序移动 sequence 与双方共址依据。

判定：passed。
