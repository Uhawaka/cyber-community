"""Learning grants only the registered skill after its actual duration."""

from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError, NeedDelta


def owned_skills(world, events, actor_id):
    character = next((c for c in world.characters if c.id == actor_id), None) if world else None
    if character is None:
        raise EventValidationError("skills require bound character definitions")
    return set(dict(character.profile).get("skills", ())) | {
        e.data["learned_skill"] for e in events
        if e.actor_id == actor_id and e.event_type.value == "activity_finished"
        and e.data.get("status") == "completed" and e.data.get("learned_skill")
    }


def validate_learning_start(event, activity, events, state, community, world):
    if activity.verb.value != "learn":
        return
    rule = next((r for r in community.learning if r.resource_id == activity.target_id), None) if community else None
    resource = next((r for r in world.resources if r.id == activity.target_id), None) if world else None
    entity = state.entities.get(activity.target_id)
    actor = state.characters[activity.actor_id]
    held = state.inventories[activity.actor_id].get(activity.target_id, 0) > 0
    if (rule is None or resource is None or entity is None or not actor.active
            or entity.version != activity.target_version
            or actor.location_id != entity.components["attributes"]["location_id"] and not held):
        raise EventValidationError("learning requires a registered current reachable carrier")
    skills = owned_skills(world, events, activity.actor_id)
    if (rule.skill in skills or not set((*resource.required_skills, *rule.prerequisite_skills)) <= skills
            or activity.due_tick - activity.started_tick != rule.duration_ticks):
        raise EventValidationError("learning requires registered duration and unmet skill with prerequisites")
    expected = Delta(
        actions=(ActionRecord(activity.actor_id, "learn", activity.target_id, state.tick),),
        needs=(NeedDelta(activity.actor_id, "fatigue", 2),),
    )
    if event.delta != expected:
        raise EventValidationError("learning start must match its registered effort")


def validate_learning_completion(event, started, state, community):
    activity = started.data["activity"]
    if activity["verb"] != "learn":
        return
    if event.delta != Delta():
        raise EventValidationError("learning cannot change materials or other objective state")
    if event.data["status"] != "completed":
        if event.data.get("learned_skill"):
            raise EventValidationError("unsuccessful learning cannot grant a skill")
        return
    rule = next((r for r in community.learning if r.resource_id == activity["target_id"]), None) if community else None
    entity = state.entities.get(activity["target_id"])
    actor = state.characters[event.actor_id]
    held = state.inventories[event.actor_id].get(activity["target_id"], 0) > 0
    if (rule is None or entity is None or not actor.active or entity.version != activity["target_version"]
            or actor.location_id != entity.components["attributes"]["location_id"] and not held
            or event.data.get("learned_skill") != rule.skill
            or event.data.get("resource_id") != rule.resource_id
            or event.observers != (event.actor_id,)
            or f"event:{started.sequence}" not in event.data.get("source_refs", ())):
        raise EventValidationError("learning completion requires its private registered skill outcome")
