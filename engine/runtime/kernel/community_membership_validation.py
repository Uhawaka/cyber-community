"""Voluntary membership changes remove access, not personal obligations."""


def current_members(group, events, index=None):
    members = set(group.member_ids)
    if index is not None:
        for person, joined in index.membership_changes.get(group.organization_id, {}).items():
            if joined:
                members.add(person)
            else:
                members.discard(person)
        return members
    for event in events:
        if (event.event_type.value != "membership_updated"
                or event.target_entity_id != group.organization_id):
            continue
        status = event.data.get("membership", {}).get("status")
        if status == "left":
            members.discard(event.actor_id)
        elif status == "joined":
            members.add(event.actor_id)
    return members


def valid_invitation(events, state, group, actor_id, sequence, members, index=None):
    if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence < len(events):
        return False
    invitation = events[sequence]
    invited = invitation.data.get("membership", {})
    inviter = state.characters.get(invitation.actor_id)
    if index is not None:
        uninterrupted = all(
            index.membership_exits.get((group.organization_id, person), -1) <= sequence
            for person in (invitation.actor_id, actor_id)
        )
    else:
        uninterrupted = not any(e.event_type.value == "membership_updated"
                                and e.target_entity_id == group.organization_id
                                and e.data.get("membership", {}).get("status") == "left"
                                and e.actor_id in {invitation.actor_id, actor_id}
                                for e in events[sequence + 1:])
    return (
        invitation.event_type.value == "membership_updated"
        and invitation.target_entity_id == group.organization_id
        and invited.get("status") == "invited" and invited.get("member_id") == actor_id
        and actor_id in invitation.observers and invitation.actor_id in members
        and inviter is not None and inviter.active and inviter.location_id == group.location_id
        and state.tick <= invitation.tick + 24
        and uninterrupted
    )


def validate_membership_change(event, events, state, community, index=None):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
    group = next((g for g in community.organizations
                  if g.organization_id == event.target_entity_id), None) if community else None
    actor = state.characters.get(event.actor_id)
    if (group is None or actor is None or not actor.active
            or actor.location_id != group.location_id):
        raise EventValidationError("membership change requires an active character at the organization")
    raw = event.data.get("membership")
    if (not isinstance(raw, dict) or raw.get("organization_id") != group.organization_id
            or not isinstance(raw.get("status"), str)
            or raw.get("status") not in {"left", "invited", "joined"}):
        raise EventValidationError("invalid membership change")
    members = current_members(group, events, index)
    if raw["status"] == "left":
        if set(raw) != {"organization_id", "member_id", "status"} or raw["member_id"] != event.actor_id:
            raise EventValidationError("membership exit must belong only to its actor")
        if event.actor_id not in members:
            raise EventValidationError("only a current member can leave an organization")
        verb = "resign"
        notified = members
    elif raw["status"] == "invited":
        if set(raw) != {"organization_id", "member_id", "status"} or not isinstance(raw["member_id"], str):
            raise EventValidationError("invalid invitation")
        invitee = state.characters.get(raw["member_id"])
        if (event.actor_id not in members or raw["member_id"] in members or invitee is None
                or not invitee.active or invitee.location_id != group.location_id):
            raise EventValidationError("invitation requires a local member and local nonmember")
        verb = "invite"
        notified = members | {raw["member_id"]}
    elif raw["status"] == "joined":
        if (set(raw) != {"organization_id", "member_id", "status", "invitation_sequence"}
                or raw["member_id"] != event.actor_id or event.actor_id in members):
            raise EventValidationError("an existing member cannot join again")
        sequence = raw["invitation_sequence"]
        if (not valid_invitation(events, state, group, event.actor_id, sequence, members, index)
                or f"event:{sequence}" not in event.data.get("source_refs", ())):
            raise EventValidationError("joining requires a current local invitation")
        verb = "join"
        notified = members | {event.actor_id}
    else:
        raise EventValidationError("invalid membership status")
    audience = tuple(sorted(p for p in notified
                            if state.characters[p].active
                            and state.characters[p].location_id == group.location_id))
    if event.observers != audience:
        raise EventValidationError("membership change audience must match local members")
    if event.delta != Delta(actions=(ActionRecord(event.actor_id, verb, group.organization_id, state.tick),)):
        raise EventValidationError("membership change cannot erase duties, debts or transfer goods")
