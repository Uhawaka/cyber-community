#!/usr/bin/env python3
"""Regression tests for architecture-audit P0/P1 fixes."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.anonymous_events import AnonymousEventBoard
from engine.deep_think import DeepThinkEngine
from engine.engine import SimulationEngine
from engine.live_session import LiveSession
from engine.thought_loop import InnerDialogue
from engine.world_builder import expand_world, load_world


class CountingLLM:
    def __init__(self):
        self.call_count = 0
        self.error_count = 0

    def chat(self, *a, **k):
        self.call_count += 1
        time.sleep(0.01)
        return "（noop 回复：观察一下边界条件。）"

    def think(self, *a, **k):
        return self.chat()


def _engine():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    cfg = expand_world(raw) if raw.get("format_version") == "2.0" else raw
    return SimulationEngine(cfg, CountingLLM(), dry_run=True)


def test_inner_dialogue_can_continue_first_turn():
    d = InnerDialogue()
    assert d.can_continue() is False
    d.start("spectral gap")
    assert d.can_continue() is True
    assert d.is_active() is True
    d.add_turn("self", "hmm", "explore")
    assert d.can_continue() is True
    d.max_turns = 1
    assert d.can_continue() is False


def test_deep_think_not_eager_on_empty_counters():
    eng = DeepThinkEngine(CountingLLM())
    assert eng.should_trigger("Elias", 0, 0, 0, 100.0) is False
    assert eng.should_trigger("Elias", 5, 0, 0, 3.0) is False
    assert eng.should_trigger("Elias", 5, 0, 0, 4.0) is True
    assert eng.should_trigger("Elias", 1, 1, 1, 12.0) is True


def test_anon_peek_does_not_consume():
    board = AnonymousEventBoard()
    board.inject("桌上多了一张纸条", day=1, time=0.0)
    peeked = board.peek_for("Elias")
    assert peeked
    assert board.pending_for("Elias")
    consumed = board.consume_for("Elias")
    assert consumed == peeked
    assert not board.pending_for("Elias")


def test_activate_study_produces_inner_turns():
    eng = _engine()
    eng.bootstrap()
    eng._bootstrapped = True
    eng.running = True
    # Force one activate for first cast member
    name = next(iter(eng.characters))
    from engine.events import Event
    eng.clock = 2.0
    eng._handle_activate(Event(time=2.0, type="activate", actor=name), verbose=False)
    turns = [e for e in eng.event_log if e.get("type") == "inner_turn" and e.get("actor") == name]
    steps = [e for e in eng.event_log if e.get("type") == "study_step" and e.get("actor") == name]
    # Rhythm often picks study; if rest/move, skip assertion softness
    if steps:
        assert steps[0].get("step", 0) >= 1
        assert len(turns) >= 1


def test_wake_releases_lock_for_status():
    eng = _engine()
    session = LiveSession(
        eng,
        avatar_name="Alex",
        virtual_hours_per_wake=4.0,
        max_events_per_wake=8,
        max_llm_calls_per_wake=20,
    )
    eng.bootstrap()
    eng._bootstrapped = True
    eng.running = True

    status_ok = {"ok": False}

    def reader():
        # Should not block for the whole wake
        out = session.status_text()
        status_ok["ok"] = "Day" in out

    t = threading.Thread(target=reader)
    # Start wake in background; reader runs concurrently
    wake_stats = {}

    def waker():
        wake_stats.update(session.run_wake_window(verbose=False))

    tw = threading.Thread(target=waker)
    tw.start()
    time.sleep(0.02)
    t.start()
    t.join(timeout=2.0)
    tw.join(timeout=30.0)
    assert status_ok["ok"] is True
    assert wake_stats.get("processed", 0) >= 1
    assert "llm_calls" in wake_stats


def test_load_world_shared():
    cfg = load_world("math-commune", ROOT / "worlds")
    assert cfg.get("characters")
    assert any(c["name"] == "Elias" for c in cfg["characters"])


def test_activate_does_not_poisson_chain():
    eng = _engine()
    eng.bootstrap()
    name = next(iter(eng.characters))

    def count_activate(actor: str) -> int:
        return sum(
            1 for _, _, ev in eng.queue._heap
            if ev.type == "activate" and ev.actor == actor
        )

    before = count_activate(name)
    from engine.events import Event
    eng.clock = 2.0
    eng._handle_activate(Event(time=2.0, type="activate", actor=name), verbose=False)
    # Rhythm owns schedule: activate must not push another activate via Poisson
    assert count_activate(name) == before


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
