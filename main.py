#!/usr/bin/env python3
"""
赛博社区 · Cyber Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用法:
  python main.py                              # 运行 1 天 + 日报
  python main.py --days 7                     # 运行 7 天 + 周报
  python main.py --world math-commune         # 指定世界
  python main.py --watch                      # 实时输出
  python main.py --digest                     # 只看最新角色摘要
  python main.py --message "桌上出现一篇论文"  # 注入匿名事件后运行
"""

import sys
import argparse
import random
from pathlib import Path
from datetime import datetime

# Ensure real-time output — no buffering in --watch mode
sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.llm import LLM
from engine.engine import SimulationEngine
from engine.world_builder import load_world


def main():
    parser = argparse.ArgumentParser(description="赛博社区 — AI角色社区引擎")
    parser.add_argument("--world", default="math-commune", help="世界名称")
    parser.add_argument("--days", type=int, default=1, help="运行天数")
    parser.add_argument("--watch", action="store_true", help="实时输出")
    parser.add_argument("--digest", action="store_true", help="只看最新日报/角色摘要")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    parser.add_argument(
        "--message",
        default=None,
        help="向社区注入匿名事件（角色不知来源）",
    )
    parser.add_argument(
        "--to",
        default=None,
        dest="message_target",
        help="匿名事件只让某角色察觉（配合 --message）",
    )
    parser.add_argument(
        "--framing",
        default=None,
        choices=["letter", "coincidence", "environment", "rumor", "discovery"],
        help="匿名事件包装方式（默认随机）",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    try:
        config = load_world(args.world, PROJECT_ROOT / "worlds")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        available = list((PROJECT_ROOT / "worlds").glob("*/community.yaml"))
        if available:
            print(f"   可用世界: {', '.join(p.parent.name for p in available)}")
        sys.exit(1)
    world_name = (
        config.get("name")
        or (config.get("meta") or {}).get("name")
        or args.world
    )

    print(f"🚀 赛博社区 · {world_name}")
    print(f"   角色: {', '.join(c['name'] for c in config['characters'])}")
    print(f"   运行: {args.days} 天\n")

    llm = LLM(config)
    engine = SimulationEngine(config, llm)

    if args.message:
        framed = engine.inject_anonymous_event(
            args.message,
            target=args.message_target,
            framing=args.framing,
            verbose=True,
        )
        print(f"   （角色将以自然方式感知，不会知道是你注入的）\n")

    engine.run(max_days=args.days, verbose=args.watch or args.days <= 1)

    if args.digest:
        for name, archive in engine.archives.items():
            ctx = archive.get_recent_context(1)
            if ctx:
                print(f"\n📝 {name} 昨日摘要: {ctx}")
        snap = engine.society.get_community_snapshot()
        if snap:
            print(f"\n🏛 社区快照:\n{snap}")
        return

    print(f"\n{'='*50}")
    period = "周" if args.days >= 7 else "日"
    print(f"📋 {period}报 (基于 {len(engine.production.artifacts)} 件产出)...")
    digest = engine.production.generate_digest("weekly" if args.days >= 7 else "daily")
    # Append sociology snapshot for richer observer report
    snap = engine.society.get_community_snapshot()
    if snap:
        digest = f"{digest}\n\n---\n社区动态:\n{snap}"
    print(digest)

    output_dir = engine._output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    digest_path = output_dir / f"digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(digest_path, "w") as f:
        f.write(f"# {config.get('meta', {}).get('name', world_name)} · {period}报\n\n")
        f.write(f"_{datetime.now().strftime('%Y年%m月%d日')}_\n\n")
        f.write(digest)
        f.write(f"\n\n---\n*运行 {args.days} 天, {len(engine.event_log)} 事件, {len(engine.production.artifacts)} 件产出*")
        if args.message:
            f.write(f"\n*本轮注入匿名事件: {args.message}*")
        f.write(f"\n\n## 制品列表\n")
        for art in engine.production.get_recent(20):
            f.write(f"\n- **[{art.type}]** {art.title} ({', '.join(art.authors)}, Day{art.created_day})")

    print(f"\n📁 {period}报已保存: {digest_path}")
    print(
        f"📊 产出: {len(engine.production.artifacts)} 件 "
        f"(papers: {len(engine.production.get_by_type('paper'))}, "
        f"insights: {len(engine.production.get_by_type('insight'))})"
    )


if __name__ == "__main__":
    main()
