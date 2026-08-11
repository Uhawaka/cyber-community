#!/usr/bin/env python3
"""Quick quant lab dialogue test."""
import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.character import Character
from engine.interactions import run_collision

with open("worlds/quant-lab/community.yaml") as f:
    config = yaml.safe_load(f)

chars = {cc["name"]: Character(cc["name"], cc) for cc in config["characters"]}
llm = LLM(config)

# Elias ↔ Pavel: Heston numerics + statistical physics
print("=== Elias ↔ Pavel: Heston 数值发散 ===")
d1 = run_collision(chars["Elias"], chars["Pavel"],
    "Elias 在 Heston 模型高波动率区域发现了数值发散——他想问 Pavel 统计力学里有没有类似的现象",
    llm)
print(d1[:800])

# Yuki ↔ Elias: duality approach to the same problem
print("\n=== Yuki ↔ Elias: 对偶方法看 Heston ===")
d2 = run_collision(chars["Yuki"], chars["Elias"],
    "Yuki 觉得 Elias 的 Heston 数值发散可以用对偶方法解释——她想说服他试试",
    llm)
print(d2[:800])
