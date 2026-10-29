"""Immutable evidence views shared with read-only community observers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommunityFact:
    sequence: int
    tick: int
    kind: str
    actor_id: str | None
    participants: tuple[str, ...]
    source_sequences: tuple[int, ...]
    target_id: str
    summary: str
    object_id: str = ""
    status: str = ""
    goal_id: str = ""
    changed_world: bool = False
    utterance: str = ""
    action_verb: str = ""
    speech_act: str = ""
    topic_ref: str = ""


@dataclass(frozen=True)
class StoryThread:
    thread_id: str
    participants: tuple[str, ...]
    target_id: str
    source_sequences: tuple[int, ...]
    from_tick: int
    to_tick: int
    unresolved_ids: tuple[str, ...]
    significance: int
    evidence: tuple[CommunityFact, ...]
