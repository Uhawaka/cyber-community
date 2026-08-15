#!/usr/bin/env python3
"""Research grain + verdict discipline."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.culture import format_practice_context, resolve_world_frame
from engine.research import (
    looks_like_premature_verdict,
    research_prompt_block,
    resolve_research_config,
    score_research_note,
)
from engine.world_builder import load_world


def test_default_grain_is_working_unit():
    cfg = resolve_research_config({"domain": "mathematics"})
    assert cfg["grain"] == "working_unit"
    assert cfg["allow_horizon_solve"] is False
    assert cfg["verdict_requires_obligation"] is True
    assert "reconstruct" in cfg["working_unit_kinds"]


def test_prompt_block_forbids_horizon_solve():
    text = research_prompt_block({"research": {"grain": "working_unit"}})
    assert "working unit" in text.lower() or "horizon" in text.lower()


def test_research_skill_has_review_and_cross_domain():
    from engine.skills import load_skill_text, skill_section

    raw = load_skill_text("research")
    assert raw
    cycle = skill_section(raw, "Cycle")
    assert "Review peers" in cycle or "review" in cycle.lower()
    assert "Cross-domain" in cycle or "another domain" in cycle.lower()
    assert "engineer" in raw.lower()
    temper = skill_section(raw, "Temperament")
    assert "Tao" in temper or "Scholze" in temper or "Gowers" in temper
    assert "Zhang" in temper or "Huh" in temper
    assert "authority" in temper.lower() or "citation" in temper.lower()


def test_math_commune_injects_research_soul():
    cfg = load_world("math-commune", ROOT / "worlds")
    elias = next(c for c in cfg["characters"] if c["name"] == "Elias")
    soul = elias.get("soul") or {}
    assert soul.get("vocation") == "research"
    assert "engineer" in (soul.get("vocation_stance") or "").lower()
    traits = soul.get("vocation_traits") or []
    joined = " ".join(str(t).lower() for t in traits)
    assert "citation" in joined or "authority" in joined
    assert "mismatch" in joined or "curiosity" in joined
    assert "chair" in (soul.get("craft") or "").lower() or "studio" in (soul.get("craft") or "").lower()
    frame = resolve_world_frame(cfg)
    assert frame.get("vocation") == "research"
    catalog = frame.get("skill_catalog") or frame.get("skills") or []
    assert "research" in catalog
    assert not (frame.get("skills_text") or {})
    assert "research" in (elias.get("skills") or [])
    practice = format_practice_context(frame)
    assert "review" in practice.lower() or "peer" in practice.lower() or "working unit" in practice.lower()


def test_poets_salon_has_no_research_vocation():
    cfg = load_world("poets-salon", ROOT / "worlds")
    frame = resolve_world_frame(cfg)
    assert (frame.get("vocation") or "") != "research"
    first = cfg["characters"][0]
    assert (first.get("soul") or {}).get("vocation") in ("", None)
    assert "research" not in (first.get("skills") or [])


def test_free_grain_is_silent():
    assert research_prompt_block({"research": {"grain": "free"}}) == ""


def test_premature_verdict_without_obligation():
    assert looks_like_premature_verdict("这个方向不可行，到此为止。")
    assert looks_like_premature_verdict("Therefore this approach is a dead end.")
    assert not looks_like_premature_verdict(
        "这次探针失败。若要判定，还需要显式公式的误差项；下一步义务是复述 Weil 公式。"
    )


def test_score_rejects_solved_horizon():
    bad = score_research_note("我们今天证完了 Riemann hypothesis。")
    assert bad["claims_horizon_solved"]
    assert not bad["ok"]
    good = score_research_note(
        "Horizon: RH. Working unit: reconstruct explicit formula special case. "
        "Claim: … Status: obstructed. 下一步还需要误差项。"
    )
    assert good["ok"]


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
