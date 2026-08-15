"""World-authored skills — loaded at community generation, injected by phase.

Engine does not invent methodology. Worlds declare `world.skills: [research]`
(and optionally `world.vocation: research`). Text lives in:

  1. worlds/<name>/skills/<id>.md     (world override)
  2. docs/skills/<id>.md              (shared default)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)


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


def load_world_skills(
    world: dict,
    world_dir: Optional[Path] = None,
) -> dict[str, str]:
    """Load skill markdown keyed by id. Research vocation implies research skill."""
    ids = list(world.get("skills") or [])
    if isinstance(ids, str):
        ids = [ids]
    voc = str(world.get("vocation") or "").strip().lower()
    if voc == "research" and "research" not in ids:
        ids = ["research"] + ids
    out: dict[str, str] = {}
    for sid in ids:
        sid = str(sid).strip()
        if not sid:
            continue
        text = load_skill_text(sid, world_dir)
        if text.strip():
            out[sid] = text
    return out


def skill_section(text: str, heading: str) -> str:
    """Extract a `## heading` block (case-insensitive) until the next `##`."""
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


def skill_phase_block(
    skills_text: Optional[dict],
    *,
    skill_id: str = "research",
    phase: str = "",
    max_chars: int = 1100,
) -> str:
    """Stance + Cycle (always) + optional phase slice for prompts."""
    raw = (skills_text or {}).get(skill_id) or ""
    if not raw:
        return ""
    parts = []
    stance = skill_section(raw, "Stance")
    cycle = skill_section(raw, "Cycle")
    if stance:
        parts.append("Stance:\n" + stance)
    if cycle:
        parts.append("Cycle:\n" + cycle)
    if phase:
        body = skill_section(raw, phase)
        if body:
            parts.append(f"{phase}:\n{body}")
    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


# Default research-soul seed (identity, not a problem). Worlds may override
# via world.vocation_soul. Never copied into core_belief as a conjecture.
DEFAULT_RESEARCH_SOUL = {
    "vocation": "research",
    "vocation_stance": (
        "A researcher, not an engineer. Questions may stay open. "
        "Choose a direction, review peers, then carve a working unit. "
        "If the object lives in another field, open that field. "
        "A failed probe is data — not a verdict that the horizon is dead."
    ),
}

# Shared researcher habits (world.vocation_soul.traits may override).
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
    """Fill vocation fields without overwriting authored personality."""
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
