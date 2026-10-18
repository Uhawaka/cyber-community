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

```bash
cyber-community run worlds/echo-quay
cyber-community run worlds/black-pine-ridge
cyber-community help
cyber-community help run
```

`help` 会列出当前可用的命令。仓库自带的世界包在 `worlds/`。

## 许可

[MIT](LICENSE)
