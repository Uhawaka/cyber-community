"""Observation Pipeline: characters observe the human / academic world.

Queries are built from living domains + current focus (English literature nouns),
not hardcoded primes/turbulence heuristics.
"""

from __future__ import annotations

from engine.language import format_domains_for_query


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
) -> list:
    """Generate (query_type, query) pairs — English academic queries preferred."""
    research = char_research or {}
    project = (research.get("project") or research.get("stuck_point") or "").strip()
    focus = (focus or project or "").strip()

    doms = list(domains or [])
    if not doms and char_domain:
        if isinstance(char_domain, list):
            doms = list(char_domain)
        else:
            doms = [char_domain]

    base = format_domains_for_query(doms, focus=focus, fallback=char_domain or "mathematics")

    queries: list[tuple[str, str]] = []
    for q in base:
        # arXiv prefers English technical phrases
        queries.append(("arxiv", q))
    # One broader web query still in English for journals / surveys / blogs
    if base:
        queries.append(("web", base[0] + " survey OR journal recent"))

    # Deduplicate while preserving order
    out, seen = [], set()
    for kind, q in queries:
        key = (kind, q.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, q))
    return out[:6]
