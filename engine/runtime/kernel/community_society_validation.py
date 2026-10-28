"""Consent, custody and lifecycle invariants for society events."""

from __future__ import annotations

from engine.contracts.community import Commitment
from engine.contracts.society import ExchangeOffer
from engine.runtime.kernel.community_obligation_outcomes import obligation_outcome_matches


def validate_society_event(event, events, state):
    from engine.runtime.kernel.events import EventValidationError
    from engine.runtime.simulation.community_society import exchange_delta

    exchange = event.event_type.value == "exchange_updated"
    key, cls, id_field = ("offer", ExchangeOffer, "offer_id") if exchange else ("commitment", Commitment, "commitment_id")
    try:
        raw = event.data[key]
        record = cls(**{**raw, "source_refs": tuple(raw["source_refs"])})
        if not set(record.source_refs) <= set(event.data["source_refs"]):
            raise ValueError("society record sources must match event")
        sender = record.sender_id if exchange else record.promisor_id
        recipient = record.recipient_id if exchange else record.beneficiary_id
        if sender not in state.characters or recipient not in state.characters:
            raise ValueError("society parties must exist")
        previous_event = next((
            e for e in reversed(events) if e.event_type == event.event_type
            and e.data[key][id_field] == getattr(record, id_field)
        ), None)
        if previous_event is None:
            if record.status != "proposed" or event.actor_id != sender or record.deadline_tick <= state.tick:
                raise ValueError("only sender may propose a future bilateral obligation")
            if not all(state.characters[p].active for p in (sender, recipient)):
                raise ValueError("proposal parties must be active")
            if state.characters[sender].location_id != state.characters[recipient].location_id:
                raise ValueError("proposal requires local reach")
            if exchange and state.inventories[sender].get(record.item_id, 0) < record.quantity:
                raise ValueError("proposal requires held stock")
            if not exchange:
                commitments = {e.data[key][id_field]: e.data[key] for e in events if e.event_type == event.event_type}
                if any(c["promisor_id"] == sender and c["beneficiary_id"] == recipient
                       and c["target_id"] == record.target_id and c["action_verb"] == record.action_verb
                       and c["status"] in {"proposed", "accepted"} for c in commitments.values()):
                    raise ValueError("an equivalent commitment is already pending")
        else:
            previous = previous_event.data[key]
            mutable = {"status", "source_refs"}
            if any(value != previous.get(field) for field, value in raw.items() if field not in mutable):
                raise ValueError("society terms cannot change after proposal")
            old, new = previous["status"], record.status
            allowed = (
                {"proposed": {"accepted", "rejected", "expired"}}
                if exchange else
                {"proposed": {"accepted", "rejected"}, "accepted": {"fulfilled", "breached"}}
            )
            if new not in allowed.get(old, set()):
                raise ValueError("invalid or repeated society transition")
            if new == "accepted" or new == "rejected" and not event.data.get("system_update"):
                if event.actor_id != recipient:
                    raise ValueError("only recipient may consent or reject")
                if state.tick > record.deadline_tick:
                    raise ValueError("consent deadline has passed")
                if not all(state.characters[p].active for p in (sender, recipient)):
                    raise ValueError("consent requires active parties")
                if state.characters[sender].location_id != state.characters[recipient].location_id:
                    raise ValueError("consent requires local reach")
            if new in {"expired", "breached"} or new == "rejected" and event.data.get("system_update"):
                if state.tick <= record.deadline_tick or event.actor_id != sender or not event.data.get("system_update"):
                    raise ValueError("expiry or breach requires elapsed deadline")
            if new == "fulfilled":
                if event.actor_id != sender:
                    raise ValueError("fulfillment must belong to promisor")
                evidence = [
                    e for e in events[previous_event.sequence + 1:]
                    if f"event:{e.sequence}" in record.source_refs
                    and e.tick <= record.deadline_tick
                ]
                if not any(obligation_outcome_matches(record, origin, events) for origin in evidence):
                    raise ValueError("fulfillment requires a matching committed outcome")
        if exchange:
            expected = exchange_delta(record) if record.status == "accepted" else ()
            if event.delta.inventories != expected:
                raise ValueError("exchange delta must exactly match accepted terms")
            if record.status == "accepted" and any(
                q.amount < 0 and state.inventories[q.owner_id].get(q.item_id, 0) < -q.amount
                for q in expected
            ):
                raise ValueError("exchange cannot spend unavailable stock")
        elif event.delta.inventories:
            raise ValueError("promise cannot transfer inventory")
        if event.delta.resources or event.delta.entity_patches or event.delta.knowledge:
            raise ValueError("society event cannot invent external facts or resources")
        if exchange and not event.data.get("system_update"):
            expected_audience = tuple(sorted(
                person for person, actor in state.characters.items()
                if actor.active and actor.location_id == state.characters[event.actor_id].location_id
            ))
        else:
            expected_audience = tuple(sorted(
                person for person in (sender, recipient) if state.characters[person].active
            ))
        if event.observers != expected_audience:
            raise ValueError("society audience must match actual reach or agreed parties")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid society transition: " + str(exc)) from exc
