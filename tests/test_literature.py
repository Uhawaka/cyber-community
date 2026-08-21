#!/usr/bin/env python3
"""Literature search policy — bilingual frontier rules."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.literature import (
    category_on_shelf,
    compose_arxiv_search_query,
    filter_shelf_hits,
    looks_like_cjk,
    plan_literature_search,
    primary_query,
    resolve_literature_config,
    to_frontier_english,
)
from engine.culture import resolve_world_frame
from engine.world_builder import load_world


def test_default_frontier_is_english():
    cfg = resolve_literature_config({"domain": "mathematics"})
    assert cfg["frontier_language"] == "en"
    assert cfg["allow_vernacular"] is True
    assert cfg["bilingual_web"] is True
    assert "open problems" in cfg["fallback_query"].lower()
    assert cfg.get("enabled") is False


def test_cjk_slogan_rewrites_via_focus_not_rh_default():
    eng, rewritten = to_frontier_english(
        "从验证推论转向直接攻击作为检验标准",
        focus="spectral statistics L-function",
        fallback="research open problems",
    )
    assert rewritten
    assert not looks_like_cjk(eng)
    assert "spectral" in eng.lower() or "l-function" in eng.lower() or "research" in eng.lower()
    assert "riemann" not in eng.lower()  # no math-only default when focus is other


def test_cjk_with_riemann_focus_maps_lexicon():
    eng, rewritten = to_frontier_english(
        "从验证转向零点实部",
        focus="Riemann Hypothesis zeros",
        fallback="open problems mathematics",
    )
    assert rewritten
    assert "riemann" in eng.lower() or "zeta" in eng.lower()


def test_arxiv_plan_english_only():
    plan = plan_literature_search(
        intent="frontier",
        channel="arxiv",
        query="把判据换成检验标准",
        focus="Navier-Stokes regularity",
        world_or_frame={"domain": "mathematics"},
    )
    assert plan.rewritten_from_cjk
    q = primary_query(plan, "arxiv")
    assert not looks_like_cjk(q)
    assert "navier" in q.lower() or "stokes" in q.lower()


def test_web_plan_bilingual():
    plan = plan_literature_search(
        intent="mixed",
        channel="web",
        query="Riemann hypothesis recent progress",
        focus="Riemann hypothesis",
        world_or_frame={
            "domain": "mathematics",
            "literature": {
                "bilingual_web": True,
                "allow_vernacular": True,
                "en_site_hints": ["arxiv.org"],
            },
        },
    )
    channels = {q.channel for q in plan.queries}
    assert "web" in channels
    assert "web_zh" in channels
    en = primary_query(plan, "web")
    assert "riemann" in en.lower()
    assert "site:arxiv.org" in en.lower()


def test_vernacular_intent_zh_only():
    plan = plan_literature_search(
        intent="vernacular",
        channel="web",
        query="黎曼假设通俗解读",
        world_or_frame={"domain": "mathematics", "literature": {"allow_vernacular": True}},
    )
    assert len(plan.queries) == 1
    assert plan.queries[0].channel == "web_zh"
    assert looks_like_cjk(plan.queries[0].text)


def test_math_commune_frame_has_literature():
    cfg = load_world("math-commune", ROOT / "worlds")
    frame = resolve_world_frame(cfg)
    lit = frame.get("literature") or {}
    assert lit.get("frontier_language") == "en"
    assert lit.get("fallback_query")
    assert "arxiv.org" in (lit.get("en_site_hints") or [])
    assert lit.get("enabled") is True
    cats = lit.get("arxiv_categories") or []
    assert any(c.startswith("math") for c in cats)
    assert "hep-th" in cats
    assert "hep-ex" not in cats


def test_shelf_keeps_math_drops_hep_ex():
    math_shelf = ["math.*", "math-ph", "cs.CC", "hep-th", "hep-lat"]
    assert category_on_shelf("math.AG", math_shelf)
    assert category_on_shelf("math.AP", math_shelf)
    assert category_on_shelf("cs.CC", math_shelf)
    assert category_on_shelf("hep-th", math_shelf)
    assert not category_on_shelf("hep-ex", math_shelf)
    assert not category_on_shelf("hep-ph", math_shelf)
    assert not category_on_shelf("q-bio.GN", math_shelf)
    kept, dropped = filter_shelf_hits(
        [
            {"arxiv_id": "1", "primary_category": "math.AG"},
            {"arxiv_id": "2", "primary_category": "hep-ex"},
            {"arxiv_id": "3", "categories": ["hep-th"]},
        ],
        math_shelf,
    )
    assert [p["arxiv_id"] for p in kept] == ["1", "3"]
    assert [p["arxiv_id"] for p in dropped] == ["2"]
    q = compose_arxiv_search_query("Beale Kato Majda", math_shelf)
    assert "cat:math.*" in q
    assert "AND all:Beale Kato Majda" in q
    assert compose_arxiv_search_query("foo", []) == "all:foo"


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
