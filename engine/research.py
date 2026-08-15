"""Research grain + verdict discipline — engine-level, domain-agnostic.

Problem this solves
-------------------
Agents will happily *cite* a prize-class open problem (good) and then treat
today's session as if they should solve it — or, after one toy check, declare
the direction dead. Both are design failures, not intelligence failures.

Rules (default)
---------------
1. **Horizon ≠ working unit.** A cited famous/open problem is a horizon.
   Today's deliverable is a smaller, checkable unit.
2. **Success = move a working unit**, never "close the horizon" in a sim day
   unless the world explicitly allows it.
3. **No premature foreclosure.** "Infeasible / solved / dead" after one casual
   try is invalid. A closing verdict needs an *obligation* (what experiment or
   derivation would decide), what was actually tried, and remaining uncertainty.
4. Worlds override via `world.research` without engine forks.

Config shape (optional under world:)
------------------------------------
  research:
    grain: working_unit          # working_unit (default) | free
    allow_horizon_solve: false
    verdict_requires_obligation: true
    working_unit_kinds: []       # optional extra kinds for this world
"""

from __future__ import annotations

import re
from typing import Optional


DEFAULT_UNIT_KINDS = (
    "reconstruct",   # rebuild a known lemma / argument from a source
    "special_case",  # restrict the horizon to a checkable subclass
    "numerical_probe",
    "literature_map",
    "obstruction_log",  # name the next missing step; do not kill the direction
)

ALLOWED_STATUSES = (
    "open",
    "reconstructing",
    "probing",
    "obstructed",
    "narrowed",
    "withdrawn-with-obligation",
)

# Casual closure language — used for prompts + lightweight scoring
_PREMATURE_RE = re.compile(
    r"("
    r"不可行|不可证明|此路不通|方向死了|已经证完|已经解决|显然成立|显然不成立|"
    r"infeasible|impossible\b|dead end|this (approach|direction) (is|fails)|"
    r"we (have )?(thus |therefore )?(proved|solved|disproved)|"
    r"therefore (RH|BSD|the conjecture) (is|fails)"
    r")",
    re.I,
)

_OBLIGATION_RE = re.compile(
    r"("
    r"若要判定|还需要|下一步|缺的是|obligation|would decide|"
    r"kill criterion|可杀|反例条件|还没做|尚未"
    r")",
    re.I,
)


def resolve_research_config(
    world_or_frame: Optional[dict] = None,
    config: Optional[dict] = None,
) -> dict:
    """Merge world.research with safe defaults."""
    world: dict = {}
    if isinstance(world_or_frame, dict):
        if "research" in world_or_frame or "practice" in world_or_frame:
            world = world_or_frame
        elif isinstance(world_or_frame.get("world"), dict):
            world = world_or_frame["world"]
    if config and not world:
        world = (config.get("world") or {}) if isinstance(config, dict) else {}

    raw = world.get("research") if isinstance(world.get("research"), dict) else {}

    # Re-entry: already resolved
    if raw.get("_resolved") and "grain" in raw:
        return dict(raw)

    grain = str(raw.get("grain") or "working_unit").strip().lower()
    if grain not in ("working_unit", "free"):
        grain = "working_unit"

    kinds = raw.get("working_unit_kinds") or raw.get("unit_kinds") or []
    if isinstance(kinds, str):
        kinds = [kinds]
    kinds = [str(k).strip() for k in kinds if str(k).strip()]
    for k in DEFAULT_UNIT_KINDS:
        if k not in kinds:
            kinds.append(k)

    allow_solve = bool(raw.get("allow_horizon_solve", False))
    need_obl = raw.get("verdict_requires_obligation")
    if need_obl is None:
        need_obl = True

    return {
        "_resolved": True,
        "grain": grain,
        "allow_horizon_solve": allow_solve,
        "verdict_requires_obligation": bool(need_obl),
        "working_unit_kinds": kinds,
        "allowed_statuses": list(ALLOWED_STATUSES),
    }


def research_prompt_block(
    cfg_or_frame: Optional[dict] = None,
    *,
    phase: str = "",
) -> str:
    """Short grain line for the world. Character skill books live on Soul."""
    frame = cfg_or_frame or {}
    cfg = frame if frame.get("_resolved") else resolve_research_config(frame)
    if cfg.get("grain") == "free":
        return ""
    return (
        "Research grain: horizon ≠ today's work. Review peers before a Claim. "
        "Carve a working unit. Failed probe ≠ infeasible. Status needs a next obligation."
    )


def format_research_context(cfg_or_frame: Optional[dict] = None, max_chars: int = 900) -> str:
    text = research_prompt_block(cfg_or_frame)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def looks_like_premature_verdict(text: str) -> bool:
    """Heuristic: closing language without an obligation / next step."""
    blob = (text or "").strip()
    if not blob or not _PREMATURE_RE.search(blob):
        return False
    return not _OBLIGATION_RE.search(blob)


def score_research_note(text: str, *, cfg: Optional[dict] = None) -> dict:
    """Lightweight note audit — for probes / tests, not a judge of truth."""
    cfg = resolve_research_config(cfg) if cfg and not (cfg or {}).get("_resolved") else (cfg or resolve_research_config())
    blob = text or ""
    premature = looks_like_premature_verdict(blob)
    has_unit = bool(re.search(
        r"(reconstruct|special.?case|probe|lemma|Claim|工作单元|特例|复述|数值)",
        blob,
        re.I,
    ))
    claims_horizon_solved = bool(re.search(
        r"(证完|解决了|已证明).{0,20}(Riemann|RH|BSD|Hodge|千禧|millennium)|"
        r"(proved|solved).{0,20}(Riemann|RH|BSD|Hodge)",
        blob,
        re.I,
    ))
    ok = (not premature) and not (claims_horizon_solved and not cfg.get("allow_horizon_solve"))
    return {
        "ok": ok,
        "premature_verdict": premature,
        "claims_horizon_solved": claims_horizon_solved,
        "mentions_working_unit": has_unit,
    }
