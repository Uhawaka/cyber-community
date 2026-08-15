"""Observation Pipeline: characters observe the human / academic world.

Queries follow engine.literature policy:
  frontier (arXiv / primary web) → English
  optional vernacular web track → Chinese explanations when allowed
"""

from __future__ import annotations

from typing import Optional

from engine.literature import observation_query_pairs


OBSERVATION_SOURCES = [
    {
        "name": "arxiv_recent",
        "description": "Search recent arXiv papers related to living domains",
        "trigger": "periodic",
        "frequency_hours": 12,
    },
    {
        "name": "arxiv_specific",
        "description": "Search papers related to current research focus",
        "trigger": "study_milestone",
        "frequency_steps": 8,
    },
]


def get_observation_queries(
    char_research: dict | None,
    char_domain: str = "",
    domains: list | None = None,
    focus: str = "",
    *,
    world_or_frame: Optional[dict] = None,
    config: Optional[dict] = None,
) -> list:
    """Generate (query_type, query) pairs via literature search policy."""
    research = char_research or {}
    project = (research.get("project") or research.get("stuck_point") or "").strip()
    focus = (focus or project or "").strip()

    return observation_query_pairs(
        focus=focus,
        domains=domains,
        world_or_frame=world_or_frame,
        config=config,
        char_domain=char_domain,
    )
