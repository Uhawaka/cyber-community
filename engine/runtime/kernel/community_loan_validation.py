"""Material debt requires consent; overdue obligations never authorize seizure."""

from dataclasses import asdict

from engine.contracts.society import MaterialLoan


def loan_inventory_delta(record):
    from engine.runtime.kernel.events import QuantityDelta
    if record.status == "accepted":
        sender, recipient, amount = record.lender_id, record.borrower_id, record.quantity
    elif record.status == "repaid":
        sender, recipient, amount = record.borrower_id, record.lender_id, record.repayment_quantity
    else:
        return ()
    return (QuantityDelta(sender, record.item_id, -amount), QuantityDelta(recipient, record.item_id, amount))


def validate_loan(event, events, state):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
    try:
        raw = event.data["loan"]
        record = MaterialLoan(**{**raw, "source_refs": tuple(raw["source_refs"])})
        parties = (record.lender_id, record.borrower_id)
        if any(p not in state.characters for p in parties) or record.item_id not in state.resources:
            raise ValueError("loan requires existing parties and registered material")
        if not set(record.source_refs) <= set(event.data["source_refs"]):
            raise ValueError("loan sources must match event")
        previous = next((e for e in reversed(events) if e.event_type.value == "loan_updated"
                         and e.data["loan"]["loan_id"] == record.loan_id), None)
        system = event.data.get("system_update", False)
        if not isinstance(system, bool):
            raise ValueError("loan system flag must be boolean")
        if previous is None:
            if record.status != "proposed" or system or event.actor_id != record.lender_id:
                raise ValueError("only lender may propose a new loan")
            if record.deadline_tick != state.tick + 24:
                raise ValueError("loan deadline must be 24 ticks after proposal")
            verb, target = "lend", record.borrower_id
            if state.inventories[record.lender_id].get(record.item_id, 0) < record.quantity:
                raise ValueError("loan requires personally held principal")
            current = {e.data["loan"]["loan_id"]: e.data["loan"] for e in events
                       if e.event_type.value == "loan_updated"}
            if any(r["lender_id"] == record.lender_id and r["borrower_id"] == record.borrower_id
                   and r["item_id"] == record.item_id and r["status"] in {"proposed", "accepted", "overdue"}
                   for r in current.values()):
                raise ValueError("equivalent loan is already outstanding")
        else:
            old = previous.data["loan"]
            if any(value != old[field] for field, value in asdict(record).items()
                   if field not in {"status", "source_refs"}):
                raise ValueError("loan terms cannot change")
            if record.status not in {
                "proposed": {"accepted", "rejected", "expired"},
                "accepted": {"overdue", "repaid"}, "overdue": {"repaid"},
            }.get(old["status"], set()):
                raise ValueError("invalid or repeated loan transition")
            if f"event:{previous.sequence}" not in record.source_refs:
                raise ValueError("loan transition requires its previous event")
            verb, target = record.status, record.loan_id
            if record.status in {"accepted", "rejected", "repaid"}:
                if system or event.actor_id != record.borrower_id:
                    raise ValueError("only borrower may independently answer or repay")
                if record.status in {"accepted", "rejected"} and state.tick > record.deadline_tick:
                    raise ValueError("loan consent deadline has passed")
                if record.status == "repaid" and old["status"] == "accepted" and state.tick > record.deadline_tick:
                    raise ValueError("overdue must be recorded before late repayment")
                verb = {"accepted": "accept", "rejected": "reject", "repaid": "repay"}[record.status]
            elif not system or event.actor_id != record.lender_id or state.tick <= record.deadline_tick:
                raise ValueError("expiry or overdue requires elapsed deadline")
        if not system and (not all(state.characters[p].active for p in parties)
                           or state.characters[parties[0]].location_id != state.characters[parties[1]].location_id):
            raise ValueError("loan decisions require active local parties")
        inventory = loan_inventory_delta(record)
        expected = Delta(inventories=inventory, actions=() if system else (
            ActionRecord(event.actor_id, verb, target, state.tick),
        ))
        if event.delta != expected or event.target_entity_id != record.item_id:
            raise ValueError("loan delta must exactly match consented material terms")
        if any(q.amount < 0 and state.inventories[q.owner_id].get(q.item_id, 0) < -q.amount for q in inventory):
            raise ValueError("loan cannot spend unavailable personal stock")
        if event.observers != tuple(sorted(p for p in parties if state.characters[p].active)):
            raise ValueError("loan is private to its actual parties")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid material loan: " + str(exc)) from exc
