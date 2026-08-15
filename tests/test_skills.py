#!/usr/bin/env python3
"""Character-owned skills: catalog creates, practice grows, world does not dump."""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.skills import (
    create_skill_record,
    format_skill_book,
    list_catalog_ids,
    open_skill,
    practice_from_tool,
    practice_skill,
    seed_skill_ids,
)
from engine.soul import SoulFile
from engine.world_builder import load_world


def test_catalog_is_ids_not_prompt_dump():
    cfg = load_world("math-commune", ROOT / "worlds")
    world = cfg.get("world") or {}
    ids = list_catalog_ids(world, ROOT / "worlds" / "math-commune")
    assert "research" in ids
    assert not world.get("skills_text")


def test_math_commune_seeds_research_on_characters():
    cfg = load_world("math-commune", ROOT / "worlds")
    for char in cfg["characters"]:
        assert "research" in (char.get("skills") or []), char["name"]


def test_poets_do_not_get_research_skill():
    cfg = load_world("poets-salon", ROOT / "worlds")
    world = cfg.get("world") or {}
    assert "research" not in list_catalog_ids(world)
    for char in cfg["characters"]:
        assert "research" not in seed_skill_ids(char, world)


def test_open_and_practice_grows_book():
    book = {}
    assert open_skill(book, "research", day=1)
    assert not open_skill(book, "research", day=1)
    rec = book["research"]
    start = float(rec["level"])
    assert practice_skill(book, "research", "deep-read 1806.01678", day=2, amount=0.06)
    assert book["research"]["level"] > start
    assert book["research"]["practices"] == 1
    assert "1806.01678" in book["research"]["moves"][-1]


def test_practice_noop_without_skill():
    assert practice_skill({}, "research", "studied zeta") is False


def test_format_uses_character_moves_not_full_manifesto():
    rec = create_skill_record("research", day=1)
    rec["level"] = 0.40
    rec["practices"] = 4
    rec["moves"] = ["deep-read 1806.01678", "wrote unit claim"]
    rec["notes"] = ["next: contour for psi(x)"]
    text = format_skill_book({"research": rec})
    assert "research" in text
    assert "0.40" in text
    assert "deep-read" in text
    assert "contour" in text
    assert "Temperament" not in text
    assert "Tao" not in text


def test_tool_maps_to_research_practice():
    assert practice_from_tool("read_arxiv", {"arxiv_id": "1806.01678"}, True) == (
        "research",
        "deep-read 1806.01678",
        0.06,
    )
    assert practice_from_tool("read_arxiv", {"arxiv_id": "x"}, False) is None
    assert practice_from_tool("write_paper", {}, True)[0] == "research"


def test_soul_file_persists_skill_growth():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "Elias.yaml")
        soul = SoulFile(path)
        soul.init_from_config("Elias", {"skills": ["research"]}, world_name="Math Commune")
        assert "research" in soul.data["skills"]
        soul.practice_skill("research", "ran killable probe", day=3, amount=0.04)
        again = SoulFile(path)
        rec = again.data["skills"]["research"]
        assert rec["practices"] == 1
        assert "probe" in rec["moves"][-1]
        summary = again.get_context_summary()
        assert "Skills" in summary
        assert "research" in summary


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
