#!/usr/bin/env python3
"""Round 1: Dialogue quality test — test the new psychology-driven system prompt."""

import sys
import yaml
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine.llm import LLM
from engine.character import Character

random.seed(42)

# Load math-commune config
with open("worlds/math-commune/community.yaml") as f:
    config = yaml.safe_load(f)

# Create characters
chars = {}
for cc in config["characters"]:
    chars[cc["name"]] = Character(cc["name"], cc)
    print(f"✓ {cc['name']} loaded (prompt: {len(chars[cc['name']].build_system_prompt())} chars)")

llm = LLM(config)

print("\n" + "="*60)
print("TEST 1: Individual study thoughts")
print("="*60)

for name, char in chars.items():
    system = char.build_system_prompt()
    topic = char.research.get("project", char.config.get("seed", ""))[:100]
    prompt = f"你正在思考你当前的研究方向。你卡在哪里了？你现在在想什么？自然地写一段思考（1-3段，中文）。不要表演——真实的数学家大部分时间都在卡住。"
    
    thought = llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.8)
    print(f"\n── {name} ──")
    print(thought[:500])
    print()

print("\n" + "="*60)
print("TEST 2: Elias ↔ Yuki collision")
print("="*60)

from engine.interactions import run_collision
dialogue = run_collision(chars["Elias"], chars["Yuki"], 
    "Elias 最近在算质数模7的分布时发现了一个奇怪的模式——他想找 Yuki 聊聊，但他不确定她会觉得这有价值", 
    llm)
print(dialogue[:1200])

print("\n" + "="*60)
print("TEST 3: Yuki ↔ Pavel collision")
print("="*60)

dialogue2 = run_collision(chars["Yuki"], chars["Pavel"],
    "Yuki 想把 Pavel 的湍流模型用范畴论重新表述——她不确定他会不会又觉得这'不实用'",
    llm)
print(dialogue2[:1200])
