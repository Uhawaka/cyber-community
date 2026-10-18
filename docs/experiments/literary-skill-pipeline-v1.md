# EXP-20261017-010：冻结素材的文学 Skill 管线

## 目标

验证文学编辑能否在不推进世界的情况下，以独立专业岗位处理同一份 Digest，
并把失败定位到具体阶段，而不是继续修改世界运行器或扩大总 Prompt。

## 固定输入

- 世界：`black-pine-ridge`
- seed：17
- 输入：`outputs/dramatic-motivation-iteration/round-04-deepseek/presentations.json`
- 来源事件：21
- 输入 SHA-256：
  `b76dbef9ff1adaea4d7a561533f32a743d6513834526abee58924aa2856cad2c`

重渲染入口只复制 PresentationStore，不加载 Event Log，不调用 Tick。

## 管线

```text
developmental-editor-v1
→ scene-writer-v1
→ line-editor-v1
→ fact-continuity-editor-v1
→ Delivery fact/literary gate
```

四个阶段分别加载宿主 `SKILL.md`，中间产物为 `EditorialBrief` 和带段落来源的
`SourcedDraft`。行文编辑无实际修订时定向重试；事实失败时把具体无来源引语或
provenance 诊断返回事实编辑，预算耗尽才确定性回退。

## 结果

- `round-02-deepseek`：四次调用自动通过，但仍偏信息转述。
- `round-03-deepseek`：行文编辑实际改稿后产生无来源短引语，事实门禁回退。
- `round-06-deepseek`：发展编辑删除被后续承诺取代的重复核验；事实编辑仍未在
  预算内修复改写引语，回退。
- `round-07-deepseek`：五次调用，主 Renderer 自动通过，世界未推进；输出和各
  阶段 trace 位于同名目录。

匿名八维评审把第 7 轮评为 58/80，旧基线为 60/80。新稿改善了孙悟空参与和
保管责任交涉，但台词仍偏解释、信息密度偏高、结尾余味不足。结果超过 56/80
技术线，却没有胜过旧稿，因此只能证明机制可执行、可诊断，不能宣称文学质量
已经达到专业标准。

## 结论

世界素材与文学编辑已经能够独立迭代。下一次质量提升应针对发展编辑的省略选择、
潜台词和结尾结构建立多样本盲评，不应修改 Runtime 来迁就单篇文字，也不应放宽
事实门禁换取表面流畅。
