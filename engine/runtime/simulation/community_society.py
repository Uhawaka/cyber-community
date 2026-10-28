"""Offers, consent and timed obligations with atomic bilateral settlement."""

from __future__ import annotations

from dataclasses import asdict, replace

from engine.contracts.community import ActionVerb, Commitment
from engine.contracts.society import ExchangeOffer
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType, QuantityDelta
from engine.runtime.simulation.community_events import commit, present


def exchange_delta(offer):
    quantities = [
        QuantityDelta(offer.sender_id, offer.item_id, -offer.quantity),
        QuantityDelta(offer.recipient_id, offer.item_id, offer.quantity),
    ]
    if offer.requested_quantity:
        quantities += [
            QuantityDelta(offer.recipient_id, offer.requested_item_id, -offer.requested_quantity),
            QuantityDelta(offer.sender_id, offer.requested_item_id, offer.requested_quantity),
        ]
    return tuple(quantities)


def write_offer(run, offer, actor_id, *, action=None, system=False):
    place = run.state.characters[actor_id].location_id
    audience = present(run, place) if not system else tuple(sorted(
        party for party in (offer.sender_id, offer.recipient_id)
        if run.state.characters[party].active
    ))
    return commit(
        run, EventType.EXCHANGE_UPDATED, actor_id=actor_id, observers=audience,
        delta=Delta(
            inventories=exchange_delta(offer) if offer.status == "accepted" else (),
            actions=(action,) if action else (),
        ),
        data={"offer": asdict(offer), "summary": f"exchange {offer.offer_id}: {offer.status}",
              "system_update": system},
        sources=offer.source_refs, commit_id=f"exchange:{offer.offer_id}:{offer.status}",
        target_id=offer.item_id,
    )


def write_commitment(run, obligation, actor_id, *, action=None, system=False):
    parties = (obligation.promisor_id, obligation.beneficiary_id)
    status = "unanswered proposal expired" if system and obligation.status == "rejected" else obligation.status
    return commit(
        run, EventType.COMMITMENT_UPDATED, actor_id=actor_id,
        observers=tuple(sorted(p for p in parties if run.state.characters[p].active)),
        delta=Delta(actions=(action,)) if action else None,
        data={"commitment": asdict(obligation), "summary": f"{status}: {obligation.description}",
              "system_update": system},
        sources=obligation.source_refs,
        commit_id=f"commitment:{obligation.commitment_id}:{obligation.status}",
        target_id=obligation.target_id or obligation.beneficiary_id,
    )


