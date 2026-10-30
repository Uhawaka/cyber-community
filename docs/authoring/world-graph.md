# 社区世界包

社区世界以 `community-authoring/v1` JSON 为唯一作者输入，通过
`python -m scripts.world create` 生成 `world-package/v1alpha3` 目录。
完整字段与创建方式见[统一世界创建](community-authoring.md)。

正式世界和作者源：

- 回声码头：`worlds/echo-quay/`，源为 `worlds/sources/echo-quay.json`。
- 石阶院：`worlds/stone-step-commons/`，源为 `worlds/sources/stone-step.json`。
- 黑松岭：`worlds/black-pine-ridge/`，源为 `worlds/sources/black-pine-ridge.json`。
- 青衡院：`worlds/qingheng-academy/`，源为 `worlds/sources/qingheng-academy.json`。
- 李氏族院：`worlds/li-clan-court/`，源为 `worlds/sources/li-clan-court.json`。
- 黑风寨：`worlds/black-wind-stockade/`，源为 `worlds/sources/black-wind-stockade.json`。

包包含 manifest、世界、地点、通路、资源、人物、关系、社区规则和注册工作流。
所有引用与能力在编译时验证；作者文本不会被执行，缺失字段不会由模型补齐。
世界包必须显式声明体验配置，不自动合成旧格式配置。

运行、恢复和只读观察见[社区运行指南](community-runtime.md)。世界内容变化后，
已有托管运行不能静默切换到新定义，应保留历史并新建运行。
