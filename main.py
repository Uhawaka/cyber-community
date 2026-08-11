#!/usr/bin/env python3
"""
赛博社区 · Cyber Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

用法:
  python main.py                         # 运行 1 天 + 日报
  python main.py --days 7                # 运行 7 天 + 周报
  python main.py --world math-commune    # 指定世界
  python main.py --watch                 # 运行并实时输出
  python main.py --digest                # 只看最新日报
"""

import sys
import os
import yaml
import argparse
import random
from pathlib import Path
from datetime import datetime

# Ensure real-time output — no buffering in --watch mode
sys.stdout.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.llm import LLM
from engine.engine import SimulationEngine
from engine.world_builder import expand_world


def load_config(world_name: str, auto_expand: bool = True) -> dict:
    config_path = PROJECT_ROOT / "worlds" / world_name / "community.yaml"
    if not config_path.exists():
        print(f"❌ 找不到世界: {world_name} ({config_path})")
        available = list((PROJECT_ROOT / "worlds").glob("*/community.yaml"))
        if available:
            print(f"   可用世界: {', '.join(p.parent.name for p in available)}")
        sys.exit(1)
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    
    # Auto-expand minimal configs to full psychology models
    if auto_expand and raw.get("format_version") == "2.0":
        raw = expand_world(raw)
    
    return raw


def generate_digest(engine: SimulationEngine, period: str = "daily") -> str:
    """Generate a daily or weekly digest from the event log."""
    
    collisions = [e for e in engine.event_log if e["type"] == "collision"]
    studies = [e for e in engine.event_log if e["type"] == "study_step"]
    
    # Collect collision highlights
    highlights = []
    for c in collisions[-5:]:  # last 5 collisions
        dialogue = c.get("dialogue", "")
        if dialogue:
            first_line = dialogue.split("\n")[0] if dialogue else ""
            highlights.append(f"{c['initiator']} ↔ {c['target']}: {first_line[:100]}")

    highlight_text = "\n".join(f"  · {h}" for h in highlights[-8:]) if highlights else "  (无对话记录)"

    system = "你是社区的观察者。写中文。风格像晚报，有幽默感。"
    prompt = f"""社区「{engine.config.get('name', '')}」运行了 {engine.day - 1} 天。

统计: {len(collisions)} 次碰撞, {len(studies)} 次研究步骤。

对话亮点:
{highlight_text}

角色状态:
{chr(10).join(f'  {n}: 能量{c.state.energy}/{c.state.energy_max}, 状态{c.state.status}' for n, c in engine.characters.items())}

社区动态:
{engine.sociology.get_community_snapshot()}

写一份{period}报（200字以内）：
1. 今日/本周话题 — 大家主要在讨论什么？
2. 最精彩发言 — 引用一句最妙的话
3. 火花瞬间 — 有没有特别有趣的碰撞？
4. 明日/下周看点"""

    return engine.llm.chat(
        [{"role": "user", "content": prompt}],
        system=system,
        temperature=0.7,
    )


def main():
    parser = argparse.ArgumentParser(description="赛博社区 — AI角色社区引擎")
    parser.add_argument("--world", default="math-commune", help="世界名称")
    parser.add_argument("--days", type=int, default=1, help="运行天数")
    parser.add_argument("--watch", action="store_true", help="实时输出")
    parser.add_argument("--digest", action="store_true", help="只看最新日报")
    parser.add_argument("--seed", type=int, default=None, help="随机种子")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    config = load_config(args.world)
    world_name = config.get("name", args.world)

    print(f"🚀 赛博社区 · {world_name}")
    print(f"   角色: {', '.join(c['name'] for c in config['characters'])}")
    print(f"   运行: {args.days} 天\n")

    llm = LLM(config)
    engine = SimulationEngine(config, llm)
    engine.run(max_days=args.days, verbose=args.watch or args.days <= 1)

    if args.digest:
        # Show latest digest from archive
        for name, archive in engine.archives.items():
            ctx = archive.get_recent_context(1)
            if ctx:
                print(f"\n📝 {name} 昨日摘要: {ctx}")
        return

    # Generate digest using production pipeline
    print(f"\n{'='*50}")
    period = "周" if args.days >= 7 else "日"
    print(f"📋 {period}报 (基于 {len(engine.production.artifacts)} 件产出)...")
    digest = engine.production.generate_digest("weekly" if args.days >= 7 else "daily")
    print(digest)

    # Save digest
    output_dir = PROJECT_ROOT / "outputs" / args.world
    output_dir.mkdir(parents=True, exist_ok=True)
    digest_path = output_dir / f"digest_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(digest_path, "w") as f:
        f.write(f"# {config.get('meta', {}).get('name', world_name)} · {period}报\n\n")
        f.write(f"_{datetime.now().strftime('%Y年%m月%d日')}_\n\n")
        f.write(digest)
        f.write(f"\n\n---\n*运行 {args.days} 天, {len(engine.event_log)} 事件, {len(engine.production.artifacts)} 件产出*")
        f.write(f"\n\n## 制品列表\n")
        for art in engine.production.get_recent(20):
            f.write(f"\n- **[{art.type}]** {art.title} ({', '.join(art.authors)}, Day{art.created_day})")

    print(f"\n📁 {period}报已保存: {digest_path}")
    print(f"📊 产出: {len(engine.production.artifacts)} 件 (papers: {len(engine.production.get_by_type('paper'))}, insights: {len(engine.production.get_by_type('insight'))})")


if __name__ == "__main__":
    main()
