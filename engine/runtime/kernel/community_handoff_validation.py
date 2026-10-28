"""Responsibility changes require a current holder and independent consent."""

from dataclasses import asdict

from engine.contracts.society import ResponsibilityHandoff


def responsibility_assignments(world, events=()):
    assignments = {
        (character.id, target)
        for character in world.characters
        for target in dict(character.profile).get("responsibilities", ())
    }
    for event in events:
        if event.event_type.value == "responsibility_updated":
            raw = event.data["handoff"]
            if raw["status"] == "accepted":
                assignments.discard((raw["sender_id"], raw["target_id"]))
                assignments.add((raw["recipient_id"], raw["target_id"]))
    return assignments


def validate_handoff(event, events, state, community, world):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError

    try:
        if world is None or community is None:
            raise ValueError("handoff requires bound author definitions")
        raw = event.data["handoff"]
        record = ResponsibilityHandoff(**{**raw, "source_refs": tuple(raw["source_refs"])})
        if record.source_refs != tuple(event.data["source_refs"]):
            raise ValueError("handoff sources must match event")
        parties = (record.sender_id, record.recipient_id)
        if any(p not in state.characters for p in parties):
            raise ValueError("handoff parties must exist")
        if event.target_entity_id != record.target_id:
            raise ValueError("handoff event must target its responsibility")
        expected_audience = tuple(sorted(p for p in parties if state.characters[p].active))
        if event.observers != expected_audience:
            raise ValueError("handoff is private to its parties")
        resource = next((r for r in world.resources if r.id == record.target_id), None)
        repair = next((r for r in community.repairs if r.target_id == record.target_id), None)
        if resource is None or repair is None or dict(resource.properties).get("hidden") is True:
            raise ValueError("handoff requires a registered visible maintenance responsibility")
        previous = next((e for e in reversed(events)
                         if e.event_type == event.event_type
                         and e.data["handoff"]["handoff_id"] == record.handoff_id), None)
        assignments = responsibility_assignments(world, events)
        if previous is None:
            if record.status != "proposed" or event.actor_id != record.sender_id:
                raise ValueError("only current holder may propose a handoff")
            if record.deadline_tick != state.tick + 24:
                raise ValueError("handoff answer deadline must be 24 ticks")
            if (record.sender_id, record.target_id) not in assignments:
                raise ValueError("sender does not hold this responsibility")
            if (record.recipient_id, record.target_id) in assignments:
                raise ValueError("recipient already holds this responsibility")
            latest = {e.data["handoff"]["handoff_id"]: e.data["handoff"] for e in events
                      if e.event_type == event.event_type}
            if any(r["target_id"] == record.target_id and r["status"] == "proposed"
                   for r in latest.values()):
                raise ValueError("a handoff for this target is already pending")
            if any(sum(p in (r["sender_id"], r["recipient_id"]) and r["status"] == "proposed"
                       for r in latest.values()) >= 16 for p in parties):
                raise ValueError("pending handoff budget exceeded")
        else:
            old = ResponsibilityHandoff(**{
                **previous.data["handoff"],
                "source_refs": tuple(previous.data["handoff"]["source_refs"]),
            })
            if any(value != asdict(old)[key] for key, value in asdict(record).items()
                   if key not in {"status", "source_refs"}):
                raise ValueError("handoff terms cannot change")
            if old.status != "proposed" or record.status not in {"accepted", "rejected", "expired"}:
                raise ValueError("only a pending handoff may be answered")
            if f"event:{previous.sequence}" not in record.source_refs:
                raise ValueError("handoff answer must cite its proposal")
            if record.status == "expired":
                if (state.tick <= record.deadline_tick or event.actor_id != record.sender_id
                        or event.data.get("system_update") is not True):
                    raise ValueError("expiry requires elapsed deadline")
            elif event.actor_id != record.recipient_id or state.tick > record.deadline_tick:
                raise ValueError("only recipient may answer before deadline")
            if record.status == "accepted":
                if (record.sender_id, record.target_id) not in assignments:
                    raise ValueError("sender no longer holds responsibility")
                if (record.recipient_id, record.target_id) in assignments:
                    raise ValueError("recipient already holds responsibility")
                from engine.runtime.kernel.community_learning_validation import owned_skills
                skills = owned_skills(world, events, record.recipient_id)
                if not set((*resource.required_skills, *repair.required_skills)) <= skills:
                    raise ValueError("recipient lacks maintenance capability")
        system = record.status == "expired"
        if bool(event.data.get("system_update")) != system:
            raise ValueError("only expiry is a system transition")
        if not system:
            if not all(state.characters[p].active for p in parties):
                raise ValueError("handoff requires active parties")
            if any(state.characters[p].location_id != resource.location_id for p in parties):
                raise ValueError("handoff requires both parties at the maintained device")
        verb = "handoff" if previous is None else "accept" if record.status == "accepted" else "reject"
        target = record.recipient_id if previous is None else record.handoff_id
        expected_delta = Delta() if system else Delta(actions=(
            ActionRecord(event.actor_id, verb, target, state.tick),
        ))
        if event.delta != expected_delta:
            raise ValueError("handoff cannot change materials, promises or external state")
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        raise EventValidationError("invalid responsibility handoff: " + str(exc)) from exc
