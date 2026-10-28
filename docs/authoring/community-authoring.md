# 统一世界创建

社区世界采用一个数据源和一个构建入口，不为每个世界编写 Python 构建脚本，
不维护旧作者格式或旧 revision 的转换分支。

## 创建

当前完整作者例子：

- [回声码头](../../worlds/sources/echo-quay.json)
- [石阶院](../../worlds/sources/stone-step.json)
- [黑松岭](../../worlds/sources/black-pine-ridge.json)

复制一份作者数据，修改世界、人物、地图和规则后，指定一个不存在的新目录：

```bash
python -m scripts.world create worlds/sources/stone-step.json \
  --output worlds/my-community
```

成功时输出编译后的 package id、revision、content hash 和实体摘要。
构建器只负责写出目录和编译校验，不运行社区、不调用模型、不补写人物或剧情。
修改包身份和 revision 直接修改数据，不需要注册 Python 分支。

## 作者数据

顶层是 `community-authoring/v1` JSON，必须完整提供以下字段：

- `schema_version`：固定 `community-authoring/v1`。
- `package_id`：安全目录标识符。
- `revision`：正整数，仅标记数据版本，不选择执行代码。
- `world`：世界 id、标题、前提、规则及 experience profile。
- `locations`、`resources`、`passages`：完整对象数组，通路显式有向。
- `relationships`：关系边数组。
- `characters`：以角色 id 为键；每人必须有 `profile`、`soul`、`memory`。
- `community`：生活、维修、学习、物质过程与组织的注册规则。
- `workflows`：完整的 genesis、evolution、intervention、presentation 定义。

字段语义沿用[目录世界包格式](world-graph.md)及[社区运行指南](community-runtime.md)。
manifest、capabilities 和固定目录布局由构建器生成，作者不能提供文件路径、
动态导入、脚本或任意规则 DSL。作者文本只是数据，不会被执行。
无需外部模板、旧世界文件或角色专名判断；技能与服务依赖必须在数据中声明。

`community.public_knowledge` 表示作者指定的社区初始常识，每条为不超过 2000
字符的文本，最多 32 条。每个作者角色以有来源的初始信念获得它，知识检索仍有
条数与字符预算；不要在这里填写秘密、未发生的事件或要求角色自动掌握的技能。
公共常识不改变权威世界事实，也不代表角色阅读了某份具体档案。

## 校验与发布

构建器先在目标父目录下的私有临时目录写包，再调用同一个 `compile_package`。
未知字段、重复 JSON 键、过大/过深输入、非法角色目录名、缺少资产、
非法引用及不支持的注册规则都拒绝。缺失信息不会由模型猜测。

编译通过后以不可覆盖的原子重命名发布完整目录。目标父目录须预先存在，
任何已有目标，包括空目录和坏符号链接，都不会被替换；写入或编译失败会清理临时目录。
发布支持 macOS/Linux 的原生 no-replace 重命名；缺少该能力时直接报错，
不退回到可能覆盖现有路径的行为。

已有 Event Log 不会自动换用新定义。创建新世界不删除历史数据、重置运行 Tick，
也不把版本迁移伪装成继续旧运行。

## 产出位置

作者 JSON 是正式输入，位于 `worlds/sources/`；可运行世界包位于 `worlds/`。
正式包分别为 `echo-quay`、`stone-step-commons` 和 `black-pine-ridge`。
实验 JSON、日志和报告写入 `outputs/experiments/`，测试报告写入 `outputs/tests/`。
`docs/` 只保存规范与开发记录，冻结回归输入仍位于 `tests/fixtures/`。

## 岗位示例

组织岗位与成员、个人库存、设备照管职责相互独立：

```json
{
  "organization_id": "name-keepers",
  "name": "留名校记小组",
  "location_id": "merit-ash-archive",
  "member_ids": ["bailing", "traveler", "zhu"],
  "norms": ["来源与判断分开。"],
  "roles": [{
    "role_id": "archivist",
    "name": "校记值守",
    "required_skills": ["校记档案"],
    "permissions": ["censure"],
    "initial_holder_id": "zhu"
  }]
}
```

每组织最多16岗位，role_id唯一；初始持有人必须是成员且具有真实初始技能。
未注册权限拒绝，省略 initial_holder_id 表示空缺。学习、作者愿望或岗位文字
不自动任命人物；后续只能本人在现场主动接任或卸任。
规范文字也不自动变成引擎处罚规则。行为与边界见[运行指南](community-runtime.md)。

黑松岭的社区包包含八地点和六位角色；不导入旧日志、场景倒计时或导演动作。
