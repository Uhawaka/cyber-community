#!/usr/bin/env python3
"""Test inner dialogue — the character talks to themselves."""
import sys, yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.character import Character
from engine.thought_loop import InnerDialogue, next_inner_turn, extract_insight

with open("worlds/quant-lab/community.yaml") as f:
    config = yaml.safe_load(f)

char = Character("Elias", config["characters"][0])
llm = LLM(config)

dialogue = InnerDialogue()
dialogue.start("Heston模型ξ>1.5时Euler离散化的偏差为什么随Δt减小反而增大")

print("内心对话开始...\n")
for i in range(6):
    turn = next_inner_turn(llm, char, dialogue)
    if turn is None:
        break
    dialogue.add_turn(turn.role, turn.content, turn.motivation)
    prefix = "我:" if turn.role == "self" else "但:"
    print(f"[{turn.motivation}] {prefix} {turn.content[:150]}")
    print()

print(f"---\n{len(dialogue.turns)}轮对话完成")
print(f"核心洞察: {extract_insight(dialogue)[:200]}")
