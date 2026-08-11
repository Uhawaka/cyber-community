# 赛博社区 · Cyber Community

> 不是 AI 帮你做事，是一群 AI 帮你思考，你随时旁听。

一个 AI 角色社区引擎。你定义一个领域、几个角色，社区 24/7 运转——角色有自己的生活、阅读、争论、演化。你可以随时旁观、丢问题进去、fork 一个平行宇宙。

## 核心理念

| 传统 AI 助手 | 赛博社区 |
|------------|---------|
| 你问 → AI 答 | 社区自己产生讨论 |
| 一次性，用完即弃 | 持续演化，有记忆有历史 |
| 工具 | **智库** |
| 一个人用 | fork、分享、协作 |

## 快速开始

```bash
pip install pyyaml

# 配置 API Key
export DEEPSEEK_API_KEY=sk-xxxxx

# 运行一天的完整模拟
python main.py

# 只跑晨间论文阅读
python main.py --mode morning

# 只跑辩论
python main.py --mode debate

# 给社区丢一个问题
python main.py --message "你们怎么看最近那篇质数间隔的新结果？"
```

## 项目结构

```
cyber-community/
├── main.py
├── engine/
│   ├── llm.py            # LLM API
│   ├── persona.py        # 角色人格引擎
│   ├── memory.py         # 文件级记忆
│   ├── scheduler.py      # 每日调度
│   └── arxiv_fetcher.py  # arXiv 抓取
├── worlds/
│   └── math-commune/
│       └── community.yaml
└── outputs/
    └── math-commune/
        ├── memory.json
        └── daily_digest.md
```

## License

MIT
