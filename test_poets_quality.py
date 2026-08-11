#!/usr/bin/env python3
"""Round 4: Cross-world dialogue quality — test poets salon."""

import sys, yaml, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from engine.llm import LLM
from engine.character import Character
from engine.interactions import run_collision
from engine.world_builder import expand_world

random.seed(42)

with open("worlds/poets-salon/community.yaml") as f:
    config = yaml.safe_load(f)
config = expand_world(config)

chars = {}
for cc in config["characters"]:
    chars[cc["name"]] = Character(cc["name"], cc)

llm = LLM(config)

print("="*60)
print("诗人雅集 — 对话质量测试")
print("="*60)

# 李白 ↔ 杜甫: 李白邀杜甫喝酒，杜甫婉拒但认真
print("\n── 李白 ↔ 杜甫 ──")
d1 = run_collision(chars["李白"], chars["杜甫"],
    "月下独饮，想拉个人一起——杜甫正好路过",
    llm)
print(d1[:1000])

# 王维 ↔ 李白: 王维画了一幅画，李白来看
print("\n── 王维 ↔ 李白 ──")
d2 = run_collision(chars["王维"], chars["李白"],
    "王维刚画完一幅山水，李白闯进来要看",
    llm)
print(d2[:1000])

# 杜甫 ↔ 王维: 杜甫看到王维画里的农夫，想起民生
print("\n── 杜甫 ↔ 王维 ──")
d3 = run_collision(chars["杜甫"], chars["王维"],
    "杜甫看到王维画的山水——画里有一个孤独的农夫",
    llm)
print(d3[:1000])
