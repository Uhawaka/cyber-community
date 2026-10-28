# World

## 职责
安全读取、验证并确定性编译目录世界包及其 schema；从统一作者 JSON 创建社区包。

## 输入
manifest、world、locations、resources、passages 与 character 源文件。

## 输出
`PackageCompileResult`、诊断、能力握手与 `CompiledWorld`。

## 禁止事项
不得依赖 runtime/narrative/application/participation；不得执行作者代码；不得允许越界引用或预编排剧情。

## 公共 API
以 `engine.world` 导出的 package spec、`compile_package`、`load_community_source`
和 `build_community_package` 为准。世界内容写在 `worlds/sources/` 的数据中，
不为世界专名或旧 revision 增加构建分支。
