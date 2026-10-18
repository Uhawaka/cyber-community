"""Typed append-only facts and atomic state deltas for autonomous runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, TYPE_CHECKING
from contextvars import ContextVar, Token

from engine.contracts import ComponentPatch
from engine.contracts import EntityKind
from engine.runtime.kernel.event_persistence import (
    EventPersistenceIOError,
    append_record,
    recover_tail,
)

if TYPE_CHECKING:
    from engine.runtime.kernel.state import WorldState

_WORKFLOW_PROVENANCE: ContextVar[tuple[str, str] | None] = ContextVar(
    "workflow_provenance", default=None
)


def set_workflow_provenance(kind: str, step: str) -> Token:
    return _WORKFLOW_PROVENANCE.set((kind, step))


def reset_workflow_provenance(token: Token) -> None:
    _WORKFLOW_PROVENANCE.reset(token)
class EventType(str, Enum):
    RUN_CREATED = "run_created"
    RUN_FORKED = "run_forked"
    AVATAR_JOINED = "avatar_joined"
    AVATAR_LEFT = "avatar_left"
    AVATAR_REJOINED = "avatar_rejoined"
    MOVED = "moved"
    GATHERED = "gathered"
    INSPECTED = "inspected"
    OBSERVED = "observed"
    DIALOGUE = "dialogue"
    RESTED = "rested"
    WAITED = "waited"
    ENVIRONMENT_DECAYED = "environment_decayed"
    INCIDENT_OCCURRED = "incident_occurred"
    INCIDENT_RESTED = "incident_rested"
    GATE_OPENED = "gate_opened"
    GATE_WAITED = "gate_waited"
    USER_INTERVENTION = "user_intervention"
    FATE_INTERVENTION = "fate_intervention"
    COARSE_TICK_SUMMARY = "coarse_tick_summary"
    SCHEME_CREATED = "scheme_created"
    SCHEME_ADVANCED = "scheme_advanced"
    SCHEME_COMPLETED = "scheme_completed"
    SCHEME_INVALIDATED = "scheme_invalidated"
    MEMORY_CONSOLIDATED = "memory_consolidated"
    SOUL_EVOLUTION_PROPOSED = "soul_evolution_proposed"
    SOUL_EVOLUTION_APPROVED = "soul_evolution_approved"
    SOUL_EVOLUTION_REJECTED = "soul_evolution_rejected"
    ACTION_REJECTED = "action_rejected"
    ACTION_REPLANNED = "action_replanned"
    PHASE_SNAPSHOT = "phase_snapshot"
    SCENE_INSTANTIATED = "scene_instantiated"
    SCENE_ENTERED = "scene_entered"
    SCENE_EVOLVED = "scene_evolved"
    TURN_RESOLVED = "turn_resolved"

@dataclass(frozen=True)
class MoveDelta:
    character_id: str
    origin_id: str
    destination_id: str
@dataclass(frozen=True)
class QuantityDelta:
    owner_id: str
    item_id: str
    amount: int

@dataclass(frozen=True)
class NeedDelta:
    character_id: str
    need: str
    amount: int

@dataclass(frozen=True)
class RelationshipDelta:
    source_id: str
    target_id: str
    amount: int

@dataclass(frozen=True)
class KnowledgeDelta:
    character_id: str
    fact_id: str
    source_id: str

@dataclass(frozen=True)
class DisclosureDelta:
    speaker_id: str
    listener_id: str
    fact_id: str

@dataclass(frozen=True)
class PlanDelta:
    character_id: str
    plan: tuple[str, ...]

@dataclass(frozen=True)
class ActionRecord:
    character_id: str
    kind: str
    target_id: str
    tick: int
@dataclass(frozen=True)
class CharacterDelta:
    character_id: str
    display_name: str
    location_id: str
    needs: Mapping[str, int]
    goals: tuple[str, ...] = ()
    participant_kind: str = "avatar"

    def __post_init__(self) -> None:
        object.__setattr__(self, "needs", MappingProxyType(dict(self.needs)))
@dataclass(frozen=True)
class AvatarPresenceDelta:
    character_id: str
    active: bool
@dataclass(frozen=True)
class SchemeDelta:
    scheme_id: str
    character_id: str
    target_state: tuple[str, ...]
    progress: float
    status: str
@dataclass(frozen=True)
class SoulDelta:
    character_id: str
    trait: str
    value: Any
    expected_version: int
    evidence_sequences: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.character_id.strip() or not self.trait.strip():
            raise ValueError("soul delta requires character and trait")
        if self.expected_version < 0:
            raise ValueError("soul delta version must be non-negative")
        if len(self.evidence_sequences) < 3 or any(
            sequence < 0 for sequence in self.evidence_sequences
        ):
            raise ValueError("soul delta requires at least three source events")
        if len(set(self.evidence_sequences)) != len(self.evidence_sequences):
            raise ValueError("soul delta evidence must be unique")

@dataclass(frozen=True)
class Delta:
    """A complete transaction. Validation happens before any field is changed."""

    characters: tuple[CharacterDelta, ...] = ()
    avatar_presence: tuple[AvatarPresenceDelta, ...] = ()
    moves: tuple[MoveDelta, ...] = ()
    resources: tuple[QuantityDelta, ...] = ()
    inventories: tuple[QuantityDelta, ...] = ()
    needs: tuple[NeedDelta, ...] = ()
    relationships: tuple[RelationshipDelta, ...] = ()
    knowledge: tuple[KnowledgeDelta, ...] = ()
    disclosures: tuple[DisclosureDelta, ...] = ()
    plans: tuple[PlanDelta, ...] = ()
    actions: tuple[ActionRecord, ...] = ()
    schemes: tuple[SchemeDelta, ...] = ()
    souls: tuple[SoulDelta, ...] = ()
    entity_patches: tuple[ComponentPatch, ...] = ()
    advance_time: int = 0
    advance_tick: int = 0
@dataclass(frozen=True)
class WorldEvent:
    sequence: int
    tick: int
    event_type: EventType
    actor_id: str | None
    observers: tuple[str, ...]
    delta: Delta = field(default_factory=Delta)
    data: Mapping[str, Any] = field(default_factory=dict)
    opportunity_id: str | None = None
    pre_state_hash: str | None = None
    world_hash: str | None = None
    deterministic_cursor: int | None = None
    target_entity_id: str | None = None
    rule_basis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "observers", tuple(sorted(set(self.observers))))
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "rule_basis", tuple(self.rule_basis))
class EventValidationError(ValueError):
    pass
class EventPersistenceError(EventValidationError):
    pass
EVENT_LOG_SCHEMA_VERSION = "autonomous-event-log.v1"
class EventLog:
    """The only mutation gateway for objective world state."""

    def __init__(self, state: "WorldState", path: str | Path | None = None) -> None:
        self._state = state
        self._events: list[WorldEvent] = []
        self._path = Path(path) if path is not None else None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def state(self) -> "WorldState":
        return self._state

    @property
    def events(self) -> tuple[WorldEvent, ...]:
        return tuple(self._events)

    def append(self, event: WorldEvent) -> WorldEvent:
        provenance = _WORKFLOW_PROVENANCE.get()
        has_provenance = (
            "workflow_kind" in event.data and "workflow_step" in event.data
        )
        if provenance is None and not has_provenance:
            provenance = {
                EventType.ENVIRONMENT_DECAYED: ("evolution", "environment_update"),
                EventType.COARSE_TICK_SUMMARY: ("evolution", "environment_update"),
                EventType.MOVED: ("evolution", "actor_windows"),
                EventType.GATHERED: ("evolution", "actor_windows"),
                EventType.INSPECTED: ("evolution", "actor_windows"),
                EventType.OBSERVED: ("evolution", "actor_windows"),
                EventType.DIALOGUE: ("evolution", "actor_windows"),
                EventType.RESTED: ("evolution", "actor_windows"),
                EventType.WAITED: ("evolution", "actor_windows"),
                EventType.ACTION_REJECTED: ("evolution", "actor_windows"),
                EventType.ACTION_REPLANNED: ("evolution", "actor_windows"),
                EventType.SCHEME_CREATED: ("evolution", "scheme_progress"),
                EventType.SCHEME_ADVANCED: ("evolution", "scheme_progress"),
                EventType.SCHEME_COMPLETED: ("evolution", "scheme_progress"),
                EventType.SCHEME_INVALIDATED: ("evolution", "scheme_progress"),
                EventType.MEMORY_CONSOLIDATED: ("evolution", "memory_consolidation"),
                EventType.SOUL_EVOLUTION_PROPOSED: ("evolution", "memory_consolidation"),
                EventType.SOUL_EVOLUTION_APPROVED: ("evolution", "memory_consolidation"),
                EventType.SOUL_EVOLUTION_REJECTED: ("evolution", "memory_consolidation"),
                EventType.PHASE_SNAPSHOT: ("evolution", "phase_check"),
                EventType.SCENE_INSTANTIATED: ("evolution", "scene_turns"),
                EventType.SCENE_ENTERED: ("evolution", "scene_turns"),
                EventType.SCENE_EVOLVED: ("evolution", "scene_turns"),
                EventType.TURN_RESOLVED: ("evolution", "scene_turns"),
                EventType.GATE_OPENED: ("intervention", "user_gate"),
                EventType.GATE_WAITED: ("intervention", "user_gate"),
                EventType.USER_INTERVENTION: ("intervention", "user_gate"),
                EventType.FATE_INTERVENTION: ("intervention", "fate"),
                EventType.INCIDENT_OCCURRED: ("intervention", "incident"),
                EventType.INCIDENT_RESTED: ("intervention", "incident"),
                EventType.AVATAR_JOINED: ("intervention", "user_gate"),
                EventType.AVATAR_LEFT: ("intervention", "user_gate"),
                EventType.AVATAR_REJOINED: ("intervention", "user_gate"),
            }.get(event.event_type)
        if provenance is not None and not has_provenance:
            event = WorldEvent(
                **{
                    **vars(event),
                    "data": {
                        "workflow_kind": provenance[0],
                        "workflow_step": provenance[1],
                        **dict(event.data),
                    },
                }
            )
        if event.sequence != len(self._events):
            raise EventValidationError("event sequence must be contiguous")
        if event.tick != self._state.tick:
            raise EventValidationError("event tick must match current state")
        known = set(self._state.characters) | {
            entity_id
            for entity_id, entity in self._state.entities.items()
            if entity.kind in {EntityKind.CHARACTER, EntityKind.NPC}
        }
        additions = {item.character_id for item in event.delta.characters}
        if len(additions) != len(event.delta.characters):
            raise EventValidationError("duplicate character addition")
        allowed = known | additions
        if event.actor_id is not None and event.actor_id not in allowed:
            raise EventValidationError("unknown event actor")
        if not set(event.observers).issubset(allowed):
            raise EventValidationError("unknown event observer")
        if additions and event.event_type is not EventType.AVATAR_JOINED:
            raise EventValidationError("characters may only join through avatar_joined")
        if event.event_type is EventType.AVATAR_JOINED and not additions:
            raise EventValidationError("avatar_joined requires a character delta")
        if event.delta.avatar_presence and event.event_type not in {
            EventType.AVATAR_LEFT,
            EventType.AVATAR_REJOINED,
        }:
            raise EventValidationError("avatar presence requires a lifecycle event")
        presence = event.delta.avatar_presence
        if event.event_type is EventType.AVATAR_LEFT and (
            len(presence) != 1
            or presence[0].character_id != event.actor_id
            or presence[0].active
        ):
            raise EventValidationError(
                "avatar_left requires the actor's active=False presence delta"
            )
        if event.event_type is EventType.AVATAR_REJOINED and (
            len(presence) != 1
            or presence[0].character_id != event.actor_id
            or not presence[0].active
        ):
            raise EventValidationError(
                "avatar_rejoined requires the actor's active=True presence delta"
            )
        if event.event_type in {
            EventType.AVATAR_LEFT,
            EventType.AVATAR_REJOINED,
        }:
            lifecycle_character = self._state.characters.get(event.actor_id)
            if (
                lifecycle_character is None
                or lifecycle_character.participant_kind != "avatar"
            ):
                raise EventValidationError(
                    "avatar lifecycle actor must be a known avatar"
                )
            if (
                event.event_type is EventType.AVATAR_LEFT
                and not lifecycle_character.active
            ) or (
                event.event_type is EventType.AVATAR_REJOINED
                and lifecycle_character.active
            ):
                raise EventValidationError(
                    "avatar lifecycle delta must change active state"
                )
        if any(item.participant_kind != "avatar" for item in event.delta.characters):
            raise EventValidationError("joined characters must be avatars")
        if event.pre_state_hash is not None and event.pre_state_hash != self._state.state_hash():
            raise EventValidationError("event pre-state hash does not match current state")
        if event.world_hash is not None and event.world_hash != self._state.world_hash:
            raise EventValidationError("event world hash does not match current world")
        if event.event_type is EventType.DIALOGUE and not event.data.get("utterance"):
            raise EventValidationError("dialogue must preserve the actual utterance")
        if event.delta.souls and event.event_type is not EventType.SOUL_EVOLUTION_APPROVED:
            raise EventValidationError("soul deltas require an approved evolution event")
        if event.event_type is EventType.SOUL_EVOLUTION_APPROVED:
            if len(event.delta.souls) != 1:
                raise EventValidationError("approved soul evolution requires one soul delta")
            soul = event.delta.souls[0]
            if soul.character_id != event.actor_id:
                raise EventValidationError("soul delta must update the event actor")
            if tuple(event.data.get("evidence_sequences", ())) != soul.evidence_sequences:
                raise EventValidationError("soul evidence data must match the typed delta")
            if event.data.get("trait") != soul.trait:
                raise EventValidationError("soul trait data must match the typed delta")
            for sequence in soul.evidence_sequences:
                if sequence >= len(self._events):
                    raise EventValidationError("soul evidence must reference prior events")
                source = self._events[sequence]
                if event.actor_id not in source.observers and source.actor_id != event.actor_id:
                    raise EventValidationError("soul evidence must be visible to the actor")
        if event.event_type is EventType.SOUL_EVOLUTION_REJECTED and event.delta.souls:
            raise EventValidationError("rejected soul evolution cannot change soul state")
        if event.event_type is EventType.MEMORY_CONSOLIDATED:
            self._validate_memory_consolidation(event)
        candidate = self._state.apply(event.delta)
        if self._path is not None:
            self._append_record(self._path, event)
        self._state = candidate
        self._events.append(event)
        return event

    def _validate_memory_consolidation(self, event: WorldEvent) -> None:
        required = {"source_sequences", "target_tier", "belief_type", "confidence", "summary"}
        if not required.issubset(event.data):
            raise EventValidationError("memory consolidation is missing typed fields")
        sources = tuple(event.data["source_sequences"])
        if not sources or any(
            isinstance(sequence, bool) or not isinstance(sequence, int)
            for sequence in sources
        ):
            raise EventValidationError("memory consolidation requires source sequences")
        if event.data["target_tier"] not in {"semantic", "core"}:
            raise EventValidationError("memory target tier must be semantic or core")
        if event.data["belief_type"] not in {"fact", "inference", "misbelief"}:
            raise EventValidationError("memory belief type is invalid")
        confidence = event.data["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise EventValidationError("memory confidence must be between zero and one")
        if not isinstance(event.data["summary"], str) or not event.data["summary"].strip():
            raise EventValidationError("memory consolidation requires a summary")
        for sequence in sources:
            if sequence < 0 or sequence >= len(self._events):
                raise EventValidationError("memory source must reference a prior event")
            source = self._events[sequence]
            if not set(event.observers).issubset(set(source.observers)):
                raise EventValidationError("memory source must be visible to every observer")

    def _append_record(self, path: Path, event: WorldEvent) -> None:
        try:
            append_record(
                path,
                event_record(event),
                expected_sequence=event.sequence,
                world_hash=self._state.world_hash,
                pre_state_hash=event.pre_state_hash,
                current_state_hash=self._state.state_hash(),
                expected_tail_pre_state_hash=self._events[-1].pre_state_hash if self._events else None,
            )
        except EventPersistenceIOError as exc:
            raise EventPersistenceError(str(exc)) from exc

    @classmethod
    def replay(
        cls,
        initial_state: "WorldState",
        events: Iterable[WorldEvent],
        *,
        path: str | Path | None = None,
    ) -> "EventLog":
        log = cls(initial_state)
        for event in events:
            log.append(event)
        log._path = Path(path) if path is not None else None
        return log

    @classmethod
    def read_events(
        cls,
        path: str | Path,
        *,
        world_hash: str,
        recover_tail: bool = False,
    ) -> tuple[WorldEvent, ...]:
        source = Path(path)
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise EventPersistenceError(f"cannot read event log: {exc}") from exc
        lines = payload.splitlines(keepends=True)
        events: list[WorldEvent] = []
        for index, raw in enumerate(lines):
            is_unterminated_tail = index == len(lines) - 1 and not raw.endswith(b"\n")
            if is_unterminated_tail:
                if recover_tail:
                    cls._recover_tail(
                        source, payload, sum(len(line) for line in lines[:index])
                    )
                    break
                raise EventPersistenceError(
                    f"unterminated event log record at line {index + 1}"
                )
            try:
                record = json.loads(raw.decode("utf-8"))
                event = event_from_record(record, world_hash=world_hash)
            except (UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                raise EventPersistenceError(
                    f"invalid event log record at line {index + 1}: {exc}"
                ) from exc
            if event.sequence != len(events):
                raise EventPersistenceError("event sequence must be contiguous")
            events.append(event)
        return tuple(events)

    @staticmethod
    def _recover_tail(path: Path, payload: bytes, valid_length: int) -> None:
        recover_tail(path, payload, valid_length)


def event_record(event: WorldEvent) -> dict[str, Any]:
    """Lossless JSON representation; every line is independently gateable."""
    from engine.runtime.kernel.event_codec import event_record as encode

    return encode(event)


def event_from_record(record: Mapping[str, Any], *, world_hash: str) -> WorldEvent:
    from engine.runtime.kernel.event_codec import event_from_record as decode

    return decode(record, world_hash=world_hash)


