#!/usr/bin/env python3
"""Soul v2: generic seeding, junk rejection, identity ≠ orientation."""

import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.soul import SoulFile, empty_soul
from engine.engine import SimulationEngine
from engine.world_builder import expand_world


class NoopLLM:
    def chat(self, *a, **k):
        return "{}"

    def think(self, *a, **k):
        return "[noop]"


def _load_world(name: str) -> dict:
    raw = yaml.safe_load((ROOT / f"worlds/{name}/community.yaml").read_text())
    if raw.get("format_version") == "2.0":
        return expand_world(raw)
    return raw


def _elias_cfg():
    cfg = _load_world("math-commune")
    return next(c for c in cfg["characters"] if c["name"] == "Elias")


def test_soul_py_has_no_domain_dictionaries():
    src = (ROOT / "engine/soul.py").read_text()
    assert "DOMAIN_CRAFT" not in src
    assert "analytic_number_theory" not in src
    assert "质数" not in src
    assert "twin prime" not in src.lower()


def test_explicit_soul_block_copied_one_to_one():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Tea.yaml"))
        cfg = {
            "soul": {
                "craft": "Tea ceremony host",
                "who_i_am": "I measure time by the cooling of water.",
                "core_belief": "Attention is a form of hospitality.",
                "how_i_think": "Notices temperature before words",
                "how_i_protect": "Withdraws into ritual sequence",
                "what_drives_me": "One guest who leaves quieter than they arrived",
                "voice": ["Speaks in short, warm sentences"],
                "bonds": {"Guest": {"stance": "Curious without crowding"}},
            },
            "orientation": {
                "current_focus": "Winter-blend ratio for a shy guest",
                "open_question": "When is silence better than the next pour?",
                "tensions": ["Tradition vs the guest's impatience"],
            },
        }
        soul.init_from_config("Tea", cfg, world_name="tea_ceremony")
        ident = soul.data["identity"]
        assert ident["craft"] == "Tea ceremony host"
        assert "hospitality" in ident["core_belief"]
        assert "Winter-blend" in soul.data["orientation"]["current_focus"]
        assert "Guest" in soul.data["bonds"]


def test_seed_fills_identity_from_math_commune():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg(), world_name="Math Commune")
        ident = soul.data["identity"]
        assert ident["craft"]
        assert ident["who_i_am"]
        assert ident["core_belief"]
        assert ident["voice"]
        assert "Yuki" in soul.data["bonds"] or "Pavel" in soul.data["bonds"]
        belief = ident["core_belief"].lower()
        assert "prime" not in belief, "core_belief must not collapse to a narrow topic"
        # Craft is analytic number theory; seasonal focus is shared spectral program
        craft = (ident.get("craft") or "").lower()
        assert (
            "analytic" in craft
            or "number theory" in craft
            or "l-function" in craft
            or "chair" in craft
            or "analyst" in craft
            or "estimate" in craft
        )
        focus = (soul.data["orientation"].get("current_focus") or "").lower()
        assert (
            "seed" in focus
            or "shelf" in focus
            or "clay" in focus
            or "tool" in focus
            or "attack" in focus
            or "url" in focus
            or "claim" in focus
        )
        assert "knowledge_evolved" not in soul.data


def test_reject_tool_junk_milestones():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg())
        assert soul.add_milestone("使用run_code获得发现") is False
        assert soul.add_milestone("论文已保存: foo.md") is False
        assert soul.add_milestone("First time admitting Pavel's analogy might be right") is True
        assert len(soul.data["milestones"]) == 1


def test_add_knowledge_gained_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg())
        soul.add_knowledge("gained", "[run_code] output: alpha=1.2")
        assert "[run_code]" not in yaml.dump(soul.data)
        soul.add_knowledge("question", "Is the short-interval error cancellation real?")
        assert "short-interval" in soul.data["orientation"]["open_question"]


def test_deep_thought_becomes_one_reflection():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg())

        class T:
            understanding = "I may have been looking in the wrong place. The low-frequency end matters."
            confidence = 0.7
            day = 2
            open_questions = ["Is alpha stable?"]

        soul.add_deep_thought(T())
        assert len(soul.data["reflections"]) == 1
        assert "wrong place" in soul.data["reflections"][0]["statement"]


