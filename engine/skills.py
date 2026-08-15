"""Character skills — created from templates, grown by practice.

Engine role
-----------
The engine is a *factory*: it can instantiate a skill onto a character from a
catalog template (`docs/skills/<id>.md` or `worlds/<name>/skills/<id>.md`).
It does **not** dump catalog text into every world prompt.

Character role
--------------
Each character carries a living skill book (on Soul, sibling of identity):

    skills:
      research:
        id: research
        level: 0.24
        moves: ["deep-read 1806.01678", "wrote unit claim"]
        notes: ["next: contour for psi(x)"]

Skills grow the way Memory and Soul grow: practice after study / read / write /
code. Prompts inject *this character's* book, not the world's manifesto.

World YAML
----------
  skill_catalog: [research]   # templates available to open
  vocation: research          # seeds stance + opens `research` on each character
  characters[].skills: [research]   # optional extra seeds
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_SKILL_ID = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def skill_search_paths(world_dir: Optional[Path] = None) -> list[Path]:
    paths = []
    if world_dir:
        paths.append(Path(world_dir) / "skills")
    paths.append(PROJECT_ROOT / "docs" / "skills")
    return paths


def load_skill_text(skill_id: str, world_dir: Optional[Path] = None) -> str:
    name = f"{skill_id}.md"
    for folder in skill_search_paths(world_dir):
        path = folder / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def skill_section(text: str, heading: str) -> str:
    if not text or not heading:
        return ""
    want = heading.strip().lower()
    matches = list(_H2.finditer(text))
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == want:
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            return text[start:end].strip()
    return ""


def list_catalog_ids(world: Optional[dict] = None, world_dir: Optional[Path] = None) -> list[str]:
    """Template ids this world may *open* on characters — not prompt dumps."""
    world = world or {}
    raw = world.get("skill_catalog") or world.get("skills") or []
    if isinstance(raw, str):
        raw = [raw]
    ids = [str(s).strip() for s in raw if str(s).strip()]
    voc = str(world.get("vocation") or "").strip().lower()
    if voc == "research" and "research" not in ids:
        if load_skill_text("research", world_dir):
            ids = ["research"] + ids
    out, seen = [], set()
    for sid in ids:
        if not _SKILL_ID.match(sid) or sid in seen:
            continue
        if load_skill_text(sid, world_dir):
            seen.add(sid)
            out.append(sid)
    return out


def seed_skill_ids(char_cfg: dict, world: Optional[dict] = None, world_dir: Optional[Path] = None) -> list[str]:
    """Which skills this character should open at birth."""
    catalog = set(list_catalog_ids(world, world_dir))
    raw = char_cfg.get("skills") or (char_cfg.get("soul") or {}).get("skills") or []
    if isinstance(raw, dict):
        raw = list(raw.keys())
    if isinstance(raw, str):
        raw = [raw]
    ids = [str(s).strip() for s in raw if str(s).strip()]
    voc = str((world or {}).get("vocation") or "").strip().lower()
    if voc == "research" and "research" in catalog and "research" not in ids:
        ids.append("research")
    return [s for s in ids if s in catalog or _SKILL_ID.match(s)]


def create_skill_record(
    skill_id: str,
    *,
    world_dir: Optional[Path] = None,
    day: int = 1,
) -> Optional[dict]:
    """Instantiate a catalog template onto a character. Snapshot stance only."""
    skill_id = (skill_id or "").strip().lower()
    if not _SKILL_ID.match(skill_id):
        return None
    text = load_skill_text(skill_id, world_dir)
    stance = skill_section(text, "Stance") if text else ""
    if not stance:
        stance = skill_section(text, "Cycle")[:240] if text else ""
    return {
        "id": skill_id,
        "level": 0.08,
        "opened_day": int(day or 0),
        "practices": 0,
        "moves": [],
        "notes": [],
        "stance": " ".join(stance.split())[:280],
    }


def open_skill(
    book: dict,
    skill_id: str,
    *,
    world_dir: Optional[Path] = None,
    day: int = 0,
) -> bool:
    book = book if isinstance(book, dict) else {}
    skill_id = (skill_id or "").strip().lower()
    if skill_id in book:
        return False
    rec = create_skill_record(skill_id, world_dir=world_dir, day=day)
    if not rec:
        return False
    book[skill_id] = rec
    return True


def practice_skill(
    book: dict,
    skill_id: str,
    move: str = "",
    *,
    note: str = "",
    day: int = 0,
    amount: float = 0.04,
) -> bool:
    """Grow an already-open skill. No-op if the character does not have it."""
    rec = (book or {}).get(skill_id)
    if not isinstance(rec, dict):
        return False
    rec["practices"] = int(rec.get("practices") or 0) + 1
    rec["level"] = min(1.0, float(rec.get("level") or 0) + max(0.01, float(amount)))
    rec["last_practiced"] = int(day or 0)
    move = " ".join((move or "").split())[:80]
    if move:
        moves = [str(m) for m in (rec.get("moves") or []) if str(m).strip()]
        if move not in moves:
            moves.append(move)
        rec["moves"] = moves[-8:]
    note = " ".join((note or "").split())[:100]
    if note:
        notes = [str(n) for n in (rec.get("notes") or []) if str(n).strip()]
        if note not in notes:
            notes.append(note)
        rec["notes"] = notes[-5:]
    return True


def format_skill_book(book: Optional[dict], *, phase: str = "", max_chars: int = 700) -> str:
    """Prompt slice: this character's living skills, not the catalog manifesto."""
    if not book:
        return ""
    parts = []
    for sid, rec in list(book.items())[:6]:
        if not isinstance(rec, dict):
            continue
        lv = float(rec.get("level") or 0)
        n = int(rec.get("practices") or 0)
        line = f"- {sid} lv {lv:.2f} ({n} practices)"
        moves = rec.get("moves") or []
        if moves:
            line += "\n  recent: " + "; ".join(str(m)[:50] for m in moves[-3:])
        notes = rec.get("notes") or []
        if notes:
            line += "\n  note: " + str(notes[-1])[:80]
        # Apprentice still needs the template stance; later the book speaks
        stance = (rec.get("stance") or "").strip()
        if stance and lv < 0.28:
            line += "\n  method: " + stance[:200]
        parts.append(line)
    if not parts:
        return ""
    text = "Your skills (earned, growing — not a world dump):\n" + "\n".join(parts)
    if phase and "research" in (book or {}) and float((book.get("research") or {}).get("level") or 0) < 0.28:
        raw = load_skill_text("research")
        extra = skill_section(raw, phase) if raw else ""
        if extra:
            text += f"\n[{phase}] " + " ".join(extra.split())[:180]
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def practice_from_tool(tool_name: str, params: Optional[dict] = None, result_ok: bool = True) -> Optional[tuple]:
    """Map a tool use to (skill_id, move, amount) if it should grow a skill."""
    if not result_ok:
        return None
    params = params or {}
    if tool_name == "read_arxiv":
        aid = (params.get("arxiv_id") or params.get("query") or "")[:40]
        return ("research", f"deep-read {aid}".strip(), 0.06)
    if tool_name == "search_arxiv":
        q = (params.get("query") or "")[:40]
        return ("research", f"search {q}".strip(), 0.03)
    if tool_name == "search_web":
        return ("research", "web frontier hunt", 0.03)
    if tool_name == "write_paper":
        return ("research", "wrote unit claim", 0.05)
    if tool_name == "run_code":
        return ("research", "ran killable probe", 0.04)
    return None


