#!/usr/bin/env python3
"""Live hang windows + avatar talk (wait / urgent)."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.character import Character
from engine.engine import SimulationEngine
from engine.live_session import LiveSession, next_wake_after, parse_wake_times
from engine.world_builder import expand_world


class NoopLLM:
    def chat(self, *a, **k):
        return "（noop 回复）"

    def think(self, *a, **k):
        return "[noop]"


def _engine():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    cfg = expand_world(raw) if raw.get("format_version") == "2.0" else raw
    return SimulationEngine(cfg, NoopLLM(), dry_run=True)


def test_parse_and_next_wake():
    times = parse_wake_times("09:30,21:00,14:00")
    assert times == [(9, 30), (14, 0), (21, 0)]
    now = datetime(2026, 8, 11, 10, 0, 0)
    nxt = next_wake_after(now, times)
    assert nxt == datetime(2026, 8, 11, 14, 0, 0)
    now2 = datetime(2026, 8, 11, 22, 0, 0)
    nxt2 = next_wake_after(now2, times)
    assert nxt2 == datetime(2026, 8, 12, 9, 30, 0)


def test_run_slice_advances_without_finishing_forever():
    eng = _engine()
    eng.bootstrap()
    eng._bootstrapped = True
    eng.running = True
    stats = eng.run_slice(until_time=8.0, max_events=40, verbose=False)
    assert stats["processed"] >= 1
    assert eng.clock <= 8.0 + 1e-6
    # Queue should still have later events (Poisson / later rhythm)
    assert len(eng.queue) > 0


def test_suspend_resume_work():
    char = Character("Elias", {"autonomy": {}}, lam=0.5)
    char.set_busy()
    char.state.current_focus = "spectral estimates"
    assert char.suspend_work() is True
    assert char.state.status == "Available"
    assert char.state.suspended_work
    assert char.resume_work() is True
    assert char.state.status == "Busy"
    assert char.state.current_focus == "spectral estimates"
    assert char.state.suspended_work is None


def test_talk_busy_wait_message_and_urgent():
    eng = _engine()
    session = LiveSession(eng, avatar_name="Alex", wake_times=[(9, 30)])
    # Don't start hang thread — unit test talk paths only
    eng.bootstrap()
    eng._bootstrapped = True
    eng.running = True

    target = next(iter(eng.characters))
    char = eng.characters[target]
    char.set_busy()
    char.state.current_focus = "deep work"

    msg = session.talk(target, "在吗？")
    assert "正忙" in msg or "urgent" in msg

    reply = session.talk(target, "有个紧急问题", urgent=True)
    assert reply.startswith(f"{target}:")
    assert char.state.suspended_work is None  # resumed
    # Memory recorded
    mem = eng.memories[target]
    assert any(e.type == "avatar_talk" for e in mem.episodes)


def test_repl_status_and_quit():
    eng = _engine()
    session = LiveSession(eng, avatar_name="Alex")
    eng.bootstrap()
    eng._bootstrapped = True
    out, q = session.handle_line("status")
    assert "Day" in out
    assert q is False
    out, q = session.handle_line("who")
    assert "Elias" in out or "Yuki" in out
    out, q = session.handle_line("quit")
    assert q is True


def test_guide_ask_uses_observer_briefing():
    eng = _engine()
    session = LiveSession(eng, avatar_name="Alex")
    eng.bootstrap()
    eng._bootstrapped = True
    brief = session.observer_briefing()
    assert "Members:" in brief
    assert "Elias" in brief or "Yuki" in brief
    out, q = session.handle_line("ask 最近大家在忙什么？")
    assert q is False
    assert out.startswith("向导:")
    # Bare text with no focus → guide, not error
    out2, _ = session.handle_line("社区现在有意思吗？")
    assert out2.startswith("向导:")


def test_force_wake_processes_events():
    eng = _engine()
    session = LiveSession(
        eng,
        avatar_name="Alex",
        virtual_hours_per_wake=8.0,
        max_events_per_wake=30,
    )
    stats = session.force_wake()
    assert stats["processed"] >= 1
    assert session._wake_count == 1


def test_batch_main_path_still_runs():
    """Regression: batch run(max_days=1) still completes."""
    eng = _engine()
    eng.run(max_days=1, verbose=False)
    assert eng.day >= 1
    assert eng.running is False


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
