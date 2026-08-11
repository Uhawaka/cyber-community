#!/usr/bin/env python3
"""Dry-run DES smoke: 3 virtual days, NoopLLM, no external APIs.

Manual:  python tests/smoke_engine.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.engine import SimulationEngine
from engine.world_builder import expand_world

random.seed(42)


class NoopLLM:
    def chat(self, *args, **kwargs):
        return "[decision simulated]"

    def think(self, *args, **kwargs):
        return "[thinking simulated]"


def main():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    config = expand_world(raw) if raw.get("format_version") == "2.0" else raw

    print("🚀 DES 引擎冒烟测试")
    print(f"   社区: {config.get('name') or (config.get('meta') or {}).get('name')}")
    print(f"   角色: {', '.join(c['name'] for c in config['characters'])}")
    print("   模式: dry_run (无外部 API)\n")

    engine = SimulationEngine(config, NoopLLM(), dry_run=True)
    engine.run(max_days=3, verbose=True)

    print(f"\n📊 事件: {len(engine.event_log)}  t={engine.clock:.1f}  Day {engine.day}")
    for name, char in engine.characters.items():
        s = char.state
        print(f"   {name}: {s.status} E={s.energy}/{s.energy_max}")

    collisions = [e for e in engine.event_log if e["type"] == "collision"]
    studies = [e for e in engine.event_log if e["type"] == "study_step"]
    print(f"\n碰撞 {len(collisions)} | 研究步骤 {len(studies)}")
    assert engine.day >= 1
    assert len(engine.event_log) > 0
    print("✅ smoke_engine 通过")


if __name__ == "__main__":
    main()
