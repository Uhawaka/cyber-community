"""Typed evolution phase predicates and factual snapshots."""

from __future__ import annotations

from typing import Any

from engine.runtime.kernel.events import EventType, WorldEvent
from engine.runtime.simulation.run import AutonomousRun


def check_phase_snapshots(
    run: AutonomousRun, *, observer_ids: tuple[str, ...]
) -> None:
    policy = dict(run.compiled.workflow.evolution.policy)
    completed = {
        event.data.get("phase_id")
        for event in run.events
        if event.event_type is EventType.PHASE_SNAPSHOT
    }
    for phase in policy.get("phase_predicates", ()):
        phase_id = phase["id"]
        if phase_id in completed:
            continue
        results = tuple(
            _evaluate_phase_predicate(run, predicate)
            for predicate in phase["predicates"]
        )
        if not all(item["satisfied"] for item in results):
            continue
        state = run.state
        pre_state_hash = state.state_hash()
        cursor = len(run.events)
        current_state = {
            "tick": state.tick,
            "world_time": state.world_time,
            "resources": dict(state.resources),
            "relationships": {
                source: dict(values)
                for source, values in state.relationships.items()
            },
            "locations": {
                actor_id: actor.location_id
                for actor_id, actor in state.characters.items()
            },
        }
        run.log.append(
            WorldEvent(
                sequence=cursor,
                tick=state.tick,
                event_type=EventType.PHASE_SNAPSHOT,
                actor_id=None,
                observers=observer_ids,
                data={
                    "phase_id": phase_id,
                    "target": phase["target"],
                    "state_target": phase["target"],
                    "result": {
                        "satisfied": True,
                        "predicate_results": results,
                    },
                    "predicate_results": results,
                    "current_state": current_state,
                    "unresolved_items": tuple(phase["unresolved_items"]),
                    "pre_state_hash": pre_state_hash,
                    "world_hash": state.world_hash,
                    "deterministic_cursor": cursor,
                    "target_entity_id": phase_id,
                    "rule_basis": ("typed evolution phase predicates satisfied",),
                },
                pre_state_hash=pre_state_hash,
                world_hash=state.world_hash,
                deterministic_cursor=cursor,
                target_entity_id=phase_id,
                rule_basis=("typed evolution phase predicates satisfied",),
            )
        )


def _evaluate_phase_predicate(
    run: AutonomousRun, predicate: dict[str, Any]
) -> dict[str, Any]:
    kind = predicate["type"]
    minimum = predicate["minimum"]
    if kind == "tick":
        actual = run.state.tick
    elif kind == "resource":
        actual = run.state.resources.get(predicate["resource_id"], 0)
    else:
        actual = run.state.relationships.get(predicate["source_id"], {}).get(
            predicate["target_id"], 0
        )
    return {
        "predicate": dict(predicate),
        "actual": actual,
        "satisfied": actual >= minimum,
    }
