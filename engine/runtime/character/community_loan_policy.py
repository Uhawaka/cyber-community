"""Personal debt choices use owned needs and inventory, never another person's plans."""

from engine.contracts.community import ActionVerb
from engine.runtime.character.community_exchange_choices import resource_reserves


def choose_loan(policy, context):
    visible = {e.entity_id for e in context.perception.entities if e.kind == "character"}
    stock = dict(context.inventory)
    reserves = resource_reserves(context)
    for loan in sorted(context.loans, key=lambda r: (r.deadline_tick, r.loan_id)):
        if loan.borrower_id != context.actor_id or loan.lender_id not in visible:
            continue
        if loan.status == "proposed":
            wanted = reserves.get(loan.item_id, 0)
            if loan.item_id in context.stocking_interests:
                wanted = max(wanted, 1)
            request = next((
                request for request in context.requests
                if request.status == "open" and request.requester_id == context.actor_id
                and request.helper_id == loan.lender_id and request.item_id == loan.item_id
                and context.perception.tick <= request.deadline_tick
            ), None)
            consent = (
                dict(context.relationships).get(loan.lender_id, 0) > -20
                and (wanted > stock.get(loan.item_id, 0) or request is not None)
                and loan.repayment_quantity <= loan.quantity
                and loan.deadline_tick - context.perception.tick >= 3
            )
            return policy.action(
                context, ActionVerb.ACCEPT if consent else ActionVerb.REJECT, loan.loan_id,
                "borrow material for my own needs on acceptable terms" if consent else
                "decline debt I do not need or cannot accept",
                sources=tuple(dict.fromkeys(
                    (*loan.source_refs, *(request.source_refs if consent and request else ()))
                )),
            )
        if loan.status in {"accepted", "overdue"}:
            own_needs = max(0, reserves.get(loan.item_id, 0) - loan.repayment_quantity)
            if loan.item_id in context.stocking_interests:
                own_needs = max(own_needs, 1)
            if stock.get(loan.item_id, 0) - own_needs >= loan.repayment_quantity:
                return policy.action(context, ActionVerb.REPAY, loan.loan_id,
                                     "repay my agreed material debt using available surplus",
                                     sources=loan.source_refs)
    return None
