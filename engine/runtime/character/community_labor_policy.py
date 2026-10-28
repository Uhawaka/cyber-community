"""Voluntary labor proposals bounded by the actor's own knowledge and means."""

from __future__ import annotations

from engine.contracts.community import ActionVerb
from engine.runtime.character.community_exchange_choices import resource_reserves


def propose_labor(policy, context, target, description, quantity, sources):
    needs = dict(context.needs)
    if needs.get("resources", 0) >= 60:
        return None
    if any(c.promisor_id == context.actor_id and c.status in {"proposed", "accepted"}
           for c in context.commitments):
        return None
    if any(c.action_verb == "repair" and c.target_id == target and c.status == "accepted"
           for c in context.commitments):
        return None
    operation = next((o for o in context.operations
                      if o.verb is ActionVerb.REPAIR and o.target_id == target), None)
    observation = policy.observation(context, target)
    if (operation is None or operation.reserved or observation is None or not observation.content.isdigit()
            or not 0 < quantity <= operation.restored_condition
            or int(observation.content) >= quantity
            or context.perception.tick - observation.acquired_tick >= 12
            or operation.duration_ticks + 4 > 24
            or needs.get("fatigue", 0) + 4 + operation.duration_ticks >= 60):
        return None
    reserved = resource_reserves(context)
    own_plan = any(g.action_verb == "repair" and g.target_id == target for g in context.goals)
    held, shared = dict(context.inventory), dict(operation.material_stock)
    if any(held.get(item, 0) + shared.get(item, 0) <
           amount + max(0, reserved.get(item, 0) - (amount if own_plan else 0))
           for item, amount in operation.inputs):
        return None
    people = [e.entity_id for e in context.perception.entities if e.kind == "character"]
    trust = dict(context.relationships)
    for beneficiary in sorted(people, key=lambda p: (-trust.get(p, 0), p)):
        if trust.get(beneficiary, 0) <= -20:
            continue
        if any(c.promisor_id == context.actor_id and c.beneficiary_id == beneficiary
               and c.action_verb == "repair" and c.target_id == target
               and c.status in {"rejected", "breached"}
               and context.perception.tick <= c.deadline_tick + (12 if c.status == "breached" else 0)
               for c in context.commitment_history):
            continue
        return policy.action(context, ActionVerb.COMMIT, beneficiary, description,
                             item_id=target, reply_to="repair", quantity=quantity,
                             sources=tuple(dict.fromkeys((*sources, *observation.source_refs))))
    return None
