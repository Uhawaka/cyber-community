#!/usr/bin/env python3
"""Test: Memory → Deep Think → Soul chain over 3 virtual days."""

import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from engine.llm import LLM
from engine.engine import SimulationEngine

random.seed(42)

with open("worlds/math-commune/community.yaml") as f:
    config = yaml.safe_load(f)

llm = LLM(config)
engine = SimulationEngine(config, llm)

print("Running 3-day simulation...")
engine.run(max_days=3, verbose=True)

print("\n" + "="*60)
print("MEMORY")
print("="*60)
for name, mem in engine.memories.items():
    episodes = mem.recall_recent(5)
    print(f"\n{name}: {len(mem.episodes)} total episodes")
    for ep in episodes:
        print(f"  [Day{ep.day}] {ep.emotional_valence} {ep.type}: {ep.summary[:80]}")

print("\n" + "="*60)
print("DEEP UNDERSTANDING (Soul)")
print("="*60)
for name, soul in engine.souls.items():
    understanding = soul.get_deep_understanding(3)
    print(f"\n{name}:")
    if understanding:
        print(understanding)
    else:
        print("  (no deep understanding yet)")
