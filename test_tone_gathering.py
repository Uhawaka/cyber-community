#!/usr/bin/env python3
"""Test: Tone + Casual Gathering"""
import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.character import Character
from engine.interactions import run_collision, run_gathering
random.seed(42)

with open("worlds/math-commune/community.yaml") as f:
    config = yaml.safe_load(f)
chars = {cc["name"]: Character(cc["name"], cc) for cc in config["characters"]}
llm = LLM(config)

# Test 1: Pressure situation — should be collegial now
print("="*60)
print("TEST 1: Yuki 质疑 Elias (应保持学术语气)")
print("="*60)
d1 = run_collision(chars["Elias"], chars["Yuki"],
    "Yuki 觉得 Elias 最近的质数分布模式可能只是统计波动——她想认真讨论",
    llm)
print(d1[:700])

# Test 2: Casual gathering — should feel like colleagues chatting
print("\n" + "="*60)
print("TEST 2: 三人闲聊 (应该是自然对话，不是正式会议)")
print("="*60)
d2 = run_gathering(chars, "Pavel", "", llm)
print(d2[:800])
