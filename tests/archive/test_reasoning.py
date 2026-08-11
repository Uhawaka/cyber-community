#!/usr/bin/env python3
"""Deep test v2: Push for actual mathematical reasoning, not meta-discussion."""

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

# ── Test: Forced step-by-step reasoning ──
print("="*70)
print("TEST: Elias explains his approach — MUST include formulas and logic")
print("="*70)

char = chars["Elias"]
system = char.build_system_prompt()

# Force reasoning style
reasoning_prompt = f"""You're working on the pair correlation of zeta zeros.
Walk me through your approach. Start from something concrete —
a definition, an inequality, a computation you'd run.

Don't tell me "I think there's a connection." SHOW me the connection.
Write actual formulas. Derive one step. Point out where it breaks.

For example: "If the zeros are γ_n, I'd start by computing
R₂(x) = (1/N) #{{ (n,m) : n≠m, 0 ≤ γ_n, γ_m ≤ T, (γ_n - γ_m)(log T)/(2π) ≤ x }}
Then compare with the GUE prediction 1 - (sin(πx)/(πx))²."
"""

thought = llm.chat([{"role": "user", "content": reasoning_prompt}], system=system, temperature=0.6)
print(f"\nElias:\n{thought[:1200]}")

# ── Test: Collision with derivation ──
print("\n" + "="*70)
print("TEST: Pavel ↔ Elias — collaborative derivation")
print("="*70)

# Override the collision prompt to force derivation
from engine.character import Character as CharClass
initiator, target = chars["Elias"], chars["Pavel"]
system_i = initiator.build_system_prompt()
system_t = target.build_system_prompt()

topic = "Montgomery's pair correlation: derive the connection to GUE step by step"

# Round 1: Start with a concrete claim
msg1 = llm.chat(
    [{"role": "user", "content": f"You want to work through Montgomery's pair correlation with {target.name}. Start with a concrete statement — a formula, an inequality, or a computational approach. Don't say 'I think there's a connection.' Write an actual mathematical step."}],
    system=system_i, temperature=0.6
)
print(f"\nElias: {msg1[:400]}...")

# Round 2: Target responds with actual reasoning
msg2 = llm.chat(
    [{"role": "user", "content": f"{initiator.name} says: \"{msg1}\"\n\nRespond with actual mathematical reasoning. If you agree, extend the derivation. If you disagree, point to a specific step that fails. If you have a different approach, write the first step. Use formulas."}],
    system=system_t, temperature=0.6
)
print(f"\nPavel: {msg2[:400]}...")

# Round 3: Push deeper
msg3 = llm.chat(
    [{"role": "user", "content": f"You said: \"{msg1}\"\n\n{target.name} responded: \"{msg2}\"\n\nPush one step further. Derive the next line. Where does the computation break? What's the obstacle?"}],
    system=system_i, temperature=0.6
)
print(f"\nElias: {msg3[:400]}...")
