#!/usr/bin/env python3
"""Unit tests for worldview / sociology / psychology wiring (no LLM)."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.culture import (
    resolve_sociology,
    resolve_world_frame,
    format_culture_context,
    format_world_context,
    psych_action_bias,
    apply_weight_bias,
    frame_observation,
)
from engine.engine import SimulationEngine
from engine.day_rhythm import DayPhase, get_phase_activity
from engine.world_builder import expand_world


class NoopLLM:
    def chat(self, *args, **kwargs):
        return "[noop]"

    def think(self, *args, **kwargs):
        return "[noop]"


def _world(name: str) -> dict:
    raw = yaml.safe_load((ROOT / f"worlds/{name}/community.yaml").read_text())
    if raw.get("format_version") == "2.0":
        return expand_world(raw)
    return raw


def test_resolve_sociology_v1():
    cfg = _world("math-commune")
    soc = resolve_sociology(cfg)
    assert soc.get("development_stage") == "storming"
    assert soc.get("norms", {}).get("positive")


def test_resolve_world_frame_v2_enclosed():
    cfg = _world("poets-salon")
    frame = resolve_world_frame(cfg)
    assert frame["permeability"] == "enclosed"
    assert "poem" in frame["worldview"].lower() or "salon" in frame["worldview"].lower()


def test_format_culture_includes_norms_and_memory():
    cfg = _world("math-commune")
    text = format_culture_context(resolve_sociology(cfg))
    assert "storming" in text
    assert "被鼓励" in text or "Show unfinished" in text or "unfinished" in text.lower()
    assert "起源" in text or "共同记得" in text or "张力" in text or "founding" in text.lower()


def test_format_world_window_connected_vs_enclosed():
    connected = format_world_context({
        "name": "Math Commune",
        "permeability": "connected",
        "worldview": "shared studio",
        "domain": "mathematics",
    })
    enclosed = format_world_context({
        "name": "Poets' Salon",
        "permeability": "enclosed",
        "worldview": "moonlit courtyard",
        "domain": "literature",
    })
    assert "开着" in connected
    assert "关着" in enclosed


def test_psych_bias_extraversion_and_drives():
    social = psych_action_bias(
        {"extraversion": 9, "openness": 5, "conscientiousness": 5, "agreeableness": 5, "neuroticism": 5},
        {"relatedness": 8},
    )
    solitary = psych_action_bias(
        {"extraversion": 2, "openness": 5, "conscientiousness": 8, "agreeableness": 5, "neuroticism": 5},
        {"competence": 8, "autonomy": 8},
    )
    assert social.get("socialize", 1) > 1.0
    assert solitary.get("study", 1) > 1.0
    assert solitary.get("socialize", 1) < 1.0


def test_apply_weight_bias():
    w = apply_weight_bias({"study": 1.0, "socialize": 1.0}, {"study": 1.5, "socialize": 0.7})
    assert w["study"] == 1.5
    assert abs(w["socialize"] - 0.7) < 1e-9


def test_frame_observation_not_api_flavored():
    framed = frame_observation("prime gaps", "arxiv", "找到 3 篇论文", True)
    assert "图书馆" in framed["log"] or "馆藏" in framed["log"]
    assert "API" not in framed["log"]
    assert "搜索结果" not in framed["memory"]


def test_phase_activity_accepts_bias_without_mutating_defaults():
    from engine import day_rhythm
    before = [dict(a) for a in day_rhythm.PHASE_ACTIVITIES[DayPhase.MIDDAY]]
    get_phase_activity(DayPhase.MIDDAY, weight_bias={"socialize": 1.5})
    after = day_rhythm.PHASE_ACTIVITIES[DayPhase.MIDDAY]
    assert before == [dict(a) for a in after]


def test_engine_injects_culture_and_world():
    cfg = _world("math-commune")
    engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
    assert engine.world_frame["permeability"] == "connected"
    assert engine.society.sociology_config.get("development_stage") == "storming"

    engine._inject_context("Elias")
    ctx = engine.characters["Elias"]._memory_context
    assert "社区文化" in ctx or "storming" in ctx
    assert "你所在的世界" in ctx or "窗" in ctx


def test_enclosed_world_skips_observe_bootstrap():
    cfg = _world("poets-salon")
    from engine.events import EventQueue

    engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
    assert engine.world_frame["permeability"] == "enclosed"
    assert not engine._window_open()

    engine.dry_run = False
    engine.queue = EventQueue()
    engine.bootstrap()
    types = []
    while engine.queue:
        types.append(engine.queue.pop().type)
    assert "observe_world" not in types
    assert "activate" in types


def test_engine_dry_run_still_works_after_wiring():
    cfg = _world("math-commune")
    engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
    engine.run(max_days=1, verbose=False)
    assert engine.day >= 1
    assert len(engine.event_log) > 0


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
