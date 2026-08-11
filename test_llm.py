#!/usr/bin/env python3
"""LLM-driven test: run 1 virtual day with real DeepSeek interactions."""

import sys
import yaml
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine.llm import LLM
from engine.engine import SimulationEngine

random.seed(123)

config_path = Path(__file__).parent / "worlds" / "math-commune" / "community.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

print("🚀 启动 LLM 驱动模拟 (1 虚拟天)")
print(f"   社区: {config['name']}")
print(f"   角色: {', '.join(c['name'] for c in config['characters'])}")
print(f"   LLM: DeepSeek API")
print()

llm = LLM(config)
engine = SimulationEngine(config, llm)
engine.run(max_days=1, verbose=True)

print(f"\n📊 统计:")
print(f"   事件日志: {len(engine.event_log)} 条")

# Show collisions
collisions = [e for e in engine.event_log if e["type"] == "collision"]
studies = [e for e in engine.event_log if e["type"] == "study_step"]

print(f"   碰撞: {len(collisions)} 次")
print(f"   研究步骤: {len(studies)} 次")

# Show character states
print(f"\n👤 角色最终状态:")
for name, char in engine.characters.items():
    s = char.state
    print(f"   {name}: status={s.status}, energy={s.energy}/{s.energy_max}")

# Show sample collision
if collisions:
    print(f"\n💬 碰撞对话示例:")
    c = collisions[0]
    print(f"   {c['initiator']} ↔ {c['target']}")
    for line in c.get("dialogue", "").split("\n")[:6]:
        print(f"   {line[:150]}")
