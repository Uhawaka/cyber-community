"""Typed, owned goal and plan transitions without optimistic completion."""

from __future__ import annotations

from engine.contracts.community import Goal, Plan


def validate_goal_event(event, events, state):
    from engine.runtime.kernel.events import EventValidationError

    kind = event.event_type.value
    key, cls, id_field = (
        ("goal", Goal, "goal_id") if kind == "goal_updated"
        else ("plan", Plan, "plan_id")
    )
    try:
        raw = event.data[key]
        record = cls(**{**raw, "source_refs": tuple(raw["source_refs"])})
        if record.owner_id != event.actor_id or not set(record.source_refs) <= set(event.data["source_refs"]):
            raise ValueError("goal/plan must have owned matching sources")
        previous = next((
            prior.data[key] for prior in reversed(events)
            if prior.event_type == event.event_type
            and prior.data[key][id_field] == getattr(record, id_field)
        ), None)
        if previous:
            immutable = ("owner_id", "description", "target_id", "action_verb", "quantity") if key == "goal" else ("owner_id", "goal_id")
            if any(previous.get(field, getattr(record, field)) != getattr(record, field) for field in immutable):
                raise ValueError("goal/plan identity and completion criterion are immutable")
            if previous["status"] in {"completed", "abandoned"}:
                raise ValueError("terminal goal/plan cannot be reopened")
        elif record.status not in {"active", "ready"}:
            raise ValueError("goal/plan must begin active/ready")
        if key == "goal" and record.status == "completed":
            origins = [
                prior for prior in events if prior.event_type.value == "goal_updated"
                and prior.data["goal"]["goal_id"] == record.goal_id
            ]
            start = origins[0].sequence
            evidence = [
                prior for prior in events if prior.sequence > start
                and prior.actor_id == record.owner_id
            ]
            matched = False
            for prior in evidence:
                if f"event:{prior.sequence}" not in record.source_refs:
                    continue
                target = prior.target_entity_id
                if record.action_verb == "take":
                    matched |= target == record.target_id and prior.event_type.value == "gathered" and state.inventories[record.owner_id].get(target, 0) >= record.quantity
                elif record.action_verb == "speak":
                    matched |= prior.event_type.value == "dialogue" and prior.data.get("listener_id") == record.target_id
                elif record.action_verb == "repair":
                    entity = state.entities.get(record.target_id)
                    condition = entity.components["attributes"]["condition"] if entity else 0
                    matched |= target == record.target_id and condition >= record.quantity and (
                        prior.event_type.value == "inspected"
                        or prior.event_type.value == "activity_finished" and prior.data.get("status") == "completed"
                    )
                elif record.action_verb in {"move", "learn"}:
                    matched |= target == record.target_id and prior.event_type.value == "activity_finished" and prior.data.get("status") == "completed"
            if not matched:
                raise ValueError("completion requires committed matching outcome, not intent")
        if key == "plan":
            goal = next((
                prior.data["goal"] for prior in reversed(events)
                if prior.event_type.value == "goal_updated"
                and prior.data["goal"]["goal_id"] == record.goal_id
            ), None)
            if goal is None or goal["owner_id"] != event.actor_id:
                raise ValueError("plan requires an owned existing goal")
            if previous and record.attempts < previous["attempts"]:
                raise ValueError("plan attempts cannot decrease")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid goal/plan lifecycle: " + str(exc)) from exc
