# ADR-0007：资产与受限工作流分离

- 状态：Accepted
- 日期：2026-10-17

## 决策

`world-package/v1alpha2` 将 manifest 分为 `assets` 与 `workflows`。前者只引用
world、locations、characters、resources、passages；后者只引用 genesis、
evolution、intervention、presentation。

编译器把四类工作流编译成 typed `WorkflowIR`。每个工作流只有注册表允许的
op 和 policy；未知项、kind 不匹配、非法顺序或不安全引用均 fail closed。
所有资产和工作流语义共同参与 `CompiledWorld.content_hash`。

Runtime 从 `CompiledWorld.workflow` 派生默认模拟、介入和呈现策略，不直接读取
作者文件。`v1alpha1` 不再兼容。

## 理由

资产描述世界中“有什么”，工作流描述宿主“如何执行”。把资产称为 workflow
掩盖了执行语义，也导致运行时把工作流仅当引用保存，无法验证预算、衰减、权限
和呈现策略是否真正生效。

## 后果

- 包必须提供全部五类资产引用和四类工作流。
- evolution 顺序固定且可验证，不能注入任意 DSL 或代码。
- incident、UserGate、Fate 由 intervention 显式授权。
- 默认 DeliveryPolicy 和 SimulationPolicy 是包 hash 的一部分，修改后会形成
  不同的可回放世界输入。
