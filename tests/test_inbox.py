#!/usr/bin/env python3
"""Inbox-first (Moltbook-style) obligations."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.engine import SimulationEngine
from engine.events import Event
from engine.inbox import (
    build_inbox,
    format_inbox_briefing,
    suggest_inbox_action,
    consume_messages_from,
    community_inbox_snapshot,
)
from engine.world_builder import expand_world
from engine.collaboration import CollaborationBoard


class NoopLLM:
    def chat(self, *a, **k):
        return "T"

    def think(self, *a, **k):
        return "T"


def _engine():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    cfg = expand_world(raw) if raw.get("format_version") == "2.0" else raw
    return SimulationEngine(cfg, NoopLLM(), dry_run=True)


def test_pending_message_forces_reply_target():
    eng = _engine()
    elias = eng.characters["Elias"]
    yuki = eng.characters["Yuki"]
    elias.set_available()
    yuki.set_available()
    yuki.add_pending_message("Elias", "想找你聊聊误差项")

    inbox = build_inbox(eng, "Yuki")
    assert inbox["has_priority"]
    brief = format_inbox_briefing(inbox)
    assert "Elias" in brief
    assert "未读留言" in brief

    decision = suggest_inbox_action(eng, "Yuki", inbox)
    assert decision is not None
    assert decision["type"] == "socialize"
    assert decision["target"] == "Elias"
    assert decision.get("inbox_reply") is True


def test_activate_consumes_inbox_and_schedules_collision():
    eng = _engine()
    eng.bootstrap()
    eng._bootstrapped = True
    eng.running = True
    yuki = eng.characters["Yuki"]
    elias = eng.characters["Elias"]
    yuki.set_available()
    elias.set_available()
    yuki.add_pending_message("Elias", "[Elias 想找你聊聊]")

    eng._handle_activate(Event(time=eng.clock, type="activate", actor="Yuki"), verbose=False)
    # Message should be consumed when inbox-reply socialize runs
    assert not any(m.get("from") == "Elias" for m in yuki.state.pending_messages)
    # Collision (or leave-message path) should appear soon in queue or log
    pending_collisions = [
        e for e in eng.queue._heap
        if e[2].type == "collision" and e[2].actor == "Yuki" and e[2].target == "Elias"
    ]
    assert pending_collisions or any(
        e.get("type") == "collision" and e.get("initiator") == "Yuki"
        for e in eng.event_log
    )


def test_collab_suggests_partner():
    eng = _engine()
    eng.collab.create(
        topic="range-independent criterion",
        proposer="Pavel",
        participants=["Pavel", "Nora"],
        day=1,
    )
    decision = suggest_inbox_action(eng, "Pavel")
    assert decision is not None
    assert decision["target"] == "Nora"
    assert "协作" in decision["label"]


def test_community_snapshot_lists_backlog():
    eng = _engine()
    eng.characters["Nora"].add_pending_message("Pavel", "看这个判据")
    snap = community_inbox_snapshot(eng)
    assert "Nora" in snap
    assert "未读留言" in snap


def test_consume_messages_from():
    eng = _engine()
    char = eng.characters["Elias"]
    char.add_pending_message("Yuki", "a")
    char.add_pending_message("Pavel", "b")
    char.add_pending_message("Yuki", "c")
    got = consume_messages_from(char, "Yuki")
    assert len(got) == 2
    assert all(m["from"] == "Yuki" for m in got)
    assert len(char.state.pending_messages) == 1
    assert char.state.pending_messages[0]["from"] == "Pavel"


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
