# World

## 职责
安全读取、验证并确定性编译目录世界包及其 schema。

## 输入
manifest、world、locations、resources、passages 与 character 源文件。

## 输出
`PackageCompileResult`、诊断、能力握手与 `CompiledWorld`。

## 禁止事项
不得依赖 runtime/narrative/application/participation；不得执行作者代码；不得允许越界引用或预编排剧情。

## 公共 API
以 `engine.world` 导出的 package spec 和 `compile_package` 为准。