def begin_social_action(run, proposal, context):
    projection = community_projection(run)
    action = ActionRecord(proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick)
    if proposal.verb in {ActionVerb.OFFER, ActionVerb.TRANSFER, ActionVerb.COMMIT}:
        people = {e.entity_id for e in context.perception.entities if e.kind == "character"}
        if proposal.target_id not in people:
            raise ValueError("proposal recipient must be active and locally reachable")
        if proposal.verb is ActionVerb.COMMIT:
            verb = proposal.reply_to or "speak"
            target = proposal.item_id or proposal.target_id
            if verb == "repair" and target not in {e.entity_id for e in context.perception.entities}:
                raise ValueError("promised repair must target a known local object")
            if any(c.promisor_id == proposal.actor_id and c.beneficiary_id == proposal.target_id
                   and c.action_verb == verb and c.target_id == target and c.status in {"proposed", "accepted"}
                   for c in projection.commitments.values()):
                raise ValueError("an equivalent commitment is already pending")
            obligation = Commitment(
                proposal.proposal_id, proposal.actor_id, proposal.target_id,
                proposal.intent, proposal.source_refs, run.state.tick + 24,
                target_id=target, action_verb=verb, quantity=proposal.quantity,
            )
            write_commitment(run, obligation, proposal.actor_id, action=action)
            return
        if run.state.inventories[proposal.actor_id].get(proposal.item_id, 0) < proposal.quantity:
            raise ValueError("offer requires personally held stock")
        if proposal.requested_item_id and proposal.requested_item_id not in run.state.resources:
            raise ValueError("requested item must be registered")
        if any(o.sender_id == proposal.actor_id and o.recipient_id == proposal.target_id
               and o.item_id == proposal.item_id and o.status == "proposed"
               for o in projection.offers.values()):
            raise ValueError("an equivalent offer is already pending")
        offer = ExchangeOffer(
            proposal.proposal_id, proposal.actor_id, proposal.target_id,
            proposal.item_id, proposal.quantity, proposal.source_refs,
            run.state.tick + 6, proposal.requested_item_id, proposal.requested_quantity,
        )
        write_offer(run, offer, proposal.actor_id, action=action)
        return
    offer = projection.offers.get(proposal.target_id)
    obligation = projection.commitments.get(proposal.target_id)
    if offer is not None:
        if offer.recipient_id != proposal.actor_id or offer.status != "proposed":
            raise ValueError("only recipient may answer a pending offer")
        if offer.deadline_tick < run.state.tick:
            raise ValueError("offer has expired")
        if run.state.characters[offer.sender_id].location_id != context.perception.location_id or not run.state.characters[offer.sender_id].active:
            raise ValueError("exchange requires both parties locally present")
        status = "accepted" if proposal.verb is ActionVerb.ACCEPT else "rejected"
        origin = next(e for e in reversed(run.events) if e.event_type is EventType.EXCHANGE_UPDATED
                      and e.data["offer"]["offer_id"] == offer.offer_id)
        updated = replace(offer, status=status, source_refs=tuple(dict.fromkeys(
            (*proposal.source_refs, f"event:{origin.sequence}"),
        )))
        if status == "accepted" and any(
            q.amount < 0 and run.state.inventories[q.owner_id].get(q.item_id, 0) < -q.amount
            for q in exchange_delta(updated)
        ):
            raise ValueError("exchange stock changed; submit a new offer")
        write_offer(run, updated, proposal.actor_id, action=action)
        return
    if obligation is not None:
        if obligation.beneficiary_id != proposal.actor_id or obligation.status != "proposed":
            raise ValueError("only beneficiary may accept a proposed commitment")
        if run.state.tick > obligation.deadline_tick:
            raise ValueError("commitment proposal expired")
        if run.state.characters[obligation.promisor_id].location_id != context.perception.location_id:
            raise ValueError("accepting commitment requires locally reachable promisor")
        origin = next(e for e in reversed(run.events) if e.event_type is EventType.COMMITMENT_UPDATED
                      and e.data["commitment"]["commitment_id"] == obligation.commitment_id)
        write_commitment(run, replace(
            obligation, status="accepted" if proposal.verb is ActionVerb.ACCEPT else "rejected",
            source_refs=tuple(dict.fromkeys((*proposal.source_refs, f"event:{origin.sequence}"))),
        ), proposal.actor_id, action=action)
        return
    raise ValueError("no pending owned offer or commitment")


def settle_society(run):
    from engine.runtime.simulation.community_handoffs import settle_handoffs
    from engine.runtime.simulation.community_loans import settle_loans
    settle_handoffs(run)
    settle_loans(run)
    from engine.runtime.simulation.community_leases import settle_leases
    settle_leases(run)
    projection = community_projection(run)
    for offer in projection.offers.pending():
        if offer.status == "proposed" and run.state.tick > offer.deadline_tick:
            origin = run.events[projection.social_origins[("offer", offer.offer_id, "proposed")]]
            write_offer(run, replace(offer, status="expired", source_refs=(f"event:{origin.sequence}",)),
                        offer.sender_id, system=True)
    for obligation in projection.commitments.pending():
        sequence = projection.social_origins.get(("commitment", obligation.commitment_id, "accepted"))
        accepted = run.events[sequence] if sequence is not None else None
        outcome = projection.outcomes.obligation(obligation, accepted.sequence, run.events) if accepted else None
        if outcome is not None:
            write_commitment(run, replace(
                obligation, status="fulfilled",
                source_refs=(f"event:{accepted.sequence}", f"event:{outcome.sequence}"),
            ), obligation.promisor_id, system=True)
        elif run.state.tick > obligation.deadline_tick:
            origin = accepted or run.events[
                projection.social_origins[("commitment", obligation.commitment_id, "proposed")]
            ]
            write_commitment(run, replace(
                obligation, status="breached" if accepted else "rejected",
                source_refs=(f"event:{origin.sequence}",),
            ), obligation.promisor_id, system=True)
