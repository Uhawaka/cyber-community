# ADR-0006：自主运行以可验证 JSONL 作为耐久边界

- 状态：Accepted
- 日期：2026-10-17

## 决策

自主运行的 EventLog 使用逐事件 JSONL 持久化。每行独立携带 schema version、world hash、连续 sequence 和完整 typed event/delta；追加后 flush 到稳定存储，导出通过同目录临时文件原子替换，文件权限固定为 `0600`。

加载默认 fail closed：schema、world hash、sequence、事件校验或任一完整记录损坏都拒绝运行。只有最后一条没有换行且无法解析时，调用方可显式选择 `recover_tail`；损坏尾部会写入私有隔离文件，主日志恢复到最后一条完整事件。

fork 保留不可变事件前缀，在 run metadata 中记录 parent history hash 与 fork sequence。Tick API 返回结构化报告；事件解释 API 直接从 typed history 返回机会、状态前提、规则、确定性游标及移动/共址依据。

## 理由

日志既是恢复输入也是审计证据。把兼容性、世界身份和连续性检查放在加载边界，可以避免“尽力解析”产生不可重放状态；把报告和因果追溯作为事件投影，则不会引入第二套事实源。

## 后果

- 旧调用方若忽略 `run_ticks` / `run_catchup` 返回值，无需修改；依赖返回 run 的代码必须改读 `TickReport`。
- 尾部恢复是显式运维选择，中间损坏不可自动跳过。
- fork 元数据不向父运行追加事件，因此源历史保持不变。

## 验收

重放状态和历史一致；同 seed 历史一致；尾部半写可隔离，中间损坏与 world hash 不匹配被拒绝；导出权限为 `0600`；相遇对话可追溯到前序移动与共址条件。
