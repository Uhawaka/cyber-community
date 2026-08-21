#!/usr/bin/env python3
"""P0 knowledge commune: search off, no engine-authored query, object can ground."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.character import Character
from engine.engine import SimulationEngine
from engine.events import Event
from engine.literature import search_is_enabled
from engine.work_queue import (
    adopt_working_object,
    agent_search_query,
    artifact_has_source,
    forced_decision,
    looks_like_question,
    public_speech_ok,
    public_topic,
)
from engine.world_builder import expand_world


class NoopLLM:
    def chat(self, *a, **k):
        return "S"

    def think(self, *a, **k):
        return "S"


def _math_cfg():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    return expand_world(raw) if raw.get("format_version") == "2.0" else raw


def test_math_commune_search_is_on_demand():
    cfg = _math_cfg()
    eng = SimulationEngine(cfg, NoopLLM(), dry_run=True)
    assert search_is_enabled(eng.world_frame) is True
    names = [t["name"] for t in (eng.tool_registry.list_tools() if eng.tool_registry else [])]
    assert "search_arxiv" in names
    assert "search_web" in names
    assert "run_code" in names
    assert "read_arxiv" in names


def test_agent_search_query_rejects_slogans():
    assert agent_search_query("Beale-Kato-Majda blow-up") == "Beale-Kato-Majda blow-up"
    assert agent_search_query("open problems mathematics") == ""
    assert agent_search_query("从验证转向作为检验标准") == ""
    assert agent_search_query("") == ""


def test_bootstrap_does_not_schedule_observe():
    from engine.events import EventQueue

    eng = SimulationEngine(_math_cfg(), NoopLLM(), dry_run=True)
    eng.dry_run = False
    eng.queue = EventQueue()
    eng.bootstrap()
    types = []
    while eng.queue:
        types.append(eng.queue.pop().type)
    assert "observe_world" not in types
    assert "activate" in types


def test_observe_without_agent_query_does_not_search():
    eng = SimulationEngine(_math_cfg(), NoopLLM(), dry_run=True)
    # Even if someone re-enables tools, no query means no request
    eng.world_frame.setdefault("literature", {})["enabled"] = True
    yuki = eng.characters["Yuki"]
    before = list(getattr(yuki.state, "unread_arxiv", None) or [])
    eng._handle_observe_world(
        Event(time=eng.clock, type="observe_world", actor="Yuki"),
        verbose=False,
    )
    assert (getattr(yuki.state, "unread_arxiv", None) or []) == before
    assert not any(
        e.get("type") == "tool_use" and e.get("tool") in ("search_arxiv", "search_web")
        for e in eng.event_log
    )


def test_working_object_grounds_artifact():
    char = Character("Elias", {"seed": "x"})
    assert not artifact_has_source("HJB verification for a linear-quadratic case", char)
    adopt_working_object(char, "HJB verification theorem")
    assert char.state.working_object == "HJB verification theorem"
    assert artifact_has_source(
        "following the HJB verification theorem we write the generator",
        char,
    )
    adopt_working_object(char, "open problems mathematics")
    assert char.state.working_object == "HJB verification theorem"
    adopt_working_object(char, "从验证归约的正确性转向关注归约尺寸的常数因子，但核心问题仍是P vs NP。")
    assert char.state.working_object == "HJB verification theorem"
    cook = Character("Elias", {})
    cook.state.current_focus = "Cook–Levin SAT reduction as a working unit"
    paper = (
        "Working unit: Cook–Levin 构造中 SAT 公式尺寸为 O(T(n)^2)。"
        "Claim: k 固定时不影响 P vs NP 的判定。"
    )
    assert artifact_has_source(paper, cook)
    assert not artifact_has_source("我们对复杂性有了更深的感觉。", cook)


def test_knowledge_decision_demotes_search_only_when_off():
    eng = SimulationEngine(_math_cfg(), NoopLLM(), dry_run=True)
    keep = eng._knowledge_decision(
        {"type": "tool", "tool": "search_arxiv", "topic": "HJB", "label": "搜"}
    )
    assert keep["type"] == "tool"
    assert keep["tool"] == "search_arxiv"
    eng.world_frame.setdefault("literature", {})["enabled"] = False
    out = eng._knowledge_decision(
        {"type": "tool", "tool": "search_arxiv", "topic": "HJB", "label": "搜"}
    )
    assert out["type"] == "study"
    out2 = eng._knowledge_decision({"type": "observe_world", "topic": "HJB"})
    assert out2["type"] == "study"


def test_public_speech_needs_named_object():
    a = Character("Elias", {})
    b = Character("Yuki", {})
    adopt_working_object(a, "HJB verification theorem")
    sermon = "我们对 L-函数和模性有了更深的感觉，方向很深。"
    assert not public_speech_ok(sermon, a, b)
    ok = "The HJB verification theorem needs a C^1 value function here."
    assert public_speech_ok(ok, a, b)
    assert looks_like_question("这一步缺什么假设？")
    assert public_topic(a) == "HJB verification theorem"
    assert public_topic(b, "open problems mathematics") == ""
    # P2 sniff: punctuation / word-order must not hide a named object
    adopt_working_object(b, "Rank-1 Eisenstein series at s=1/2.")
    assert b.state.working_object == "Rank-1 Eisenstein series at s=1/2"
    talk = "我在对付 rank-1 Eisenstein series 在 s=1/2 的取值——它是 L-function 的影子。"
    assert public_speech_ok(talk, b)
    assert not public_speech_ok("我们对 L-函数有了更深的感觉。", b)


def test_socialize_without_object_becomes_study():
    eng = SimulationEngine(_math_cfg(), NoopLLM(), dry_run=True)
    yuki = eng.characters["Yuki"]
    out = eng._ground_public_decision(
        yuki, {"type": "socialize", "topic": "", "label": "聊"}
    )
    assert out["type"] == "study"
    adopt_working_object(yuki, "linear-quadratic regulator")
    out2 = eng._ground_public_decision(
        yuki, {"type": "socialize", "topic": "", "label": "聊"}
    )
    assert out2["type"] == "socialize"
    assert "linear-quadratic" in out2["topic"]
    yuki.state.working_object = None
    yuki.state.current_focus = None
    reply = eng._ground_public_decision(
        yuki,
        {"type": "socialize", "topic": "", "inbox_reply": True, "target": "Elias"},
    )
    assert reply["type"] == "socialize"


def test_collision_force_is_study_not_search():
    char = Character("Nora", {})
    char.state.collision_streak = 3
    d = forced_decision(char)
    assert d["type"] == "study"
    assert d.get("tool") != "search_arxiv"


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
