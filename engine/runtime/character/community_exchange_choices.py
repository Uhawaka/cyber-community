"""Private policy preferences, not inventory locks or mandatory consent."""

from __future__ import annotations

from collections import Counter

from engine.contracts.community import ActionVerb


def resource_reserves(context):
    repair_targets = {g.target_id for g in context.goals if g.action_verb == "repair"}
    accepted = [c for c in context.commitments
                if c.promisor_id == context.actor_id and c.status == "accepted"]
    repair_targets.update(c.target_id for c in accepted if c.action_verb == "repair")
    for target, _ in context.responsibilities:
        observations = [claim for claim in context.knowledge if claim.subject == target
                        and claim.predicate == "condition" and claim.channel == "observation"]
        if observations:
            latest = max(observations, key=lambda claim: (claim.acquired_tick, claim.claim_id))
            if latest.content.isdigit() and int(latest.content) < 80:
                repair_targets.add(target)
    reserved = Counter()
    repairs = {o.target_id: o for o in (*context.known_repair_costs, *context.operations)
               if o.verb is ActionVerb.REPAIR}
    for operation in repairs.values():
        if operation.target_id in repair_targets:
            reserved.update(dict(operation.inputs))
    for commitment in accepted:
        if commitment.action_verb == "transfer":
            reserved[commitment.target_id] += commitment.quantity
    for offer in context.offers:
        if offer.sender_id == context.actor_id and offer.status == "proposed":
            reserved[offer.item_id] += offer.quantity
    for loan in context.loans:
        if loan.borrower_id == context.actor_id and loan.status in {"accepted", "overdue"}:
            reserved[loan.item_id] += loan.repayment_quantity
    if dict(context.needs).get("resources", 0) >= 30:
        for operation in context.operations:
            if operation.verb is ActionVerb.USE and dict(operation.use_effects).get("resources", 0) < 0:
                reserved[operation.target_id] += 1
    return reserved


def exchange_preference(context, supplied_item):
    stock = dict(context.inventory)
    reserved = resource_reserves(context)
    for item, amount in sorted(reserved.items()):
        shortage = amount - stock.get(item, 0)
        if item != supplied_item and 0 < shortage <= 100:
            return item, shortage
    for item in context.stocking_interests:
        if item != supplied_item and not stock.get(item, 0):
            return item, 1
    return "", 0
