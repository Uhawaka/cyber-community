#!/usr/bin/env python3
"""常驻社区入口 — 墙钟生活窗口 + 马甲 REPL。

实验 / 快进批跑请用 main.py。
"""

from __future__ import annotations

import argparse
import random
import signal
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.llm import LLM
from engine.engine import SimulationEngine
from engine.live_session import LiveSession, parse_wake_times
from engine.world_builder import expand_world
import yaml


def load_config(world_name: str) -> dict:
    config_path = PROJECT_ROOT / "worlds" / world_name / "community.yaml"
    if not config_path.exists():
        print(f"❌ 找不到世界: {world_name}")
        available = list((PROJECT_ROOT / "worlds").glob("*/community.yaml"))
        if available:
            print(f"   可用: {', '.join(p.parent.name for p in available)}")
        sys.exit(1)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if raw.get("format_version") == "2.0":
        raw = expand_world(raw)
    return raw


def main():
    parser = argparse.ArgumentParser(
        description="赛博社区常驻模式 — 成员按墙钟窗口过日子，你以马甲进出"
    )
    parser.add_argument("--world", default="math-commune", help="世界名称")
    parser.add_argument("--as", dest="avatar", default="Alex", help="马甲名字")
    parser.add_argument("--bio", default="", help="马甲短简介")
    parser.add_argument(
        "--wake-times",
        default="09:30,14:00,21:00",
        help="墙钟生活窗口（HH:MM,...），对用户透明，仅控 token 预算",
    )
    parser.add_argument(
        "--virtual-hours-per-wake",
        type=float,
        default=8.0,
        help="每个窗口推进的虚拟小时数（默认 8，三窗≈一天）",
    )
    parser.add_argument(
        "--max-events-per-wake",
        type=int,
        default=40,
        help="每个窗口最多处理的 DES 事件数",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--wake-now",
        action="store_true",
        help="启动后立刻跑一个生活窗口（不必等日历）",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    config = load_config(args.world)
    world_name = (
        config.get("name")
        or (config.get("meta") or {}).get("name")
        or args.world
    )
    wake_times = parse_wake_times(args.wake_times)

    print(f"🏠 赛博社区 · 常驻 · {world_name}")
    print(f"   成员: {', '.join(c['name'] for c in config['characters'])}")
    print(f"   马甲: {args.avatar}" + (f" — {args.bio}" if args.bio else ""))
    print(
        f"   生活窗口(墙钟): "
        + ", ".join(f"{h:02d}:{m:02d}" for h, m in wake_times)
        + "  （你不必关心；社区在窗内自己转）"
    )
    print("   直接打字问「向导」看近况；@Name 跟成员聊；help / quit\n")

    llm = LLM(config)
    engine = SimulationEngine(config, llm)
    session = LiveSession(
        engine,
        avatar_name=args.avatar,
        avatar_bio=args.bio,
        wake_times=wake_times,
        virtual_hours_per_wake=args.virtual_hours_per_wake,
        max_events_per_wake=args.max_events_per_wake,
    )

    def _shutdown(signum, frame):
        print("\n…收到信号，正在停下生活窗口")
        session.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    session.start()
    if args.wake_now:
        stats = session.force_wake()
        print(
            f"（已预跑一窗: {stats['processed']} 事件, "
            f"t={stats['clock']:.1f}, Day {stats['day']}）\n"
        )

    try:
        while True:
            try:
                line = input(session.prompt())
            except EOFError:
                print()
                break
            reply, should_quit = session.handle_line(line)
            if reply:
                print(reply)
            if should_quit:
                break
    finally:
        session.stop()
        print("已退出常驻模式。实验批跑请用: python main.py --days 1")


if __name__ == "__main__":
    main()
