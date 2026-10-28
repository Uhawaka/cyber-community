"""Separate an actor's decision reason from an observed action."""

PRIVATE_ACTION_REASONS = {
    "activity_started", "gathered", "rested", "waited",
    "membership_updated", "organization_role_updated",
}


def visible_event_summary(event, viewer_id=None, *, omniscient=False):
    data = event.data
    if (event.event_type.value in PRIVATE_ACTION_REASONS
            and not omniscient and (viewer_id is None or viewer_id != event.actor_id)):
        action = event.delta.actions[0] if event.delta.actions else None
        verb = action.kind if action else event.event_type.value
        target = action.target_id if action else event.target_entity_id
        return " ".join(str(value) for value in (event.actor_id, verb, target) if value)
    return str(data.get("utterance") or data.get("summary") or data.get("reason") or "")
