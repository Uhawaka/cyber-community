#!/usr/bin/env python3
"""Show a character's day — rhythm + environment + inner dialogue together."""

import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.engine import SimulationEngine

random.seed(42)

with open("worlds/quant-lab/community.yaml") as f:
    config = yaml.safe_load(f)

llm = LLM(config)
engine = SimulationEngine(config, llm)
engine.run(max_days=1, verbose=True)

# Show a character's day summary
print("\n" + "=" * 60)
print("Elias 的一天")
print("=" * 60)

events = [e for e in engine.event_log if e.get("actor") == "Elias"]
for e in events:
    t = e.get("time", 0)
    etype = e.get("type", "")
    if etype == "inner_turn":
        role = e.get("role", "")
        content = e.get("content", "")[:80]
        prefix = "  我:" if role == "self" else "  但:"
        print(f"  t={t:.0f}h {prefix} {content}")
    elif etype == "study_step":
        print(f"  t={t:.0f}h 📖 研究完成 ({e.get('step',0)}轮)")
    elif etype == "collision":
        print(f"  t={t:.0f}h 💬 与 {e.get('target','')} 讨论")
    elif etype == "tool_use":
        print(f"  t={t:.0f}h 🔧 {e.get('tool','')}")
    elif etype == "deep_think":
        print(f"  t={t:.0f}h 🧠 深度反思")
