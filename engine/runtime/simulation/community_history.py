"""Copy history into immutable evidence, respecting the selected audience."""

from __future__ import annotations

from engine.contracts.community_history import CommunityFact
from engine.runtime.character.community_event_view import visible_event_summary

PRIVATE = {"cognition_recorded", "goal_updated", "plan_updated", "inspected", "action_rejected",
           "intent_plan_updated",
           "request_updated", "responsibility_updated", "organization_recorded", "organization_read",
           "loan_updated", "membership_updated", "model_decision_requested", "model_decision_resolved",
           "organization_role_updated", "lease_updated"}


def community_history(run, *, audience="observer", actor_id=None):
    if audience not in {"observer", "omniscient", "character"}:
        raise ValueError("unknown community audience")
    if audience == "character" and actor_id not in run.state.characters:
        raise ValueError("character audience requires an existing actor")
    visible = {
        e.sequence for e in run.events
        if audience == "omniscient"
        or audience == "character" and actor_id in e.observers
        or audience == "observer" and e.event_type.value not in PRIVATE
        and (e.event_type.value != "dialogue" or len(e.observers) > 1)
    }
    goals = {
        e.data["goal"]["goal_id"]: e.data["goal"]
        for e in run.events if e.sequence in visible and e.event_type.value == "goal_updated"
    }
    result = []
    activities = {
        e.data["activity"]["activity_id"]: e.data["activity"]
        for e in run.events if e.event_type.value == "activity_started"
    }
    for event in run.events:
        if event.sequence not in visible or event.event_type.value in {"run_created", "community_tick"}:
            continue
        data = event.data
        goal = data.get("goal") or goals.get(data.get("plan", {}).get("goal_id"), {})
        offer, obligation = data.get("offer", {}), data.get("commitment", {})
        request = data.get("request", {})
        handoff = data.get("handoff", {})
        target = goal.get("target_id") or obligation.get("target_id") or offer.get("item_id") or event.target_entity_id or ""
        report = data.get("reported_claim")
        if report:
            target = report["subject"]
        sources = tuple(
            int(ref.split(":", 1)[1]) for ref in data.get("source_refs", ())
            if ref.startswith("event:") and int(ref.split(":", 1)[1]) in visible
        )
        participants = tuple(sorted(set(event.observers) | ({event.actor_id} if event.actor_id else set())))
        result.append(CommunityFact(
            event.sequence, event.tick, event.event_type.value, event.actor_id,
            participants, sources, target,
            visible_event_summary(event, actor_id, omniscient=audience == "omniscient"),
            offer.get("offer_id") or obligation.get("commitment_id") or request.get("request_id")
            or handoff.get("handoff_id") or data.get("activity_id") or "",
            goal.get("status") or offer.get("status") or obligation.get("status") or request.get("status")
            or handoff.get("status") or data.get("status", ""),
            goal.get("goal_id", ""), bool(event.delta.entity_patches or event.delta.resources or event.delta.inventories
                                         or handoff.get("status") == "accepted"),
            str(data.get("utterance") or ""),
            goal.get("action_verb") or data.get("activity", {}).get("verb")
            or activities.get(data.get("activity_id"), {}).get("verb")
            or (event.delta.actions[0].kind if event.delta.actions else ""),
        ))
    return tuple(result)
