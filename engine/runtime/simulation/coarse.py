"""Boundary selection and replayable deltas for coarse catch-up."""

from __future__ import annotations

from typing import Any

from engine.runtime.kernel.events import (
    Delta,
    EventType,
    NeedDelta,
    PlanDelta,
    QuantityDelta,
)
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.space import ActionKind


def coarse_boundary(run: AutonomousRun, target_tick: int) -> int:
    current = run.state.tick
    boundaries = [target_tick]
    handled_gates = {
        event.data.get("gate_id")
        for event in run.events
        if event.event_type in {EventType.GATE_OPENED, EventType.USER_INTERVENTION}
    }
    fired_incidents = {
        event.data.get("rule_id")
        for event in run.events
        if event.event_type is EventType.INCIDENT_OCCURRED
    }
    for rule in run.compiled.world.rules:
        trigger_tick = rule.get("trigger", {}).get("tick")
        if not isinstance(trigger_tick, int):
            continue
        if (
            rule.get("type") == "user_gate"
            and rule.get("id") not in handled_gates
            and current < trigger_tick <= target_tick
        ):
            boundaries.append(trigger_tick)
        elif (
            rule.get("type") == "incident"
            and rule.get("id") not in fired_incidents
            and current < trigger_tick <= target_tick
        ):
            boundaries.append(max(current, trigger_tick - 1))
    completed_phases = {
        event.data.get("phase_id")
        for event in run.events
        if event.event_type is EventType.PHASE_SNAPSHOT
    }
    evolution = dict(run.compiled.workflow.evolution.policy)
    for phase in evolution.get("phase_predicates", ()):
        if phase.get("id") in completed_phases:
            continue
        tick_minima = [
            int(predicate["minimum"])
            for predicate in phase.get("predicates", ())
            if predicate.get("type") == "tick"
        ]
        if tick_minima:
            threshold = max(tick_minima)
            if current < threshold <= target_tick:
                boundaries.append(threshold)
    return min(boundaries)


def coarse_delta(
    run: AutonomousRun,
    ticks: int,
    need_decay: tuple[tuple[str, int], ...],
) -> tuple[Delta, dict[str, Any], tuple[str, ...]]:
    if ticks <= 0:
        return Delta(), {"needs": 0, "resources": 0, "plans": 0}, (
            "no coarse interval remained",
        )
    needs = [
        NeedDelta(character_id, need, amount * ticks)
        for character_id in sorted(run.state.characters)
        for need, amount in need_decay
    ]
    available = dict(run.state.resources)
    resources: list[QuantityDelta] = []
    inventories: list[QuantityDelta] = []
    plans: list[PlanDelta] = []
    for character_id in sorted(run.state.characters):
        character = run.state.characters[character_id]
        plan = character.short_plan
        if (
            character.participant_kind == "npc"
            and len(plan) == 3
            and plan[0] == ActionKind.GATHER.value
            and plan[2] == character.location_id
            and available.get(plan[1], 0) > 0
        ):
            quantity = min(ticks, available[plan[1]])
            available[plan[1]] -= quantity
            resources.append(QuantityDelta(character.location_id, plan[1], -quantity))
            inventories.append(QuantityDelta(character_id, plan[1], quantity))
            needs.append(NeedDelta(character_id, "resources", -16 * quantity))
            plans.append(PlanDelta(character_id, ()))
    delta = Delta(
        resources=tuple(resources),
        inventories=tuple(inventories),
        needs=tuple(needs),
        plans=tuple(plans),
        advance_time=ticks,
        advance_tick=ticks,
    )
    return delta, {
        "needs": len(needs),
        "resources": sum(-item.amount for item in resources),
        "plans": len(plans),
    }, (
        "need drift is linear and clamped by WorldState.apply",
        "only already-active local gather plans may settle resources",
        "coarse simulation emits no dialogue, secrets, relationships, memories, or Soul changes",
        "coarse simulation does not backfill detail when a character later becomes hot",
    )
