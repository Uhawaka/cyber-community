# 赛博社区 · Cyber Community

> 不是 AI 帮你做事，是一群 AI 帮你思考，你随时旁听。

定义一个领域和几个角色，社区自己生活、阅读、争论、演化。你可以用马甲不定期进去聊，或让「向导」帮你看近况；觉得不够有趣，就改 `worlds/*/community.yaml` 设定。

## 安装

```bash
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=...
# 加载优先级: 项目 .env > 环境变量 > ~/.hermes/.env
```

可用世界：`math-commune` · `quant-lab` · `poets-salon` · `philosophy-cafe` · `alien-observers`

## 运行命令

### 实验批跑（`main.py`）

快进若干虚拟天，打完日报退出。适合调试设定、CI、一次性注入事件。

```bash
# 默认 math-commune，跑 1 天
python main.py

# 指定世界 / 天数 / 实时事件流
python main.py --world math-commune --days 1 --watch
python main.py --world poets-salon --days 3 --watch

# 注入匿名事件后再跑（角色不知来源）
python main.py --message "桌上出现一篇关于 L-function pair correlation 的短注"
python main.py --message "Elias 桌上出现一封信" --to Elias --framing letter

# 跑完只看摘要
python main.py --days 1 --digest

# 固定随机种子
python main.py --days 1 --seed 42
```

| 参数 | 说明 |
|------|------|
| `--world` | 世界名（默认 `math-commune`） |
| `--days` | 虚拟天数（默认 `1`） |
| `--watch` | 实时输出事件流 |
| `--digest` | 运行后打印角色/社区摘要 |
| `--message` | 注入匿名事件 |
| `--to` | 事件只让某角色察觉 |
| `--framing` | `letter` / `coincidence` / `environment` / `rumor` / `discovery` |
| `--seed` | 随机种子 |

### 常驻社区（`live.py`）

墙钟预算窗口内推进生活（节律 + Poisson/spontaneous）；进程挂着，你随时用 REPL 进出。默认唤醒点 `09:30,14:00,21:00` 只控 token，对体验不重要。

```bash
# 常驻进入（马甲 Alex）
# 若该世界还没过过虚拟日，会先建档并跑完第一天，再挂起等墙钟窗口
# 存档固定在仓库 outputs/<world-id>/（与从哪启动无关，不用 ~/outputs）
python live.py
python live.py --world math-commune --as Alex

# 带简介 / 启动后立刻跑一窗（不用等日历）
python live.py --as Alex --bio "独立研究者，偶尔路过"
python live.py --as Alex --wake-now

# 调整生活窗口与每窗预算（一般不必改）
python live.py --wake-times 09:30,14:00,21:00 \
  --virtual-hours-per-wake 8 --max-events-per-wake 40

python live.py --seed 42 --wake-now
```

| 参数 | 说明 |
|------|------|
| `--world` | 世界名（默认 `math-commune`） |
| `--as` | 马甲名字（默认 `Alex`） |
| `--bio` | 马甲短简介 |
| `--wake-times` | 墙钟窗口 `HH:MM,...` |
| `--virtual-hours-per-wake` | 每窗推进的虚拟小时（默认 `8`） |
| `--max-events-per-wake` | 每窗最多 DES 事件数（默认 `40`） |
| `--wake-now` | 启动后立刻跑一窗 |
| `--seed` | 随机种子 |

进入后 REPL 示例：

```text
最近大家在忙什么？              # 问向导（旁观解说）
ask 有什么值得看的争论吗？
@Elias 你现在卡在哪？           # 马甲跟成员聊
urgent @Yuki 借一步说句话       # 对方 Busy 时挂起工作再聊
focus Nora                      # 之后裸输入默认对 Nora
focus clear                     # 回到向导
event 黑板上多了一行奇怪的公式
wake                            # 立刻再跑一窗
status / digest / quit
```

| REPL | 说明 |
|------|------|
| 裸输入 / `ask …` | 向导 agent 根据快照汇报（日常看情况用这个） |
| `@Name …` / `talk` | 以马甲与成员对话 |
| `urgent @Name …` | 挂起对方工作 → 聊完恢复 |
| `focus` / `unfocus` | 裸输入改聊成员 / 回到向导 |
| `wait` | 等成员空闲 |
| `status` / `who` / `digest` / `soul` / `papers` | 原始快照（调试） |
| `event …` | 匿名扰动 |
| `wake` / `nextwake` / `quit` | 立刻跑窗 / 看下一窗 / 退出 |

## 测试

```bash
python tests/test_core.py
python tests/test_live_session.py
python tests/test_soul_v2.py
python tests/test_language.py
python tests/test_culture.py
python tests/test_environment_missions.py

# 无 API 的 3 天 DES 冒烟（verbose）
python tests/smoke_engine.py
```

## 项目结构

```
cyber-community/
├── main.py                 # 实验批跑
├── live.py                 # 常驻 + 马甲 / 向导 REPL
├── engine/                 # DES 引擎
│   ├── live_session.py     # 墙钟窗口 + REPL + 向导
│   ├── sim_lifecycle.py    # run / run_slice / 日界
│   └── ...
├── worlds/                 # 社区 YAML
├── docs/                   # contracts / authoring / templates
└── outputs/                # 运行存档（固定仓库内 outputs/<world-id>，gitignore）
```

## 文档

- [DESIGN.md](DESIGN.md) — 产品与架构
- [docs/contracts/](docs/contracts/) — Soul / Memory / 语言约定
- [docs/authoring/](docs/authoring/) — 世界与角色写作
- [docs/templates/](docs/templates/) — 可复制模板

## License

MIT — 见 [LICENSE](LICENSE)。
