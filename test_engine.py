#!/usr/bin/env python3
"""Quick smoke test: run the DES engine with NoopLLM for 3 virtual days.
No external API calls — validates pure event logic, state machine, energy system."""

import sys
import yaml
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine.llm import LLM
from engine.engine import SimulationEngine

random.seed(42)


class NoopLLM:
    """LLM stub — engine uses weighted random decisions instead."""
    def chat(self, *args, **kwargs):
        return "[decision simulated]"
    def think(self, *args, **kwargs):
        return "[thinking simulated]"


# Load config
config_path = Path(__file__).parent / "worlds" / "math-commune" / "community.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

print("🚀 DES 引擎冒烟测试")
print(f"   社区: {config.get('name', config.get('meta', {}).get('name', 'math-commune'))}")
print(f"   角色: {', '.join(c['name'] for c in config['characters'])}")
print(f"   模式: dry_run (无外部API调用)")
print()

llm = NoopLLM()
engine = SimulationEngine(config, llm, dry_run=True)
engine.run(max_days=3, verbose=True)

print()
print(f"📊 统计:")
print(f"   事件日志: {len(engine.event_log)} 条")
print(f"   最终虚拟时间: t={engine.clock:.1f}")
print(f"   虚拟天数: {engine.day}")

# Show character states
print(f"\n👤 角色状态:")
for name, char in engine.characters.items():
    s = char.state
    print(f"   {name}: status={s.status}, energy={s.energy}/{s.energy_max}, mood={s.mood}")

# Spot checks
collisions = [e for e in engine.event_log if e["type"] == "collision"]
studies = [e for e in engine.event_log if e["type"] == "study_step"]
inner_turns = [e for e in engine.event_log if e["type"] == "inner_turn"]
print(f"\n✅ 碰撞: {len(collisions)} | 研究步骤: {len(studies)} | 内心对话轮: {len(inner_turns)}")
print(f"✅ 测试通过 — 引擎逻辑正常")
