"""Deterministic reservations for finite locations and resources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from engine.runtime.kernel.events import EventType, WorldEvent
from engine.runtime.kernel.state import WorldState
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.space import ActionAttempt, ActionKind
from engine.world.package_spec import AutonomousWorldSpec


@dataclass(frozen=True)
class ReservationRejection:
    actor_id: str
    reason: str
    contested_key: str
    attempt: ActionAttempt


class ReservationBook:
    """Allocates a complete tick batch independently of Python iteration order."""

    def __init__(
        self,
        world: AutonomousWorldSpec,
        snapshot: WorldState,
        *,
        action_budget: int | None = None,
    ) -> None:
        self.world = world
        self.snapshot_hash = snapshot.state_hash()
        self.tick = snapshot.tick
        self._snapshot = snapshot
        self._granted: dict[str, ActionAttempt] = {}
        self._consumed: set[str] = set()
        self._action_budget = action_budget

    def allocate(
        self, attempts: tuple[ActionAttempt, ...]
    ) -> tuple[tuple[ActionAttempt, ...], tuple[ReservationRejection, ...]]:
        available_resources = dict(self._snapshot.resources)
        occupancy = {
            location.id: sum(
                character.active and character.location_id == location.id
                for character in self._snapshot.characters.values()
            )
            for location in self.world.locations
        }
        capacities = {item.id: item.capacity for item in self.world.locations}
        accepted: list[ActionAttempt] = []
        rejected: list[ReservationRejection] = []
        remaining_budget = self._action_budget
        moving_actors = {
            attempt.actor_id
            for attempt in attempts
            if attempt.kind is ActionKind.MOVE
        }
        movement_passages = {
            attempt.actor_id: next(
                item
                for item in self.world.passages
                if item.id == attempt.target_id
            )
            for attempt in attempts
            if attempt.kind is ActionKind.MOVE
        }
        # Capacity is a batch property: everyone leaving vacates first, then
        # deterministic priority allocates all destinations. This permits swaps.
        for actor_id, passage in movement_passages.items():
            character = self._snapshot.characters.get(actor_id)
            if (
                character is not None
                and character.active
                and character.location_id == passage.origin_id
            ):
                occupancy[passage.origin_id] -= 1
        for attempt in sorted(attempts, key=self._priority):
            contested = ""
            reason = ""
            if remaining_budget is not None and attempt.cost > remaining_budget:
                contested = "tick:action_budget"
                reason = "action_budget_exhausted"
            elif (
                attempt.kind is ActionKind.TALK
                and (
                    attempt.actor_id in moving_actors
                    or attempt.target_id in moving_actors
                )
            ):
                contested = f"character:{attempt.target_id}"
                reason = "participant_moving"
            elif attempt.kind is ActionKind.GATHER:
                contested = f"resource:{attempt.target_id}"
                if available_resources.get(attempt.target_id, 0) <= 0:
                    reason = "resource_capacity_exhausted"
                else:
                    available_resources[attempt.target_id] -= 1
            elif attempt.kind is ActionKind.MOVE:
                passage = movement_passages[attempt.actor_id]
                contested = f"location:{passage.destination_id}"
                if occupancy[passage.destination_id] >= capacities[passage.destination_id]:
                    reason = "location_capacity_exhausted"
                else:
                    occupancy[passage.destination_id] += 1
            if reason:
                if attempt.kind is ActionKind.MOVE:
                    occupancy[movement_passages[attempt.actor_id].origin_id] += 1
                rejected.append(
                    ReservationRejection(
                        attempt.actor_id, reason, contested, attempt
                    )
                )
                continue
            reservation_id = self._reservation_id(attempt)
            reserved = replace(
                attempt,
                pre_state_hash=self.snapshot_hash,
                reservation_id=reservation_id,
            )
            self._granted[reservation_id] = reserved
            accepted.append(reserved)
            if remaining_budget is not None:
                remaining_budget -= attempt.cost
        return (
            tuple(sorted(accepted, key=lambda item: item.actor_id)),
            tuple(sorted(rejected, key=lambda item: item.actor_id)),
        )

    def consume(self, attempt: ActionAttempt) -> None:
        expected = self._granted.get(attempt.reservation_id)
        if (
            expected != attempt
            or attempt.pre_state_hash != self.snapshot_hash
            or attempt.reservation_id in self._consumed
        ):
            raise ValueError("missing, stale, or already consumed reservation")
        self._consumed.add(attempt.reservation_id)

    def _priority(self, attempt: ActionAttempt) -> tuple[int, str]:
        identity = (
            f"{self._snapshot.seed}:{self.tick}:{attempt.actor_id}:"
            f"{attempt.opportunity_id}:{attempt.kind.value}:{attempt.target_id}"
        )
        score = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
        return score, attempt.actor_id

    def _reservation_id(self, attempt: ActionAttempt) -> str:
        value = (
            f"{self.snapshot_hash}:{attempt.actor_id}:{attempt.kind.value}:"
            f"{attempt.target_id}:{attempt.opportunity_id}"
        )
        return hashlib.sha256(value.encode()).hexdigest()[:24]


def append_scheduling_event(
    run: AutonomousRun,
    event_type: EventType,
    actor_id: str,
    data: dict[str, object],
) -> WorldEvent:
    state = run.state
    pre_state_hash = state.state_hash()
    cursor = len(run.events)
    return run.log.append(
        WorldEvent(
            sequence=cursor,
            tick=state.tick,
            event_type=event_type,
            actor_id=actor_id,
            observers=(actor_id,),
            data={
                **data,
                "pre_state_hash": pre_state_hash,
                "world_hash": state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": actor_id,
                "rule_basis": ("deterministic reservation allocation",),
            },
            pre_state_hash=pre_state_hash,
            world_hash=state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=actor_id,
            rule_basis=("deterministic reservation allocation",),
        )
    )
