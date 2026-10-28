"""Requests cannot imply consent, change inventory, or invent fulfillment."""

from engine.contracts.society import MaterialRequest


def matches_request_delivery(request, event):
    if event.event_type.value == "exchange_updated":
        record = event.data["offer"]
        sender, recipient = record["sender_id"], record["recipient_id"]
    elif event.event_type.value == "loan_updated":
        record = event.data["loan"]
        sender, recipient = record["lender_id"], record["borrower_id"]
    else:
        return False
    return (
        record["status"] == "accepted"
        and sender == request.helper_id and recipient == request.requester_id
        and record["item_id"] == request.item_id and record["quantity"] >= request.quantity
    )


def validate_request(event, events, state, community=None):
    from engine.runtime.kernel.events import EventValidationError
    try:
        raw = event.data["request"]
        record = MaterialRequest(**{**raw, "source_refs": tuple(raw["source_refs"])})
        if not set(record.source_refs) <= set(event.data["source_refs"]):
            raise ValueError("request sources must match event")
        if any(p not in state.characters for p in (record.requester_id, record.helper_id)):
            raise ValueError("request parties must exist")
        if record.item_id not in state.resources or record.purpose_id not in state.entities:
            raise ValueError("request references must exist")
        recipe = next((r for r in community.repairs if r.target_id == record.purpose_id), None) if community else None
        if recipe is None or record.quantity > dict(recipe.inputs).get(record.item_id, 0):
            raise ValueError("request must match an authoritative repair input")
        prior = next((e for e in reversed(events) if e.event_type == event.event_type
                      and e.data["request"]["request_id"] == record.request_id), None)
        if prior is None:
            if record.status != "open" or event.actor_id != record.requester_id or record.deadline_tick <= state.tick:
                raise ValueError("only requester may open a future request")
            if any(not state.characters[p].active for p in (record.requester_id, record.helper_id)):
                raise ValueError("request parties must be active")
            if state.characters[record.requester_id].location_id != state.characters[record.helper_id].location_id:
                raise ValueError("request requires local reach")
            if state.entities[record.purpose_id].components["attributes"]["location_id"] != state.characters[record.requester_id].location_id:
                raise ValueError("repair request must be local to its known purpose")
        else:
            old = prior.data["request"]
            if old["status"] != "open" or record.status == "open" or any(
                raw[key] != old[key] for key in raw if key not in {"status", "source_refs"}
            ):
                raise ValueError("request terms cannot change or reopen")
            if record.status == "declined":
                if event.actor_id != record.helper_id or event.data.get("system_update"):
                    raise ValueError("only helper may decline")
                if state.tick > record.deadline_tick or any(
                    not state.characters[p].active for p in (record.requester_id, record.helper_id)
                ) or state.characters[record.requester_id].location_id != state.characters[record.helper_id].location_id:
                    raise ValueError("declining requires timely local reach")
            else:
                if event.actor_id != record.requester_id or not event.data.get("system_update"):
                    raise ValueError("request settlement requires requester and actual evidence")
                if record.status == "expired" and state.tick <= record.deadline_tick:
                    raise ValueError("request deadline has not passed")
                if record.status == "fulfilled" and not any(
                    e.sequence > prior.sequence and e.tick <= record.deadline_tick
                    and f"event:{e.sequence}" in record.source_refs
                    and matches_request_delivery(record, e) for e in events
                ):
                    raise ValueError("request fulfillment requires an actual consented delivery")
        if any((event.delta.resources, event.delta.inventories, event.delta.entity_patches,
                event.delta.knowledge, event.delta.needs, event.delta.moves,
                event.delta.advance_tick, event.delta.advance_time)):
            raise ValueError("request cannot alter physical facts")
        expected = tuple(sorted(p for p in (record.requester_id, record.helper_id)
                                if state.characters[p].active))
        if event.observers != expected:
            raise ValueError("request is private to its parties")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid material request: " + str(exc)) from exc
