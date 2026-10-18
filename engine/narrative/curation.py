"""Reader-facing event filtering and bounded Episode window curation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from engine.narrative.source import SourceEventView, adapt_source_event


INTERNAL_EVENT_KINDS = frozenset(
    {
        "action_rejected",
        "action_replanned",
        "environment_decayed",
        "gate_waited",
        "incident_rested",
        "memory_consolidated",
        "phase_snapshot",
        "run_created",
        "scheme_advanced",
        "scheme_completed",
        "scheme_created",
        "scheme_invalidated",
        "soul_evolution_proposed",
    }
)


@dataclass(frozen=True)
class CurationPolicy:
    max_events: int = 12
    max_world_time_span: int = 8
    min_narrative_events: int = 1
    max_repeated_action: int = 2
    min_arc_events: int = 1

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object] | None
    ) -> "CurationPolicy":
        selected = dict(value or {})
        return cls(
            max_events=int(selected.get("max_events", 12)),
            max_world_time_span=int(
                selected.get("max_world_time_span", 8)
            ),
            min_narrative_events=int(
                selected.get("min_narrative_events", 1)
            ),
            max_repeated_action=int(
                selected.get("max_repeated_action", 2)
            ),
            min_arc_events=int(selected.get("min_arc_events", 1)),
        )


@dataclass(frozen=True)
class CuratedEpisodeWindow:
    sources: tuple[SourceEventView, ...]
    cursor_after: int


def is_reader_visible_source(source: SourceEventView) -> bool:
    if source.kind in INTERNAL_EVENT_KINDS or source.kind == "scene_instantiated":
        return False
    if (
        source.kind == "turn_resolved"
        and source.facts.get("status") == "rejected"
    ):
        return False
    if (
        source.kind == "turn_resolved"
        and source.actor_ids
        and source.actor_ids[0].startswith("scene:")
        and source.facts.get("dramatic_progress") in {None, "none"}
    ):
        return False
    if str(source.facts.get("restated") or "") == "True":
        return False
    if (
        source.kind == "turn_resolved"
        and source.facts.get("dispatch") == "think"
        and not _committed_decision(source)
    ):
        return False
    return True


def _committed_decision(source: SourceEventView) -> bool:
    value = str(source.facts.get("decision") or "").strip()
    return value not in {"", "None", "null"}


def curate_episode_windows(
    events: Sequence[object],
    *,
    cursor: int,
    audience_id: str,
    omniscient: bool,
    policy: CurationPolicy,
    release_tail: bool = True,
) -> tuple[CuratedEpisodeWindow, ...]:
    """Split unseen history into bounded, source-preserving reader windows."""

    snapshot = tuple(events)
    windows: list[CuratedEpisodeWindow] = []
    current: list[SourceEventView] = []
    repeated: dict[tuple[str, str, str | None], int] = {}
    first_time: float | None = None

    for absolute_index in range(cursor, len(snapshot)):
        source = adapt_source_event(snapshot[absolute_index])
        if not omniscient and audience_id not in source.observer_ids:
            continue
        if not is_reader_visible_source(source):
            continue
        key = (
            source.kind,
            source.actor_ids[0] if source.actor_ids else "system",
            source.target_id or source.location_id,
        )
        if (
            source.kind in {"moved", "observed", "waited", "rested"}
            and repeated.get(key, 0) >= policy.max_repeated_action
        ):
            continue
        span_exceeded = (
            current
            and first_time is not None
            and source.world_time - first_time > policy.max_world_time_span
        )
        chain_open = _continues_chain(current, source)
        over_cap = len(current) >= policy.max_events + _CHAIN_SLACK
        if current and (
            over_cap
            or (
                (len(current) >= policy.max_events or span_exceeded)
                and not chain_open
            )
        ):
            windows.append(
                CuratedEpisodeWindow(tuple(current), absolute_index)
            )
            current = []
            repeated = {}
            first_time = None
        if first_time is None:
            first_time = source.world_time
        current.append(source)
        repeated[key] = repeated.get(key, 0) + 1

    arc_ready = len(current) >= max(
        policy.min_narrative_events, policy.min_arc_events
    )
    if release_tail and current and arc_ready:
        windows.append(CuratedEpisodeWindow(tuple(current), len(snapshot)))
    return tuple(windows)


_CHAIN_SLACK = 6


def _continues_chain(
    current: Sequence[SourceEventView], source: SourceEventView
) -> bool:
    if not current:
        return False
    previous = str(current[-1].facts.get("chain_id") or "")
    incoming = str(source.facts.get("chain_id") or "")
    return bool(previous) and previous == incoming
