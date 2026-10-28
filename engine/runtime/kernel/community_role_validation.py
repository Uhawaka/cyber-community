"""Organization offices are voluntary and do not confer ownership or consent."""

from engine.runtime.kernel.community_membership_validation import current_members


def role_holders(group, events, index=None):
    holders = {role.role_id: role.initial_holder_id for role in group.roles}
    if index is not None:
        changes = index.role_changes.get(group.organization_id, {})
        for role_id, initial in holders.items():
            sequence, holder = changes.get(role_id, (-1, initial))
            if holder and index.membership_exits.get((group.organization_id, holder), -1) > sequence:
                holder = ""
            holders[role_id] = holder
        return holders
    for event in events:
        if event.target_entity_id != group.organization_id:
            continue
        if event.event_type.value == "organization_role_updated":
            raw = event.data["role"]
            holders[raw["role_id"]] = raw["holder_id"] if raw["status"] == "held" else ""
        elif event.event_type.value == "membership_updated" and event.data["membership"]["status"] == "left":
            holders = {key: "" if holder == event.actor_id else holder for key, holder in holders.items()}
    return holders


def validate_role(event, events, state, community, world, index=None):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
    from engine.runtime.kernel.community_learning_validation import owned_skills
    try:
        group = next(g for g in community.organizations if g.organization_id == event.target_entity_id)
        raw = event.data["role"]
        role = next(role for role in group.roles if role.role_id == raw["role_id"])
        if set(raw) != {"organization_id", "role_id", "holder_id", "status"}:
            raise ValueError("unknown or missing role fields")
        actor = state.characters[event.actor_id]
        members = current_members(group, events, index)
        if (not actor.active or actor.location_id != group.location_id
                or event.actor_id not in members):
            raise ValueError("office requires an active local member")
        if raw["organization_id"] != group.organization_id or raw["holder_id"] != event.actor_id:
            raise ValueError("office action must belong to its actor")
        current = role_holders(group, events, index)[role.role_id]
        if raw["status"] == "held":
            if current:
                raise ValueError("office is already occupied")
            if not set(role.required_skills) <= owned_skills(world, events, event.actor_id):
                raise ValueError("office requires actual registered skills")
            verb = "take_role"
        elif raw["status"] == "vacant":
            if current != event.actor_id:
                raise ValueError("only the holder may leave an office")
            verb = "leave_role"
        else:
            raise ValueError("invalid office status")
        audience = tuple(sorted(p for p in members
                                if state.characters[p].active
                                and state.characters[p].location_id == group.location_id))
        if event.observers != audience or event.delta != Delta(actions=(
            ActionRecord(event.actor_id, verb, group.organization_id, state.tick),
        )):
            raise ValueError("office action cannot transfer goods or act for other members")
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:
        raise EventValidationError("invalid organization office: " + str(exc)) from exc
