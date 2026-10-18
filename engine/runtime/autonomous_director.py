"""Structured, non-character direction for autonomous package runs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Iterable

from engine.runtime.kernel.events import (
    Delta,
    EventType,
    KnowledgeDelta,
    NeedDelta,
    QuantityDelta,
    WorldEvent,
)
from engine.runtime.workflow import InterventionContext, dispatch_workflow_step


@dataclass(frozen=True)
class PendingUserGate:
    gate_id: str
    prompt: str
    choice_ids: tuple[str, ...]
    opened_tick: int
    deadline_tick: int


def run_incident_scheduler(
    run: Any,
    budget: int = 1,
    *,
    observer_ids: tuple[str, ...] | None = None,
) -> WorldEvent | None:
    """Select one legal due incident, or record an explicit scheduler rest."""
    return dispatch_workflow_step(
        run.compiled.workflow.intervention,
        "incident",
        InterventionContext(
            {
                "incident": lambda: _run_incident_scheduler(
                    run, budget, observer_ids=observer_ids
                )
            }
        ),
    )


def _run_incident_scheduler(
    run: Any,
    budget: int = 1,
    *,
    observer_ids: tuple[str, ...] | None = None,
) -> WorldEvent | None:

    if not _intervention_allowed(run, "allow_incidents"):
        raise ValueError("incident execution is disabled by intervention workflow")
    if budget < 0:
        raise ValueError("incident budget must be non-negative")
    fired = {
        event.data.get("rule_id")
        for event in run.events
        if event.event_type is EventType.INCIDENT_OCCURRED
    }
    due = [
        rule
        for rule in run.compiled.world.rules
        if rule.get("type") == "incident" and _rule_is_due(run, rule, fired)
    ]
    if not due:
        return None
    legal = [
        rule
        for rule in due
        if int(rule.get("cost", 1)) <= budget
        and _effects_are_legal(run, rule.get("effects", ()))
    ]
    if not legal:
        return _append_system_event(
            run,
            EventType.INCIDENT_RESTED,
            Delta(),
            {
                "reason": "no legal incident within budget",
                "candidate_rule_ids": tuple(sorted(str(rule["id"]) for rule in due)),
                "budget": budget,
            },
            "incident scheduler may rest",
            observer_ids=observer_ids,
        )
    selected = min(
        legal,
        key=lambda rule: hashlib.sha256(
            f"{run.state.seed}:{run.state.tick}:{rule['id']}".encode()
        ).digest(),
    )
    witnesses = (
        tuple(
            character_id
            for character_id, character in run.state.characters.items()
            if character.participant_kind == "npc" or character.active
        )
        if observer_ids is None
        else observer_ids
    )
    fact_id = f"incident:{selected['id']}"
    delta = _delta_for_effects(run, selected["effects"])
    delta = replace(
        delta,
        knowledge=tuple(
            KnowledgeDelta(character_id, fact_id, "world")
            for character_id in witnesses
        ),
    )
    return _append_system_event(
        run,
        EventType.INCIDENT_OCCURRED,
        delta,
        {
            "rule_id": selected["id"],
            "fact_id": fact_id,
            "summary": selected["summary"],
            "cost": selected.get("cost", 1),
            "effects": tuple(dict(item) for item in selected["effects"]),
            **_place_binding(run, selected),
        },
        f"incident rule {selected['id']} triggered",
        target_id=str(selected["id"]),
        observer_ids=observer_ids,
    )


def open_due_user_gate(run: Any) -> PendingUserGate | None:
    if not _intervention_allowed(run, "allow_gates"):
        return None
    pending = get_pending_user_gate(run)
    if pending is not None:
        return pending
    handled = {
        event.data.get("gate_id")
        for event in run.events
        if event.event_type in {EventType.GATE_OPENED, EventType.USER_INTERVENTION}
    }
    due = sorted(
        (
            rule
            for rule in run.compiled.world.rules
            if rule.get("type") == "user_gate"
            and _rule_is_due(run, rule, handled)
        ),
        key=lambda rule: str(rule["id"]),
    )
    if not due:
        return None
    rule = due[0]
    deadline_tick = run.state.tick + int(rule.get("deadline_ticks", 1))
    _append_system_event(
        run,
        EventType.GATE_OPENED,
        Delta(),
        {
            "gate_id": rule["id"],
            "prompt": rule["prompt"],
            "choice_ids": tuple(choice["id"] for choice in rule["choices"]),
            "deadline_tick": deadline_tick,
            **_place_binding(run, rule),
        },
        f"user gate {rule['id']} triggered",
        target_id=str(rule["id"]),
    )
    return get_pending_user_gate(run)


def get_pending_user_gate(run: Any) -> PendingUserGate | None:
    resolved = {
        event.data.get("gate_id")
        for event in run.events
        if event.event_type is EventType.USER_INTERVENTION
    }
    for event in reversed(run.events):
        if event.event_type is not EventType.GATE_OPENED:
            continue
        gate_id = str(event.data["gate_id"])
        if gate_id not in resolved:
            return PendingUserGate(
                gate_id=gate_id,
                prompt=str(event.data["prompt"]),
                choice_ids=tuple(event.data["choice_ids"]),
                opened_tick=event.tick,
                deadline_tick=int(event.data["deadline_tick"]),
            )
    return None


def apply_gate_intervention(
    run: Any, gate_id: str, choice_id: str | None = None
) -> WorldEvent:
    return dispatch_workflow_step(
        run.compiled.workflow.intervention,
        "user_gate",
        InterventionContext(
            {
                "user_gate": lambda: _apply_gate_intervention(
                    run, gate_id, choice_id
                )
            }
        ),
    )


def _apply_gate_intervention(
    run: Any, gate_id: str, choice_id: str | None = None
) -> WorldEvent:
    if not _intervention_allowed(run, "allow_gates"):
        raise ValueError("gate execution is disabled by intervention workflow")
    pending = get_pending_user_gate(run)
    if pending is None or pending.gate_id != gate_id:
        raise ValueError("gate is not pending")
    rule = next(
        rule
        for rule in run.compiled.world.rules
        if rule.get("type") == "user_gate" and rule.get("id") == gate_id
    )
    expired = run.state.tick >= pending.deadline_tick
    selected_id = "abstain" if choice_id is None or expired else choice_id
    if selected_id == "abstain":
        effects: Iterable[dict[str, Any]] = ()
        costs: Iterable[dict[str, Any]] = ()
        observation = ""
    else:
        choice = next(
            (item for item in rule["choices"] if item["id"] == selected_id),
            None,
        )
        if choice is None:
            raise ValueError("choice is not allowed by the pending gate")
        effects = choice.get("effects", ())
        costs = choice.get("costs", ())
        observation = str(choice.get("observation", "")).strip()
    combined = tuple(effects) + tuple(
        {**cost, "amount": -int(cost["amount"])} for cost in costs
    )
    if not _effects_are_legal(run, combined):
        raise ValueError("intervention cost or effect is not legal in current state")
    return _append_system_event(
        run,
        EventType.USER_INTERVENTION,
        _delta_for_effects(run, combined),
        {
            "gate_id": gate_id,
            "choice_id": selected_id,
            "abstained": selected_id == "abstain",
            "defaulted": choice_id is None or expired,
            "expired": expired,
            "effects": tuple(dict(item) for item in effects),
            "costs": tuple(dict(item) for item in costs),
            "observation": observation,
            **_place_binding(run, rule),
        },
        f"author-allowed choice for user gate {gate_id}",
        target_id=gate_id,
    )


def apply_fate_intervention(run: Any, intervention_id: str) -> WorldEvent:
    """Apply an authored, non-character Fate rule as one atomic transaction."""
    return dispatch_workflow_step(
        run.compiled.workflow.intervention,
        "fate",
        InterventionContext(
            {
                "fate": lambda: _apply_fate_intervention(run, intervention_id)
            }
        ),
    )


def _apply_fate_intervention(run: Any, intervention_id: str) -> WorldEvent:

    if not _intervention_allowed(run, "allow_fate"):
        raise ValueError("fate execution is disabled by intervention workflow")
    rule = next(
        (
            item
            for item in run.compiled.world.rules
            if item.get("type") == "fate_intervention"
            and item.get("id") == intervention_id
        ),
        None,
    )
    if rule is None:
        raise ValueError("unknown fate intervention")
    prior = [
        event
        for event in run.events
        if event.event_type is EventType.FATE_INTERVENTION
        and event.data.get("intervention_id") == intervention_id
    ]
    if rule.get("once", False) and prior:
        raise ValueError("fate intervention has already been used")
    cooldown = int(rule.get("cooldown_ticks", 0))
    if prior and run.state.tick - prior[-1].tick < cooldown:
        raise ValueError("fate intervention is cooling down")
    conditions = rule.get("conditions", {})
    if run.state.tick < int(conditions.get("tick_gte", 0)):
        raise ValueError("fate intervention conditions are not met")
    tick_lte = conditions.get("tick_lte")
    if tick_lte is not None and run.state.tick > int(tick_lte):
        raise ValueError("fate intervention conditions are not met")
    if any(
        run.state.resources[str(item["resource_id"])] < int(item["minimum"])
        for item in conditions.get("resources", ())
    ):
        raise ValueError("fate intervention conditions are not met")
    effects = tuple(rule.get("effects", ()))
    costs = tuple(rule.get("costs", ()))
    combined = effects + tuple(
        {**cost, "amount": -int(cost["amount"])} for cost in costs
    )
    if not _effects_are_legal(run, combined):
        raise ValueError("fate intervention cost or effect is not legal in current state")
    return _append_system_event(
        run,
        EventType.FATE_INTERVENTION,
        _delta_for_effects(run, combined),
        {
            "intervention_id": intervention_id,
            "summary": rule["summary"],
            "effects": tuple(dict(item) for item in effects),
            "costs": tuple(dict(item) for item in costs),
            "conditions": dict(conditions),
        },
        f"fate intervention rule {intervention_id} was legally invoked",
        target_id=intervention_id,
    )


def wait_on_pending_user_gate(run: Any) -> WorldEvent:
    """Advance only the gate deadline clock; never schedule character action."""

    pending = get_pending_user_gate(run)
    if pending is None:
        raise ValueError("no user gate is pending")
    waited = _append_system_event(
        run,
        EventType.GATE_WAITED,
        Delta(advance_time=1, advance_tick=1),
        {"gate_id": pending.gate_id, "deadline_tick": pending.deadline_tick},
        f"waiting for user gate {pending.gate_id}",
        target_id=pending.gate_id,
    )
    if run.state.tick >= pending.deadline_tick:
        apply_gate_intervention(run, pending.gate_id)
    return waited


def _rule_is_due(run: Any, rule: dict[str, Any], handled: set[Any]) -> bool:
    """A placed rule waits until someone is still in that place."""

    if rule.get("id") in handled:
        return False
    trigger = rule.get("trigger", {}).get("tick")
    if isinstance(trigger, bool) or not isinstance(trigger, int):
        return False
    location_id = str(rule.get("location_id") or "")
    if location_id:
        return trigger <= run.state.tick and _location_occupied(
            run, location_id
        )
    return trigger == run.state.tick


def _location_occupied(run: Any, location_id: str) -> bool:
    return any(
        character.active and character.location_id == location_id
        for character in run.state.characters.values()
    )


def _place_binding(run: Any, rule: dict[str, Any]) -> dict[str, str]:
    location_id = str(rule.get("location_id") or "")
    if not location_id:
        return {}
    scene_id = f"scene:{location_id}"
    for entity in run.state.entities.values():
        presence = entity.components.get("presence", {})
        if (
            str(presence.get("location_id", "")) == location_id
            and presence.get("scene_id")
        ):
            scene_id = str(presence["scene_id"])
            break
    return {"location_id": scene_id, "scene_id": scene_id}


def _effects_are_legal(run: Any, effects: Iterable[dict[str, Any]]) -> bool:
    totals: dict[str, int] = {}
    for effect in effects:
        if effect["type"] == "resource":
            resource_id = str(effect["resource_id"])
            totals[resource_id] = totals.get(resource_id, 0) + int(effect["amount"])
    return all(run.state.resources[item] + amount >= 0 for item, amount in totals.items())


def _intervention_allowed(run: Any, field: str) -> bool:
    return bool(dict(run.compiled.workflow.intervention.policy).get(field, False))


def _delta_for_effects(run: Any, effects: Iterable[dict[str, Any]]) -> Delta:
    resources: list[QuantityDelta] = []
    needs: list[NeedDelta] = []
    for effect in effects:
        amount = int(effect["amount"])
        if effect["type"] == "resource":
            resources.append(QuantityDelta("world", str(effect["resource_id"]), amount))
        else:
            needs.extend(
                NeedDelta(character_id, str(effect["need"]), amount)
                for character_id in sorted(run.state.characters)
            )
    return Delta(resources=tuple(resources), needs=tuple(needs))


def _append_system_event(
    run: Any,
    event_type: EventType,
    delta: Delta,
    data: dict[str, Any],
    basis: str,
    *,
    target_id: str | None = None,
    observer_ids: tuple[str, ...] | None = None,
) -> WorldEvent:
    pre_state_hash = run.state.state_hash()
    cursor = len(run.events)
    rule_basis = (basis,)
    target = target_id or run.state.world_id
    return run.log.append(
        WorldEvent(
            sequence=cursor,
            tick=run.state.tick,
            event_type=event_type,
            actor_id=None,
            observers=(
                tuple(
                    character_id
                    for character_id, character in run.state.characters.items()
                    if character.participant_kind == "npc" or character.active
                )
                if observer_ids is None
                else observer_ids
            ),
            delta=delta,
            data={
                **data,
                "pre_state_hash": pre_state_hash,
                "world_hash": run.state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": target,
                "rule_basis": rule_basis,
            },
            pre_state_hash=pre_state_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=target,
            rule_basis=rule_basis,
        )
    )
