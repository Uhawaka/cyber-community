#!/usr/bin/env python3
"""World seed pipeline completeness for math-commune."""

import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.culture import resolve_world_frame, format_practice_context
from engine.engine import SimulationEngine
from engine.world_builder import expand_world


class NoopLLM:
    def chat(self, *a, **k):
        return "{}"

    def think(self, *a, **k):
        return "[noop]"


def _cfg():
    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    return expand_world(raw)


def test_seed_yaml_has_library_readings_tools():
    cfg = _cfg()
    world = cfg["world"]
    lib = world.get("seed_library") or []
    readings = world.get("seed_readings") or []
    assert len(lib) >= 6
    assert any("claymath.org" in str(x) for x in lib)
    assert any("annals" in str(x).lower() for x in lib)
    assert any("arxiv.org" in str(x) for x in lib)
    assert len(readings) >= 2
    assert any("Re(ρ)=1/2" in str(x) or "real part 1/2" in str(x) for x in readings)
    tools = [t["name"] for t in cfg.get("tools") or []]
    assert "search_arxiv" in tools and "read_arxiv" in tools
    assert (world.get("open_problems") or []) == []
    for c in cfg["characters"]:
        assert (c.get("domains") or []) == []


def test_practice_prioritizes_math_readings_over_url_shelf():
    frame = resolve_world_frame(_cfg())
    text = format_practice_context(frame, max_chars=3200)
    assert "开箱即读的数学原文" in text
    assert "Riemann" in text or "zeta" in text.lower() or "ζ" in text
    # Readings block should appear before the long URL shelf
    assert text.index("开箱即读") < text.index("启动种子书架")


def test_deposit_and_memory_and_commons_spawn():
    cfg = _cfg()
    with tempfile.TemporaryDirectory() as tmp:
        # Point output into tmp via dry_run engine path
        engine = SimulationEngine(cfg, NoopLLM(), dry_run=True)
        # dry_run still deposits into temp output_dir
        archive = engine.environment.nodes["archive"]
        commons = engine.environment.nodes["commons"]
        blob = " ".join(
            str(c.get("content") if isinstance(c, dict) else c)
            for c in (archive.contents + commons.contents)
        )
        assert "claymath.org" in blob.lower()
        assert "Riemann" in blob or "zeta" in blob.lower() or "ζ" in blob

        elias_study = engine.environment.nodes.get("elias_study")
        assert elias_study is not None
        study_blob = " ".join(
            str(c.get("content") if isinstance(c, dict) else c)
            for c in elias_study.contents
        )
        assert "社区启动种子" in study_blob

        mem = engine.memories["Elias"]
        assert any("seed_shelf" in (e.tags or []) for e in mem.episodes)

        engine.bootstrap()
        assert engine.environment.character_locations["Elias"] == "commons"
        assert engine.environment.character_locations["Nora"] == "commons"


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
                traceback.print_exc()
    raise SystemExit(failed)
