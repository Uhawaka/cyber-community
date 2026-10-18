"""Minimal aggregate for one autonomous simulation run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from engine.contracts import IntentPolicy, SceneGenerator, WorldAdjudicator
from engine.runtime.character import MemoryProjection
from engine.runtime.character.policy import ActorPolicy, DeterministicActorPolicy
from engine.runtime.kernel.events import EventLog, WorldEvent
from engine.runtime.kernel.state import WorldState
from engine.world.package_spec import CompiledWorld

@dataclass
class AutonomousRun:
    compiled: CompiledWorld
    initial_state: WorldState
    log: EventLog
    memory: MemoryProjection
    parent_history_hash: str | None = None
    fork_sequence: int | None = None
    actor_policy: ActorPolicy = field(default_factory=DeterministicActorPolicy)
    scene_generator: SceneGenerator | None = None
    intent_policy: IntentPolicy | None = None
    world_adjudicator: WorldAdjudicator | None = None

    @property
    def state(self) -> WorldState:
        return self.log.state

    @property
    def events(self) -> tuple[WorldEvent, ...]:
        return self.log.events

    def replay(self) -> WorldState:
        return EventLog.replay(self.initial_state, self.events).state

    def history_hash(self) -> str:
        return event_history_hash(self.events)


def event_history_hash(events: tuple[WorldEvent, ...]) -> str:
    values = [
        {
            "sequence": event.sequence,
            "tick": event.tick,
            "type": event.event_type.value,
            "actor": event.actor_id,
            "observers": event.observers,
            "data": dict(event.data),
            "delta": repr(event.delta),
        }
        for event in events
    ]
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

