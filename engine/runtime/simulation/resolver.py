"""The sole writer of outcomes produced by character action attempts."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from engine.runtime.kernel.events import (
    ActionRecord,
    Delta,
    DisclosureDelta,
    EventLog,
    EventType,
    MoveDelta,
    NeedDelta,
    KnowledgeDelta,
    PlanDelta,
    QuantityDelta,
    RelationshipDelta,
    WorldEvent,
)
from engine.runtime.space import (
    ActionAttempt,
    ActionKind,
    DialogueAct,
    project_location_history,
)
from engine.world.package_spec import AutonomousWorldSpec
from engine.runtime.simulation.reservations import ReservationBook


class Resolver:
    def __init__(
        self,
        world: AutonomousWorldSpec,
        log: EventLog,
        *,
        observer_scope: frozenset[str] | None = None,
        reservation_book: ReservationBook | None = None,
    ) -> None:
        self.world = world
        self.log = log
        self.observer_scope = observer_scope
        self.reservation_book = reservation_book

    def resolve(self, attempt: ActionAttempt) -> WorldEvent:
        state = self.log.state
        actor = state.characters.get(attempt.actor_id)
        if actor is None:
            raise ValueError("unknown action actor")
        if actor.location_id != attempt.expected_location_id:
            raise ValueError("stale action attempt")
        if self.reservation_book is not None:
            if attempt.pre_state_hash != self.reservation_book.snapshot_hash:
                raise ValueError("action attempt precondition hash is stale")
        method = getattr(self, f"_resolve_{attempt.kind.value}")
        event_type, observers, delta, data = method(attempt)
        plan_changes = delta.plans
        if attempt.replacement_plan is not None:
            plan_changes += (
                PlanDelta(attempt.actor_id, attempt.replacement_plan),
            )
        delta = replace(
            delta,
            plans=plan_changes,
            actions=delta.actions
            + (
                ActionRecord(
                    attempt.actor_id,
                    attempt.kind.value,
                    attempt.target_id,
                    state.tick,
                ),
            ),
        )
        pre_state_hash = state.state_hash()
        opportunity_id = attempt.opportunity_id or hashlib.sha256(
            (
                f"{pre_state_hash}:{attempt.actor_id}:{attempt.kind.value}:"
                f"{attempt.target_id}:{attempt.expected_location_id}"
            ).encode()
        ).hexdigest()[:24]
        rule_basis = (
            f"actor is at {attempt.expected_location_id}",
            f"{attempt.kind.value} affordance targets {attempt.target_id}",
            attempt.reason,
        )
        provenance = {
            "opportunity_id": opportunity_id,
            "pre_state_hash": pre_state_hash,
            "world_hash": state.world_hash,
            "deterministic_cursor": len(self.log.events),
            "target_entity_id": attempt.target_id,
            "goal": attempt.reason,
            "rule_basis": rule_basis,
            "actor_policy_diagnostics": attempt.diagnostics,
        }
        event = WorldEvent(
            sequence=len(self.log.events),
            tick=state.tick,
            event_type=event_type,
            actor_id=attempt.actor_id,
            observers=observers,
            delta=delta,
            data={**data, **provenance},
            opportunity_id=opportunity_id,
            pre_state_hash=pre_state_hash,
            world_hash=state.world_hash,
            deterministic_cursor=len(self.log.events),
            target_entity_id=attempt.target_id,
            rule_basis=rule_basis,
        )
        if self.reservation_book is not None:
            self.reservation_book.consume(attempt)
        return self.log.append(event)

    def _resolve_move(self, attempt: ActionAttempt):
        passage = next(
            (item for item in self.world.passages if item.id == attempt.target_id),
            None,
        )
        if passage is None or passage.origin_id != attempt.expected_location_id:
            raise ValueError("passage is not available")
        destination = next(
            item for item in self.world.locations
            if item.id == passage.destination_id
        )
        occupancy = sum(
            item.active and item.location_id == passage.destination_id
            for item in self.log.state.characters.values()
        )
        if self.reservation_book is None and occupancy >= destination.capacity:
            raise ValueError("destination capacity is no longer available")
        before = self._at(passage.origin_id)
        after = self._at(passage.destination_id)
        delta = Delta(
            moves=(
                MoveDelta(
                    attempt.actor_id, passage.origin_id, passage.destination_id
                ),
            ),
            needs=(NeedDelta(attempt.actor_id, "exploration", -12),),
            advance_time=passage.travel_time,
        )
        return (
            EventType.MOVED,
            tuple(set(before + after + (attempt.actor_id,))),
            delta,
            {
                "passage_id": passage.id,
                "origin_id": passage.origin_id,
                "destination_id": passage.destination_id,
                "destination_description": destination.description,
                "travel_time": passage.travel_time,
                "location_ids": (passage.origin_id, passage.destination_id),
                "public_trace": True,
            },
        )

    def _resolve_gather(self, attempt: ActionAttempt):
        resource = next(
            (item for item in self.world.resources if item.id == attempt.target_id),
            None,
        )
        state = self.log.state
        if (
            resource is None
            or resource.location_id != attempt.expected_location_id
            or state.resources.get(resource.id, 0) <= 0
        ):
            raise ValueError("resource is not available")
        delta = Delta(
            resources=(QuantityDelta(resource.location_id, resource.id, -1),),
            inventories=(QuantityDelta(attempt.actor_id, resource.id, 1),),
            needs=(NeedDelta(attempt.actor_id, "resources", -16),),
        )
        return (
            EventType.GATHERED,
            self._at(resource.location_id),
            delta,
            {
                "resource_id": resource.id,
                "resource_name": resource.name,
                "resource_properties": dict(resource.properties),
                "quantity": 1,
                "location_id": resource.location_id,
                "public_trace": True,
            },
        )

    def _resolve_observe(self, attempt: ActionAttempt):
        location = next(
            item
            for item in self.world.locations
            if item.id == attempt.expected_location_id
        )
        resources = tuple(
            item.id
            for item in self.world.resources
            if item.location_id == attempt.expected_location_id
            and self.log.state.resources.get(item.id, 0) > 0
        )
        return (
            EventType.OBSERVED,
            (attempt.actor_id,),
            Delta(
                needs=(NeedDelta(attempt.actor_id, "knowledge", -10),),
            ),
            {
                "location_id": attempt.expected_location_id,
                "location_description": location.description,
                "resources": resources,
                "summary": f"observed {attempt.expected_location_id}",
                "local_history": project_location_history(
                    self.log.events, attempt.expected_location_id
                ),
            },
        )

    def _resolve_inspect(self, attempt: ActionAttempt):
        resource = next(
            (
                item
                for item in self.world.resources
                if item.id == attempt.target_id
            ),
            None,
        )
        if (
            resource is None
            or self.log.state.inventories.get(
                attempt.actor_id, {}
            ).get(resource.id, 0)
            <= 0
        ):
            raise ValueError("inspect requires an inventoried resource")
        fact_id = f"resource:{resource.id}:inspection"
        finding = self.log.state.facts.get(fact_id)
        if not finding:
            raise ValueError("resource has no inspectable fact")
        if fact_id in self.log.state.knowledge.get(attempt.actor_id, ()):
            raise ValueError("resource inspection is already known")
        return (
            EventType.INSPECTED,
            self._at(attempt.expected_location_id),
            Delta(
                needs=(NeedDelta(attempt.actor_id, "knowledge", -14),),
                knowledge=(
                    KnowledgeDelta(
                        attempt.actor_id,
                        fact_id,
                        attempt.actor_id,
                    ),
                ),
            ),
            {
                "resource_id": resource.id,
                "resource_name": resource.name,
                "fact_id": fact_id,
                "finding": finding,
                "location_id": attempt.expected_location_id,
                "public_trace": True,
            },
        )

    def _resolve_talk(self, attempt: ActionAttempt):
        state = self.log.state
        target = state.characters.get(attempt.target_id)
        if target is None or target.location_id != attempt.expected_location_id:
            raise ValueError("talk requires co-location")
        utterance = (attempt.utterance or "").strip()
        if not utterance:
            raise ValueError("talk requires actor-provided utterance")
        if len(utterance) > 500 or any(character in utterance for character in "\r\n\0"):
            raise ValueError("utterance is not valid")
        act = attempt.dialogue_act or DialogueAct.INQUIRE
        topic = (attempt.dialogue_topic or "眼前的情况").strip()
        if not topic or len(topic) > 100:
            raise ValueError("dialogue topic is not valid")
        allowed_information_ids = set(
            state.knowledge.get(attempt.actor_id, ())
        )
        if not set(attempt.information_ids).issubset(
            allowed_information_ids
        ):
            raise ValueError("dialogue discloses unauthorized information")
        information_gain_ids = tuple(
            information_id
            for information_id in attempt.information_ids
            if information_id
            not in state.knowledge.get(attempt.target_id, ())
        )
        addressed_fact_ids = {
            fact_id
            for listeners in state.disclosures.values()
            for facts in listeners.values()
            for fact_id in facts
        }
        conversation_progress_ids = tuple(
            information_id
            for information_id in attempt.information_ids
            if information_id in information_gain_ids
            or (
                information_id.startswith("incident:")
                and information_id not in addressed_fact_ids
            )
        )
        relationship_effects = {
            DialogueAct.INQUIRE: (1, 1),
            DialogueAct.DISCLOSE: (3, 2),
            DialogueAct.PROPOSE: (2, 1),
            DialogueAct.CHALLENGE: (-1, -1),
            DialogueAct.REASSURE: (2, 3),
        }[act]
        witnesses = tuple(
            character_id
            for character_id in self._at(attempt.expected_location_id)
            if character_id != attempt.actor_id
        )
        delta = Delta(
            relationships=(
                RelationshipDelta(
                    attempt.actor_id,
                    attempt.target_id,
                    relationship_effects[0],
                ),
                RelationshipDelta(
                    attempt.target_id,
                    attempt.actor_id,
                    relationship_effects[1],
                ),
            ),
            needs=(
                NeedDelta(attempt.actor_id, "social", -18),
                NeedDelta(attempt.target_id, "social", -10),
            ),
            knowledge=tuple(
                KnowledgeDelta(
                    witness_id,
                    information_id,
                    attempt.actor_id,
                )
                for witness_id in witnesses
                for information_id in attempt.information_ids
                if information_id
                not in state.knowledge.get(witness_id, ())
            ),
            disclosures=tuple(
                DisclosureDelta(
                    attempt.actor_id,
                    witness_id,
                    information_id,
                )
                for witness_id in witnesses
                for information_id in attempt.information_ids
            ),
        )
        return (
            EventType.DIALOGUE,
            self._at(attempt.expected_location_id),
            delta,
            {
                "speaker_id": attempt.actor_id,
                "listener_id": attempt.target_id,
                "utterance": utterance,
                "dialogue_act": act.value,
                "dialogue_topic": topic,
                "information_ids": attempt.information_ids,
                "information_gain_ids": information_gain_ids,
                "conversation_progress_ids": conversation_progress_ids,
                "relationship_reason": f"dialogue:{act.value}:{topic}",
                "location_id": attempt.expected_location_id,
                "location_description": next(
                    item.description
                    for item in self.world.locations
                    if item.id == attempt.expected_location_id
                ),
            },
        )

    def _resolve_rest(self, attempt: ActionAttempt):
        return (
            EventType.RESTED,
            self._at(attempt.expected_location_id),
            Delta(
                needs=(NeedDelta(attempt.actor_id, "fatigue", -25),),
            ),
            {"location_id": attempt.expected_location_id, "public_trace": True},
        )

    def _resolve_wait(self, attempt: ActionAttempt):
        return (
            EventType.WAITED,
            self._at(attempt.expected_location_id),
            Delta(),
            {"location_id": attempt.expected_location_id},
        )

    def _at(self, location_id: str) -> tuple[str, ...]:
        return tuple(
            character_id
            for character_id, state in self.log.state.characters.items()
            if state.location_id == location_id
            and (
                self.observer_scope is None
                or character_id in self.observer_scope
            )
        )
