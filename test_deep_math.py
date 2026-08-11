#!/usr/bin/env python3
"""Deep test: Montgomery pair correlation + Random Matrix Theory.
A real, active research area that engages all three characters'
cognitive styles: computation (Elias), structure (Yuki), physics (Pavel).
"""

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

# ── Test 1: Individual deep thinking about the problem ──
print("="*70)
print("STAGE 1: Individual deep thoughts on Montgomery pair correlation")
print("="*70)
problem_statement = """
Montgomery's pair correlation conjecture states that the normalized spacings
between zeros of the Riemann zeta function follow the GUE (Gaussian Unitary
Ensemble) distribution from random matrix theory. Specifically, the pair
correlation function is 1 - (sin(πu)/(πu))².

This suggests a deep connection between number theory and quantum chaos —
the same statistics appear in the energy levels of heavy nuclei and quantum
systems whose classical limit is chaotic.

Open question: WHY does this connection exist? Is there a spectral
interpretation of the zeta zeros? What operator has the zeros as eigenvalues?
"""

for name in ["Elias", "Yuki", "Pavel"]:
    char = chars[name]
    system = char.build_system_prompt()
    prompt = f"""Someone just brought up a fascinating problem:

{problem_statement}

You've been thinking about this. What's your genuine reaction? What angle
do you find most interesting? What's the first thing you'd want to check
or understand? Write naturally — this is your initial reaction, not a
prepared talk. 2-4 sentences."""

    thought = llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.8)
    print(f"\n── {name} ──")
    print(thought[:600])

# ── Test 2: Collision — Elias ↔ Pavel on computation vs physics ──
print("\n" + "="*70)
print("STAGE 2: Elias ↔ Pavel — computational evidence vs physical intuition")
print("="*70)
d1 = run_collision(chars["Elias"], chars["Pavel"],
    "Elias just computed the pair correlation for the first 10^5 zeta zeros and got a near-perfect GUE fit. Pavel thinks this can't be a coincidence — there must be a physical system whose spectrum matches the zeros.",
    llm)
print(d1[:1000])

# ── Test 3: Yuki brings in the structural perspective ──
print("\n" + "="*70)
print("STAGE 3: Yuki enters — can this be framed structurally?")
print("="*70)
d2 = run_collision(chars["Yuki"], chars["Elias"],
    "Yuki overheard Elias and Pavel's discussion about GUE statistics and zeta zeros. She thinks there might be a categorical framework that explains WHY these two systems share statistics — not just that they do.",
    llm)
print(d2[:1000])

# ── Test 4: All three together — gathering ──
print("\n" + "="*70)
print("STAGE 4: Three-way discussion — synthesis")
print("="*70)
d3 = run_gathering(chars, "Pavel", 
    "The connection between zeta zeros and random matrix spectra",
    llm)
print(d3[:1200])
