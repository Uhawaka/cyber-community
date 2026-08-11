#!/usr/bin/env python3
"""Test: English vs Chinese — is the web-novel tone a language artifact?"""

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

# Test 1: Elias ↔ Yuki in ENGLISH
print("="*60)
print("ENGLISH: Elias ↔ Yuki (Yuki questions Elias's pattern)")
print("="*60)
# Override system prompt language instruction temporarily
for c in chars.values():
    orig = c.build_system_prompt
    def make_english_prompt(char):
        p = orig()
        # Replace Chinese language instruction with English
        p = p.replace("回复用中文", "Reply in English")
        p = p.replace("用中文", "in English")
        return p
    # We'll inject English instruction differently

d1 = run_collision(chars["Elias"], chars["Yuki"],
    "Yuki has been looking at Elias's recent data on prime gaps modulo 7. She thinks the pattern might just be statistical fluctuation and wants to discuss it seriously — not to attack, but to understand.",
    llm)
print(d1[:800])

# Test 2: Gathering in ENGLISH
print("\n" + "="*60)
print("ENGLISH: Casual gathering — Pavel starts")
print("="*60)
d2 = run_gathering(chars, "Pavel", "", llm)
print(d2[:800])

# Test 3: Elias study thought in ENGLISH
print("\n" + "="*60)
print("ENGLISH: Elias thinking about his research")
print("="*60)
system = chars["Elias"].build_system_prompt()
thought = llm.chat(
    [{"role": "user", "content": "You're thinking about your research. Where are you stuck? What are you actually thinking about right now? Write naturally, in English. Not a performance — real mathematicians are stuck most of the time."}],
    system=system, temperature=0.8
)
print(thought[:600])
