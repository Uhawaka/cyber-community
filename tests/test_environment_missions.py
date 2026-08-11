#!/usr/bin/env python3
"""Cast-driven environment + domain-aware missions + trait sociology."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import load_config
from engine.engine import SimulationEngine
from engine.environment import Environment
from engine.mission import assign_mission, MissionBoard
from engine.sociology import CommunityEngine


class NoopLLM:
    def chat(self, *a, **k):
        return "{}"

    def think(self, *a, **k):
        return "S"


def test_environment_has_room_for_each_cast_member():
    cfg = load_config("math-commune")
    with tempfile.TemporaryDirectory() as tmp:
        # Build fake character-like objects with .config
        class C:
            def __init__(self, config):
                self.config = config

        chars = {c["name"]: C(c) for c in cfg["characters"]}
        env = Environment(str(Path(tmp) / "environment.json"), characters=chars)
        names = [c["name"] for c in cfg["characters"]]
        assert "Nora" in names
        for name in names:
            loc = env.character_locations.get(name)
            assert loc, name
            node = env.nodes[loc]
            assert name in node.name or name == node.created_by
            text = node.description.lower()
            assert "质数" not in node.description
            assert "湍流" not in node.description
        assert "commons" in env.nodes
        assert "nora_study" in env.nodes


def test_mission_uses_focus_not_hardcoded_math_fallback():
    cfg = load_config("math-commune")
    elias = next(c for c in cfg["characters"] if c["name"] == "Elias")

    class C:
        def __init__(self, config):
            self.config = config
            self.research = config.get("research") or {}

    board = MissionBoard({"Elias": C(elias)})
    m = board.get_active("Elias")
    assert m is not None
    # Should mention L-function / spectral / domains — not only legacy primes template
    q = m.question.lower()
    assert "质数分布" not in m.question or "l-function" in q or "spectral" in q or "estimate" in q or "文献" in m.question


def test_sociology_roles_not_name_table():
    cfg = load_config("math-commune")

    class C:
        def __init__(self, config):
            self.config = config
            self.personality = config.get("personality") or {}
            self.drives = config.get("drives") or {}
            self.voice = config.get("voice") or (config.get("soul") or {}).get("voice") or []
            self.cognitive = config.get("cognitive") or {}
            self.defense = config.get("defense") or {}

    chars = {c["name"]: C(c) for c in cfg["characters"]}
    soc = CommunityEngine(chars)
    assert set(soc.roles) == set(chars)
    # Pavel high extraversion+agreeableness → bridge-ish; Nora/Elias challenger-ish
    assert soc.roles["Pavel"] in ("bridge", "nurturer", "elder", "challenger", "newcomer")
    assert "Nora" in soc.stage
    # presence should mention craft/role or voice, not Hayashi lore
    assert "Hayashi" not in (soc.stage["Nora"].in_public or "")


def test_engine_wires_cast_environment():
    cfg = load_config("math-commune")
    engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
    assert "nora_study" in engine.environment.nodes or any(
        "Nora" in n.name for n in engine.environment.nodes.values()
    )
    assert engine.missions.get_active("Elias") is not None


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
