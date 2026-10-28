"""Temporary possession never implies ownership, seizure or retrospective consent."""

from dataclasses import asdict

from engine.contracts.society import MaterialLease


def lease_inventory_delta(record):
    from engine.runtime.kernel.events import QuantityDelta
    if record.status not in {"accepted", "returned"}:
        return ()
    sender, recipient = record.lessor_id, record.lessee_id
    if record.status == "returned":
        sender, recipient = recipient, sender
    return (QuantityDelta(sender, record.item_id, -record.quantity),
            QuantityDelta(recipient, record.item_id, record.quantity))


def leaseable(resource):
    properties = dict(resource.properties)
    return properties.get("portable") is True and properties.get("consumable") is not True


def validate_lease(event, events, state, world):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
    try:
        raw = event.data["lease"]
        record = MaterialLease(**{**raw, "source_refs": tuple(raw["source_refs"])})
        resource = next(r for r in world.resources if r.id == record.item_id)
        parties = record.lessor_id, record.lessee_id
        if not leaseable(resource) or any(person not in state.characters for person in parties):
            raise ValueError("lease requires registered portable nonconsumable goods and parties")
        if tuple(event.data["source_refs"]) != record.source_refs:
            raise ValueError("lease sources must exactly match event")
        previous = next((e for e in reversed(events) if e.event_type.value == "lease_updated"
                         and e.data["lease"]["lease_id"] == record.lease_id), None)
        system = event.data.get("system_update", False)
        if not isinstance(system, bool):
            raise ValueError("invalid lease system flag")
        if previous is None:
            if system or record.status != "proposed" or event.actor_id != record.lessor_id:
                raise ValueError("only lessor proposes a lease")
            if record.answer_deadline_tick != state.tick + 24:
                raise ValueError("lease answer deadline must be 24 ticks")
            if state.inventories[record.lessor_id].get(record.item_id, 0) < record.quantity:
                raise ValueError("lessor must personally hold leased goods")
            current = {e.data["lease"]["lease_id"]: e.data["lease"] for e in events
                       if e.event_type.value == "lease_updated"}
            if any(r["lessor_id"] == record.lessor_id and r["lessee_id"] == record.lessee_id
                   and r["item_id"] == record.item_id and r["status"] in {"proposed", "accepted", "overdue"}
                   for r in current.values()):
                raise ValueError("equivalent lease already outstanding")
            verb, target = "lease", record.lessee_id
        else:
            old = previous.data["lease"]
            if record.status not in {
                "proposed": {"accepted", "rejected", "expired"},
                "accepted": {"returned", "overdue"}, "overdue": {"returned"},
            }.get(old["status"], set()):
                raise ValueError("invalid lease transition")
            if any(value != old[key] for key, value in asdict(record).items()
                   if key not in {"status", "source_refs", "due_tick"}):
                raise ValueError("lease terms cannot change")
            expected_due = state.tick + record.duration_ticks if record.status == "accepted" else old["due_tick"]
            if record.due_tick != expected_due or f"event:{previous.sequence}" not in record.source_refs:
                raise ValueError("lease due time or prior source cannot change")
            verb, target = record.status, record.lease_id
            if record.status in {"accepted", "rejected", "returned"}:
                if system or event.actor_id != record.lessee_id:
                    raise ValueError("lessee alone accepts, rejects or returns")
                if record.status in {"accepted", "rejected"} and state.tick > record.answer_deadline_tick:
                    raise ValueError("lease answer deadline elapsed")
                if record.status == "returned" and old["status"] == "accepted" and state.tick > record.due_tick:
                    raise ValueError("late return must follow an overdue record")
                verb = {"accepted": "accept", "rejected": "reject", "returned": "return_lease"}[record.status]
            elif (not system or event.actor_id != record.lessor_id
                  or state.tick <= (record.answer_deadline_tick if record.status == "expired" else record.due_tick)):
                raise ValueError("expiry requires elapsed deadline")
        if not system and any(not state.characters[p].active
                              or state.characters[p].location_id != state.characters[parties[0]].location_id
                              for p in parties):
            raise ValueError("lease decisions require active local parties")
        inventory = lease_inventory_delta(record)
        if any(q.amount < 0 and state.inventories[q.owner_id].get(q.item_id, 0) < -q.amount for q in inventory):
            raise ValueError("lease cannot transfer missing goods")
        if event.delta != Delta(inventories=inventory, actions=() if system else (
            ActionRecord(event.actor_id, verb, target, state.tick),
        )) or event.target_entity_id != record.item_id:
            raise ValueError("lease delta must exactly match temporary possession terms")
        if event.observers != tuple(sorted(p for p in parties if state.characters[p].active)):
            raise ValueError("lease is private to its parties")
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:
        raise EventValidationError("invalid material lease: " + str(exc)) from exc
