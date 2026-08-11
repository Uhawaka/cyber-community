#!/usr/bin/env python3
"""Core unit tests — no live LLM required."""

import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.anonymous_events import frame_message, AnonymousEventBoard
from engine.memory import Memory, Episode
from engine.soul import SoulFile
from engine.tools import validate_sandboxed_code, ToolRegistry
from engine.engine import SimulationEngine
from engine.sociology import CommunityEngine


class NoopLLM:
    def chat(self, *args, **kwargs):
        return "[noop]"

    def think(self, *args, **kwargs):
        return "[noop]"


def test_frame_message_never_mentions_user():
    ftype, framed = frame_message("质数间隔有新想法", framing="letter")
    assert ftype == "letter"
    assert "质数间隔" in framed
    assert "用户" not in framed
    assert "创造者" not in framed


def test_anonymous_board_targeting():
    board = AnonymousEventBoard()
    board.inject("给 Elias 的线索", target="Elias", framing="discovery")
    assert board.pending_for("Elias")
    assert not board.pending_for("Yuki")
    texts = board.consume_for("Elias")
    assert len(texts) == 1
    assert board.consume_for("Elias") == []


def test_sandbox_blocks_dangerous_code():
    assert validate_sandboxed_code("import os\nos.system('ls')") is not None
    assert validate_sandboxed_code("eval('1+1')") is not None
    assert validate_sandboxed_code("open('/etc/passwd').read()") is not None
    assert validate_sandboxed_code("print(sum(range(10)))") is None
    assert validate_sandboxed_code("import math\nprint(math.sqrt(2))") is None


def test_run_code_sandbox_executes_safe_code():
    with tempfile.TemporaryDirectory() as tmp:
        reg = ToolRegistry(
            [{"name": "run_code", "timeout_seconds": 10, "sandbox": True}],
            Path(tmp),
        )
        result = reg.execute(
            "run_code",
            "Tester",
            {"code": "print(2 + 2)\n", "topic": "arith"},
        )
        assert result.success
        assert "4" in result.output

        blocked = reg.execute(
            "run_code",
            "Tester",
            {"code": "import subprocess\nprint(1)\n", "topic": "bad"},
        )
        assert not blocked.success
        assert "不允许" in blocked.output or "沙箱" in blocked.output


def test_memory_consolidate_promotes_facts():
    with tempfile.TemporaryDirectory() as tmp:
        mem = Memory(str(Path(tmp) / "m.json"), max_episodes=200)
        for i in range(8):
            mem.remember(Episode(
                id=f"e{i}",
                time=float(i),
                day=1,
                type="study",
                summary=f"Low-lying density needs a tighter error term {i}",
                detail="short",
                importance=0.9,
            ))
        # Stale low-importance episodes to compress
        for i in range(10):
            mem.remember(Episode(
                id=f"old{i}",
                time=float(i),
                day=-10,
                type="idle",
                summary=f"琐事 {i}",
                detail="",
                importance=0.1,
            ))
        stats = mem.consolidate_day(day=1, keep_recent_days=7)
        assert 1 <= stats["facts_added"] <= 3
        assert stats["compressed"] >= 5
        assert any(e.type == "compressed" for e in mem.episodes)


def test_memory_rejects_shell_facts_and_tool_promote():
    with tempfile.TemporaryDirectory() as tmp:
        mem = Memory(str(Path(tmp) / "m2.json"), max_episodes=200)
        assert mem.learn_fact("与Yuki讨论了从验证 RMT 失效转向构造判据") is False
        assert mem.learn_fact("RMT baseline fails for medium conductors in this family") is True
        assert len(mem.semantic_facts) == 1

        mem.remember(Episode(
            id="t1",
            time=1.0,
            day=2,
            type="tool_use",
            summary="使用了write_paper: 论文已保存: foo.md",
            detail="论文已保存: foo.md",
            importance=0.95,
        ))
        mem.remember(Episode(
            id="o1",
            time=2.0,
            day=2,
            type="observe",
            summary="翻阅了关于 spectral theory 的材料",
            detail="",
            importance=0.9,
        ))
        mem.remember(Episode(
            id="d1",
            time=3.0,
            day=2,
            type="deep_think",
            summary="insight",
            detail="Coordinate choice is part of the null model, not a post-hoc fix.",
            importance=0.9,
        ))
        stats = mem.consolidate_day(day=2, keep_recent_days=7)
        assert stats["facts_added"] == 1
        assert any("Coordinate choice" in f["fact"] for f in mem.semantic_facts)
        assert not any("论文已保存" in f["fact"] for f in mem.semantic_facts)
        assert not any("翻阅了" in f["fact"] for f in mem.semantic_facts)


def test_soul_calibrate_returns_note():
    with tempfile.TemporaryDirectory() as tmp:
        soul = SoulFile(str(Path(tmp) / "s.yaml"))
        soul.data["identity"] = {
            "who_i_am": "一个只信证明的人",
            "core_belief": "证明比直觉更重要",
            "how_i_think": "层层推进",
            "how_i_protect": "",
            "what_drives_me": "",
            "voice": [],
        }
        soul.save()
        note = soul.calibrate(7, ["今天和别人聊了很多"])
        assert note
        assert "core belief" in note.lower() or "核心信念" in note
        assert soul.data["meta"]["last_calibrated_day"] == 7


def test_community_snapshot():
    society = CommunityEngine({"Elias": object(), "Yuki": object()})
    society.spread_rumor("有人在公共区留下一张纸条", "unknown", 1)
    snap = society.get_community_snapshot()
    assert "地位排序" in snap or "社区" in snap


def test_engine_inject_anonymous_dry_run():
    config_path = ROOT / "worlds" / "math-commune" / "community.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    engine = SimulationEngine(config, NoopLLM(), dry_run=True)
    framed = engine.inject_anonymous_event(
        "黑板上多了一行奇怪的公式",
        framing="environment",
        verbose=False,
    )
    assert "公式" in framed or "奇怪" in framed

    engine.run(max_days=1, verbose=False)

    anon_events = [e for e in engine.event_log if e["type"] == "anonymous_event"]
    assert anon_events
    # At least one character should have remembered the disturbance
    remembered = False
    for mem in engine.memories.values():
        if any(ep.type == "anonymous_event" for ep in mem.episodes):
            remembered = True
            break
    assert remembered


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except Exception:
            failed += 1
            print(f"❌ {fn.__name__}")
            traceback.print_exc()
    if failed:
        sys.exit(1)
    print(f"\n全部通过 ({len(tests)})")
