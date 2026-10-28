"""Temporary possession is chosen from personal needs, not another actor's plans."""

from engine.contracts.community import ActionVerb
from engine.runtime.character.community_exchange_choices import resource_reserves


def choose_lease(policy, context):
    visible = {e.entity_id for e in context.perception.entities if e.kind == "character"}
    inventory = dict(context.inventory)
    reserves = resource_reserves(context)
    for lease in sorted(context.leases, key=lambda r: (
        r.due_tick if r.due_tick is not None else r.answer_deadline_tick, r.lease_id,
    )):
        if lease.lessee_id != context.actor_id or lease.lessor_id not in visible:
            continue
        wanted = reserves.get(lease.item_id, 0)
        if lease.item_id in context.stocking_interests:
            wanted = max(wanted, 1)
        if lease.status == "proposed":
            consent = (lease.item_id in context.stocking_interests
                       and inventory.get(lease.item_id, 0) == 0
                       and dict(context.relationships).get(lease.lessor_id, 0) > -20)
            return policy.action(
                context, ActionVerb.ACCEPT if consent else ActionVerb.REJECT, lease.lease_id,
                "accept temporary use for my own material needs" if consent else
                "decline temporary possession I do not need or trust",
                sources=lease.source_refs,
            )
        if lease.status in {"accepted", "overdue"}:
            if inventory.get(lease.item_id, 0) < lease.quantity:
                continue
            if wanted == 0 or context.perception.tick >= lease.due_tick:
                return policy.action(
                    context, ActionVerb.RETURN_LEASE, lease.lease_id,
                    "return goods I no longer need or whose agreed use term has ended",
                    sources=lease.source_refs,
                )
    return None
