# 赛博社区

用一个目录描述世界，让它按自己的规则运行，并把已经发生的事写成可以阅读的文字。

## 安装

需要 Python 3.10 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 使用

创建并运行社区，使用离线策略，不调用外部模型：

```bash
python -m scripts.world create worlds/sources/stone-step.json --output worlds/my-community
cyber-community community worlds/my-community --log outputs/experiments/my-community.jsonl --seed 7 --ticks 12
cyber-community community worlds/my-community --log outputs/experiments/my-community.jsonl --resume --ticks 12
cyber-community community-observe worlds/my-community --log outputs/experiments/my-community.jsonl --json
```

调用模型时加上 `--model-config config/model.json`。供应商、模型名、地址和密钥只写在
`.env`（见 `.env.example`），不要写进配置文件。

创建目标须不存在；日志包含角色私有信息，不应直接公开。运行及恢复边界见
[社区运行指南](docs/authoring/community-runtime.md)，世界创作见
[统一世界创建](docs/authoring/community-authoring.md)。人物、剧情与真实模型质量尚未验收。

`cyber-community help` 列出可用命令。统一作者源在 `worlds/sources/`。

## 许可

[MIT](LICENSE)