# ── Vocation identity (not a skill dump) ──────────────────────

DEFAULT_RESEARCH_SOUL = {
    "vocation": "research",
    "vocation_stance": (
        "A researcher, not an engineer. Questions may stay open. "
        "Choose a direction, review peers, then carve a working unit. "
        "If the object lives in another field, open that field. "
        "A failed probe is data — not a verdict that the horizon is dead."
    ),
}

DEFAULT_RESEARCH_TRAITS = [
    "Follow a mismatch even if it ruins today's plan (curiosity)",
    "A famous name — including your own — is a citation, not a proof",
    "A typo must not halt the read; go past the compilation error",
    "Post one small unfinished idea; do not disappear to polish it",
    "If you cannot sketch the details, you do not understand it yet",
    "Write a baseline that can die before you defend it",
    "If the object has another language, open that field",
    "Collaboration stall is not a reason to stop the working unit",
]


def _normalize_traits(raw) -> list[str]:
    out: list[str] = []
    if not raw:
        return out
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        if isinstance(item, dict):
            habit = (item.get("habit") or item.get("trait") or item.get("name") or "").strip()
        else:
            habit = str(item).strip()
        if habit and habit not in out:
            out.append(habit[:160])
    return out[:10]


def inject_research_soul(soul: dict, vocation_soul: Optional[dict] = None) -> dict:
    """Fill vocation identity fields only — does not attach catalog text."""
    out = dict(soul or {})
    seed = dict(DEFAULT_RESEARCH_SOUL)
    extra = vocation_soul if isinstance(vocation_soul, dict) else {}
    if extra.get("stance") or extra.get("vocation_stance"):
        seed["vocation_stance"] = str(
            extra.get("vocation_stance") or extra.get("stance")
        ).strip()
    if extra.get("vocation"):
        seed["vocation"] = str(extra["vocation"]).strip()
    traits = _normalize_traits(extra.get("traits")) or list(DEFAULT_RESEARCH_TRAITS)

    if not str(out.get("vocation") or "").strip():
        out["vocation"] = seed["vocation"]
    if not str(out.get("vocation_stance") or "").strip():
        out["vocation_stance"] = seed["vocation_stance"]
    if not out.get("vocation_traits"):
        out["vocation_traits"] = traits
    return out


def bind_character_skills(char, soul) -> None:
    """Attach this character's living skill book for prompts."""
    if char is None:
        return
    book = (soul.data.get("skills") if soul is not None else None) or {}
    if not isinstance(book, dict):
        book = {}
    char._skill_book = book
    char._skill_context = format_skill_book(book)


def character_skill_hint(char, phase: str = "") -> str:
    """Prompt slice: character book first, then short grain fallback."""
    book = getattr(char, "_skill_book", None) or {}
    if book:
        return format_skill_book(book, phase=phase)
    ctx = (getattr(char, "_skill_context", "") or "").strip()
    if ctx:
        return ctx
    return (getattr(char, "_research_protocol", "") or "").strip()


# Back-compat no-ops so old call sites do not dump the catalog
def load_world_skills(world: dict, world_dir: Optional[Path] = None) -> dict[str, str]:
    """Deprecated. Catalog ids only — empty text map (do not stuff prompts)."""
    return {}


def skill_phase_block(
    skills_text: Optional[dict],
    *,
    skill_id: str = "research",
    phase: str = "",
    max_chars: int = 1100,
) -> str:
    """Deprecated world-dump helper. Returns empty; use format_skill_book."""
    return ""