def test_engine_seeds_all_five_worlds():
    for world in (
        "math-commune",
        "quant-lab",
        "poets-salon",
        "philosophy-cafe",
        "alien-observers",
    ):
        cfg = _load_world(world)
        assert cfg.get("name") or (cfg.get("meta") or {}).get("name")
        engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
        for name, soul in engine.souls.items():
            data = soul.data
            assert data["soul_version"] == "2.0", world
            assert data["identity"]["core_belief"], f"{world}/{name} empty belief"
            assert data["identity"]["craft"], f"{world}/{name} empty craft"
            assert data["orientation"].get("current_focus") or data["orientation"].get(
                "open_question"
            ), f"{world}/{name} empty orientation"
        summary = next(iter(engine.souls.values())).get_context_summary()
        assert "Core belief:" in summary
        assert "You are " in summary


def test_enclosed_worlds_have_no_search_web():
    for world in ("poets-salon", "philosophy-cafe"):
        cfg = _load_world(world)
        tools = [t.get("name") for t in cfg.get("tools") or []]
        assert "search_web" not in tools, world
        assert (cfg.get("world") or {}).get("permeability") == "enclosed"


def test_quant_lab_seeds_nonempty():
    cfg = _load_world("quant-lab")
    for c in cfg["characters"]:
        assert (c.get("seed") or "").strip(), c["name"]
        assert (c.get("soul") or {}).get("core_belief"), c["name"]


def test_context_summary_not_empty():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg())
        s = soul.get_context_summary()
        belief_line = [ln for ln in s.splitlines() if ln.startswith("Core belief")][0]
        assert len(belief_line) > len("Core belief: ")



def test_open_domain_grows_living_list():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg(), world_name="Math Commune")
        seeds = list(soul.data["identity"]["seed_domains"])
        assert soul.data["identity"]["domains"] == seeds
        # Math Commune may start with an empty toolbox; open_domain still grows it.
        assert soul.open_domain("tropical_geometry", day=3, reason="dictionary to spectra")
        assert "tropical_geometry" in soul.data["identity"]["domains"]
        assert soul.data["identity"]["seed_domains"] == seeds  # seeds stable
        assert soul.open_domain("tropical_geometry", day=4) is False  # no dup
        assert any("tropical" in str(x).lower() for x in soul.data["orientation"]["recently_opened"])
        applied = soul.apply_delta({"opened_domains": ["homotopy_type_theory"]}, day=5)
        assert any(a.startswith("domain:") for a in applied)
        summary = soul.get_context_summary()
        assert "Domains (living)" in summary
        assert "tropical_geometry" in summary


def test_open_domain_strips_commentary_and_rejects_cjk_meta():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg(), world_name="Math Commune")
        dirty = (
            "arithmetic statistics — 若持续探索则记录，但当前仅一次提及，暂不确认"
        )
        assert soul.open_domain(dirty, day=1) is True
        assert "arithmetic_statistics" in soul.data["identity"]["domains"]
        assert all("若持续" not in d for d in soul.data["identity"]["domains"])
        assert soul.open_domain("若持续探索则记录", day=1) is False
        # Prompt leftovers: keep left slug, drop commentary after em-dash
        assert soul.open_domain(
            "english_snake_or_short_phrase — only if a lasting new territory opened",
            day=2,
        ) is True
        assert "english_snake_or_short_phrase" in soul.data["identity"]["domains"]
        assert soul.open_domain(
            "only if a lasting new territory opened",
            day=3,
        ) is False


def test_reflection_strips_numbering_and_boilerplate():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "Elias.yaml"))
        soul.init_from_config("Elias", _elias_cfg())
        ok = soul.add_reflection(
            "1. 我的核心洞见是：**scaling 是 null model 的一部分**。",
            about="work",
            day=1,
        )
        assert ok
        stmt = soul.data["reflections"][-1]["statement"]
        assert not stmt.startswith("1.")
        assert "核心洞见" not in stmt
        assert "**" not in stmt
        assert "scaling" in stmt.lower() or "null model" in stmt.lower()
        # Near-duplicate rejected
        assert soul.add_reflection(stmt, about="work", day=1) is False


def test_math_commune_starts_without_specialty_silos():
    """Seed shelf drives work; characters do not pre-claim specialty domains."""
    cfg = _load_world("math-commune")
    frame = cfg.get("world") or {}
    lib = frame.get("seed_library") or []
    assert len(lib) >= 8
    blob = " ".join(str(x) for x in lib).lower()
    assert "claymath.org" in blob
    assert "annals" in blob
    assert "inventiones" in blob or "springer.com/journal/222" in blob
    assert "arxiv.org" in blob
    assert frame.get("open_problems") in ([], None) or frame.get("open_problems") == []
    for c in cfg["characters"]:
        assert (c.get("domains") or []) == [], c["name"]
        # No pre-set specialty domain field — expertise is earned later
        assert not (c.get("domain") or "").strip() or c.get("domain") == "mathematics"


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    raise SystemExit(failed)
