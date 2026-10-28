"""Match commitments to committed outcomes, never mutable later state."""

from __future__ import annotations


def obligation_outcome_matches(obligation, event, events, *, activity_starts=None):
    sender, recipient = obligation.promisor_id, obligation.beneficiary_id
    if event.tick > obligation.deadline_tick:
        return False
    if obligation.action_verb == "speak":
        return (event.event_type.value == "dialogue" and event.actor_id == sender
                and event.data.get("listener_id") == recipient)
    if obligation.action_verb == "transfer":
        offer = event.data.get("offer", {})
        return (event.event_type.value == "exchange_updated" and offer.get("status") == "accepted"
                and offer.get("sender_id") == sender and offer.get("recipient_id") == recipient
                and offer.get("item_id") == obligation.target_id
                and offer.get("quantity", 0) >= obligation.quantity)
    if (event.event_type.value != "activity_finished" or event.actor_id != sender
            or event.target_entity_id != obligation.target_id or event.data.get("status") != "completed"):
        return False
    if activity_starts is None:
        started = next((e for e in events[:event.sequence] if e.event_type.value == "activity_started"
                        and e.data["activity"]["activity_id"] == event.data.get("activity_id")), None)
    else:
        sequence = activity_starts.get(event.data.get("activity_id"))
        started = events[sequence] if sequence is not None and sequence < event.sequence else None
    if (started is None or started.actor_id != sender
            or started.data["activity"]["verb"] != "repair"
            or started.data["activity"]["target_id"] != obligation.target_id):
        return False
    return any(patch.entity_id == obligation.target_id and patch.component is not None
               and patch.component.component_type == "attributes"
               and patch.component.data.get("condition", 0) >= obligation.quantity
               for patch in event.delta.entity_patches)
