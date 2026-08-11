#!/usr/bin/env python3
"""Test: Do JTBD/Cognitive Biases/Decision Patterns manifest in dialogue?"""

import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.character import Character
from engine.interactions import run_collision
random.seed(42)

with open("worlds/math-commune/community.yaml") as f:
    config = yaml.safe_load(f)

chars = {}
for cc in config["characters"]:
    chars[cc["name"]] = Character(cc["name"], cc)
llm = LLM(config)

# ── Test 1: 压力情境 — Elias 被质疑时是否"加倍计算"而非反思 ──
print("="*60)
print("TEST 1: 压力下决策 — Yuki 质疑 Elias 的方法")
print("="*60)
d1 = run_collision(chars["Elias"], chars["Yuki"],
    "Yuki 看了 Elias 最近的数据，觉得他的模式可能只是统计波动——她想认真讨论这个问题",
    llm)
print(d1[:800])

# ── Test 2: 认知偏差 — 给 Elias 一个反例数据 ──
print("\n" + "="*60)
print("TEST 2: 确认偏误 — Pavel 给了 Elias 一组不符合他模式的数据")
print("="*60)
d2 = run_collision(chars["Elias"], chars["Pavel"],
    "Pavel 算了一组新数据，似乎不符合 Elias 的质数分布模式——他想告诉 Elias，但不确定怎么开口",
    llm)
print(d2[:800])
