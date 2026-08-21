#!/usr/bin/env python3
"""SOP work gates: unread shelf, source citations, collision-force tool."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.character import Character
from engine.engine import SimulationEngine
from engine.events import Event
from engine.inbox import inbox_weight_bias
from engine.interactions import decide_action
from engine.work_queue import (
    COLLISION_FORCE_AFTER,
    artifact_has_source,
    extract_arxiv_ids,
    forced_decision,
    format_work_briefing,
    looks_like_mission_query,
    note_collision,
    note_read,
    note_search_hits,
    note_tool,
    salvage_search_query,
)
from engine.world_builder import expand_world


class NoopLLM:
    def __init__(self, letter: str = "T"):
        self.letter = letter

    def chat(self, *a, **k):
        return self.letter

    def think(self, *a, **k):
        return self.letter


def _char(name: str = "Elias") -> Character:
    return Character(name, {"seed": "p-adic L-functions"})


def test_extract_arxiv_ids():
    ids = extract_arxiv_ids("see arXiv:1712.01271 and 2301.12345v2 plus math/0000001")
    assert "1712.01271" in ids
    assert "2301.12345v2" in ids
    assert "math/0000001" in ids


def test_salvage_drops_mission_and_slogan_queries():
    assert looks_like_mission_query("open problems mathematics")
    assert looks_like_mission_query("Cite one seed paper on the board")
    assert salvage_search_query("open problems mathematics", domains=["Iwasawa", "p-adic L"]) == "Iwasawa p-adic L"
    assert salvage_search_query("exceptional zeros p=2") == "exceptional zeros p=2"
    # Chinese slogan-as-focus is not a search query
    assert salvage_search_query(
        "open problems mathematics",
        focus="翻阅人类世界的图书馆",
        domains=["BSD"],
    ) == "BSD"


def test_artifact_needs_arxiv_or_curve():
    char = _char()
    assert not artifact_has_source("今天对 L-函数有了更深的感觉", char)
    assert artifact_has_source("following 1712.01271 we check the Fitting ideal", char)
    assert artifact_has_source("the curve 11a1 has rank 0", char)
    assert artifact_has_source("y^2 = x^3 - x", char)
    note_read(char, "1712.01271")
    assert artifact_has_source("we reuse 1712.01271 for the local factor", char)


def test_unread_forces_read_and_clears_after_note_read():
    char = _char()
    added = note_search_hits(
        char,
        [{"arxiv_id": "1712.01271", "title": "p-adic L-functions"}],
    )
    assert added[0]["arxiv_id"] == "1712.01271"
    decision = forced_decision(char)
    assert decision is not None
    assert decision["tool"] == "read_arxiv"
    assert decision["arxiv_id"] == "1712.01271"
    assert decision["forced"] == "unread"
    note_read(char, "1712.01271")
    assert char.state.unread_arxiv == []
    assert "1712.01271" in char.state.read_arxiv_ids
    assert forced_decision(char) is None


def test_collision_streak_forces_tool():
    char = _char()
    for _ in range(COLLISION_FORCE_AFTER - 1):
        note_collision(char)
    assert forced_decision(char) is None
    note_collision(char)
    d = forced_decision(char)
    assert d is not None
    assert d["type"] == "study"
    assert d["forced"] == "collision_streak"
    note_read(char, "2301.00001")
    char.state.collision_streak = COLLISION_FORCE_AFTER
    d2 = forced_decision(char)
    assert d2["type"] == "study"
    note_tool(char)
    assert char.state.collision_streak == 0
    assert forced_decision(char) is None


def test_work_briefing_says_not_yet_read():
    char = _char()
    note_search_hits(char, [{"arxiv_id": "1712.01271", "title": "Pollack p=2"}])
    brief = format_work_briefing(char)
    assert "1712.01271" in brief
    assert "未深读" in brief
    assert "还不算读过" in brief


def test_unread_bias_does_not_crush_read_tool():
    char = _char()
    note_search_hits(char, [{"arxiv_id": "1712.01271", "title": "x"}])
    bias = inbox_weight_bias({"has_priority": True, "messages": [{"from": "Yuki"}]}, char)
    assert bias["tool_read_arxiv"] > 1
    assert bias["socialize"] < 1


def test_decide_action_x_is_rest_r_is_read():
    char = _char()
    tools = [
        {"name": "read_arxiv", "description": "deep read"},
        {"name": "search_arxiv", "description": "search"},
    ]
    rest = decide_action(char, NoopLLM("X"), tools)
    assert rest["type"] == "rest"
    read = decide_action(char, NoopLLM("R"), tools)
    assert read["type"] == "tool"
    assert read["tool"] == "read_arxiv"


def _engine():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    cfg = expand_world(raw) if raw.get("format_version") == "2.0" else raw
    return SimulationEngine(cfg, NoopLLM(), dry_run=True)


def test_activate_unread_beats_inbox():
    eng = _engine()
    yuki = eng.characters["Yuki"]
    elias = eng.characters["Elias"]
    yuki.set_available()
    elias.set_available()
    yuki.add_pending_message("Elias", "想找你聊聊误差项")
    note_search_hits(yuki, [{"arxiv_id": "1712.01271", "title": "p-adic L"}])

    eng._handle_activate(Event(time=eng.clock, type="activate", actor="Yuki"), verbose=False)

    assert any(m.get("from") == "Elias" for m in yuki.state.pending_messages)
    reads = [
        e for e in eng.queue._heap
        if e[2].type == "tool_use"
        and e[2].actor == "Yuki"
        and e[2].data.get("tool") == "read_arxiv"
        and e[2].data.get("arxiv_id") == "1712.01271"
    ]
    assert reads


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                import traceback
                traceback.print_exc()
    raise SystemExit(failed)
