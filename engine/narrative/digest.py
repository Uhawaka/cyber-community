"""Immutable narrative digest built only from committed facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from engine.narrative.source import NarrativeChange, adapt_source_events

@dataclass(frozen=True)
class NarrativeDigestEntry:
    source_event_id: str
    world_time: float
    actor_id: str
    kind: str
    summary: str
    dialogue: str | None
    actor_ids: tuple[str, ...] = ()
    observer_ids: tuple[str, ...] = ()
    location_id: str | None = None
    target_id: str | None = None
    goal: str | None = None
    causal_source_ids: tuple[str, ...] = ()
    changes: tuple[NarrativeChange, ...] = ()
    unresolved_points: tuple[str, ...] = ()
    facts: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "facts", MappingProxyType(dict(self.facts))
        )

    @property
    def utterance(self) -> str | None:
        return self.dialogue


@dataclass(frozen=True)
class NarrativeDigest:
    source_event_ids: tuple[str, ...]
    world_time_start: float
    world_time_end: float
    entries: tuple[NarrativeDigestEntry, ...]
    causal_event_ids: tuple[str, ...] = ()
    character_ids: tuple[str, ...] = ()
    location_ids: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()
    utterances: tuple[str, ...] = ()
    changes: tuple[NarrativeChange, ...] = ()
    unresolved_points: tuple[str, ...] = ()

    @property
    def actual_utterances(self) -> tuple[str, ...]:
        return self.utterances

    @property
    def structured_change_summary(self) -> tuple[NarrativeChange, ...]:
        return self.changes


def build_narrative_digest(events: Sequence[object]) -> NarrativeDigest:
    """Build a presentation input exclusively from committed event fields."""

    snapshot = adapt_source_events(events)
    if not snapshot:
        raise ValueError("a narrative digest requires at least one event")
    event_ids = tuple(event.source_event_id for event in snapshot)
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("a narrative digest cannot contain duplicate events")

    entries = tuple(
        NarrativeDigestEntry(
            source_event_id=event.source_event_id,
            world_time=event.world_time,
            actor_id=event.actor_ids[0] if event.actor_ids else "system",
            kind=event.kind,
            summary=event.summary,
            dialogue=event.utterance,
            actor_ids=event.actor_ids,
            observer_ids=event.observer_ids,
            location_id=event.location_id,
            target_id=event.target_id,
            goal=event.goal,
            causal_source_ids=event.causal_source_ids,
            changes=event.changes,
            unresolved_points=event.unresolved_points,
            facts=event.facts,
        )
        for event in snapshot
    )
    times = tuple(entry.world_time for entry in entries)
    return NarrativeDigest(
        source_event_ids=event_ids,
        world_time_start=min(times),
        world_time_end=max(times),
        entries=entries,
        causal_event_ids=_unique(
            item for entry in entries for item in entry.causal_source_ids
        ),
        character_ids=_unique(
            item
            for entry in entries
            for item in (*entry.actor_ids, *entry.observer_ids)
        ),
        location_ids=_unique(
            entry.location_id for entry in entries if entry.location_id
        ),
        target_ids=_unique(entry.target_id for entry in entries if entry.target_id),
        utterances=tuple(
            entry.dialogue for entry in entries if entry.dialogue is not None
        ),
        changes=tuple(change for entry in entries for change in entry.changes),
        unresolved_points=_unique(
            item for entry in entries for item in entry.unresolved_points
        ),
    )


def _unique(values: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values))

