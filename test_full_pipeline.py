#!/usr/bin/env python3
"""End-to-end: Run 2 days and show the full pipeline output."""

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

print("数学公社 · 2天完整运行\n")
engine.run(max_days=2, verbose=True)

# Summary
print("\n" + "="*60)
print("产出总结")
print("="*60)
arts = engine.production.artifacts
papers = engine.production.get_by_type("paper")
insights = engine.production.get_by_type("insight")
print(f"总计: {len(arts)} 件")
print(f"  论文: {len(papers)}")
print(f"  洞见: {len(insights)}")

print(f"\n--- 洞见 ---")
for a in insights[-5:]:
    print(f"  [{a.authors[0]}, Day{a.created_day}, conf={a.confidence:.0%}] {a.title[:80]}")

print(f"\n--- 论文 ---")
for a in papers[-5:]:
    print(f"  [{a.authors[0]}, Day{a.created_day}] {a.title[:60]}")

print(f"\n--- 环境 ---")
for nid, node in engine.environment.nodes.items():
    if node.echoes:
        print(f"  {node.name}: {len(node.echoes)}条回响")
        for e in node.echoes[-2:]:
            print(f"    「{e['author']}: {e['content'][:50]}」")
