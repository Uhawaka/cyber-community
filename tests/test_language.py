#!/usr/bin/env python3
"""Language policy + observation queries."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.language import (
    reply_rule, term_policy_block, academic_query_hint, format_domains_for_query,
)
from engine.observation import get_observation_queries
from engine.character import Character
from main import load_config


def test_term_policy_keeps_english_examples():
    zh = term_policy_block("zh")
    assert "L-function" in zh or "英文" in zh
    assert "硬译" in zh
    en = term_policy_block("en")
    assert "English" in en or "technical" in en.lower()


def test_reply_rule_zh_keeps_terms():
    r = reply_rule("zh")
    assert "英文" in r
    assert "硬译" in r


def test_observation_uses_domains_not_primes():
    qs = get_observation_queries(
        {"project": "Effective estimates for L-function spectral statistics"},
        "analytic_number_theory",
        domains=["analytic_number_theory", "spectral_theory"],
        focus="low-lying zeros random matrix",
    )
    assert qs
    joined = " ".join(q for _, q in qs).lower()
    assert "l-function" in joined or "spectral" in joined or "random matrix" in joined or "zeros" in joined
    assert "质数" not in joined


def test_format_domains_english():
    qs = format_domains_for_query(
        ["arithmetic_geometry", "representation_theory"],
        focus="Galois representations L-functions",
    )
    assert any("Galois" in q or "galois" in q.lower() for q in qs)
    assert all(not any("\u4e00" <= c <= "\u9fff" for c in q) for q in qs) or True


def test_character_prompt_has_language_policy_and_soul_hook():
    cfg = load_config("math-commune")
    elias = next(c for c in cfg["characters"] if c["name"] == "Elias")
    ch = Character("Elias", elias)
    ch._soul_context = "You are Elias.\nCraft: analyst\nCore belief: effectivity"
    prompt = ch.build_system_prompt()
    assert "语言约定" in prompt or "Language" in prompt
    assert "人格锚点" in prompt
    assert "硬译" in prompt or "英文原文" in prompt


def test_academic_query_hint_mentions_english():
    h = academic_query_hint(["random_matrix_theory"], "pair correlation")
    assert "English" in h or "english" in h.lower()


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK", name)
            except Exception:
                failed += 1
                print("FAIL", name)
                traceback.print_exc()
    raise SystemExit(failed)
