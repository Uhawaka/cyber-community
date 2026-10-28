"""Deterministic policy for mechanism probes, not a literary-quality model."""

from __future__ import annotations

from collections import deque

from engine.contracts.community import ActionProposal, ActionVerb
from engine.runtime.character.community_exchange_choices import exchange_preference, resource_reserves
from engine.runtime.character.community_labor_policy import propose_labor
from engine.runtime.character.community_handoff_policy import choose_handoff
from engine.runtime.character.community_loan_policy import choose_loan
from engine.runtime.character.community_lease_policy import choose_lease
from engine.runtime.character.community_membership_policy import choose_invitation, choose_join
from engine.runtime.character.community_role_policy import choose_censure, choose_role


class CommunityLifePolicy:
    version = "community-life-policy/v31"

    def propose(self, context):
        fatigue = dict(context.needs).get("fatigue", 0)
        if fatigue >= 60:
            return self.action(context, ActionVerb.REST, context.actor_id, "recover energy")
        handoff = choose_handoff(self, context)
        if handoff:
            return handoff
        loan = choose_loan(self, context)
        if loan:
            return loan
        lease = choose_lease(self, context)
        if lease:
            return lease
        office = choose_role(self, context)
        if office:
            return office
        judgment = choose_censure(self, context)
        if judgment:
            return judgment
        visible = {e.entity_id for e in context.perception.entities}
        for offer in sorted(context.offers, key=lambda o: (o.deadline_tick, o.offer_id)):
            if offer.recipient_id != context.actor_id or offer.sender_id not in visible:
                continue
            trust = dict(context.relationships).get(offer.sender_id, 0)
            stock = dict(context.inventory).get(offer.requested_item_id, 0)
            reserve = resource_reserves(context).get(offer.requested_item_id, 0)
            consent = trust > -20 and (not offer.requested_quantity or
                                      stock - reserve >= offer.requested_quantity)
            return self.action(
                context, ActionVerb.ACCEPT if consent else ActionVerb.REJECT, offer.offer_id,
                "accept terms using my surplus" if consent else "decline terms beyond my surplus or trust",
                sources=offer.source_refs,
            )
        for obligation in sorted(context.commitments, key=lambda c: (c.deadline_tick, c.commitment_id)):
            if obligation.status == "proposed" and obligation.beneficiary_id == context.actor_id and obligation.promisor_id in visible:
                consent = dict(context.relationships).get(obligation.promisor_id, 0) > -20
                if consent and obligation.action_verb == "repair":
                    observation = self.observation(context, obligation.target_id)
                    inspect = any(o.verb is ActionVerb.INSPECT and o.target_id == obligation.target_id
                                  for o in context.operations)
                    if inspect and (observation is None or context.perception.tick - observation.acquired_tick >= 12):
                        return self.action(context, ActionVerb.INSPECT, obligation.target_id,
                                           "check whether the proposed labor is still useful",
                                           sources=obligation.source_refs)
                    consent = (observation is not None and observation.content.isdigit()
                               and int(observation.content) < obligation.quantity)
                return self.action(context, ActionVerb.ACCEPT if consent else ActionVerb.REJECT,
                                   obligation.commitment_id, "accept useful labor" if consent else
                                   "decline labor I cannot use or trust",
                                   sources=obligation.source_refs)
            if obligation.status != "accepted" or obligation.promisor_id != context.actor_id:
                continue
            if obligation.action_verb == "transfer" and obligation.beneficiary_id in visible:
                if dict(context.inventory).get(obligation.target_id, 0) >= obligation.quantity:
                    return self.action(context, ActionVerb.OFFER, obligation.beneficiary_id,
                                       obligation.description, item_id=obligation.target_id,
                                       quantity=obligation.quantity, sources=obligation.source_refs)
            elif obligation.action_verb == "speak" and obligation.beneficiary_id in visible:
                return self.action(context, ActionVerb.SPEAK, obligation.beneficiary_id,
                                   obligation.description, speech=obligation.description,
                                   sources=obligation.source_refs)
            elif obligation.action_verb == "repair" and obligation.target_id in visible:
                result = self.new_goal(context, "repair", obligation.target_id,
                                       obligation.description, obligation.quantity,
                                       sources=obligation.source_refs)
                if result:
                    return result
        if any(c.promisor_id == context.actor_id and c.status == "proposed"
               and c.action_verb == "repair" and c.beneficiary_id in visible
               and context.perception.tick <= c.deadline_tick - 22 for c in context.commitments):
            return self.action(context, ActionVerb.WAIT, context.actor_id,
                               "await an independent answer to my labor proposal")
        result = self.answer_requests(context, visible)
        if result:
            return result
        for plan in sorted(context.intent_plans, key=lambda value: value.plan_id):
            if plan.status != "ready" or (plan.goal_id and not any(
                goal.goal_id == plan.goal_id for goal in context.goals
            )):
                continue
            step = plan.steps[plan.cursor]
            return self.action(
                context, ActionVerb(step.verb), step.target_id, plan.description,
                quantity=step.quantity, item_id=step.item_id, speech=step.speech,
                intent_plan_id=plan.plan_id, intent_step_index=plan.cursor,
            )
        eligible = {p.goal_id: p for p in context.plans if p.next_attempt_tick <= context.perception.tick}
        goals = sorted((g for g in context.goals if g.goal_id in eligible and g.action_verb != "wait"),
                       key=lambda g: (-g.priority, g.goal_id))
        for goal in goals:
            if goal.target_id not in visible | set(context.perception.known_routes):
                continue
            verb = ActionVerb(goal.action_verb)
            if verb is ActionVerb.REPAIR and not self.observation(context, goal.target_id):
                return self.action(context, ActionVerb.INSPECT, goal.target_id,
                                   "inspect before choosing a repair", sources=eligible[goal.goal_id].source_refs)
            if verb is ActionVerb.REPAIR:
                operation = next((o for o in context.operations if o.verb is verb and o.target_id == goal.target_id), None)
                if operation:
                    shortages = [(item, amount - dict(context.inventory).get(item, 0)
                                  - dict(operation.material_stock).get(item, 0))
                                 for item, amount in operation.inputs]
                    shortages = [(item, amount) for item, amount in shortages if amount > 0]
                    if shortages:
                        result = self.ask_for_material(context, goal.target_id, goal.description,
                                                       shortages[0], eligible[goal.goal_id].source_refs)
                        if result:
                            return result
                        continue
                    observation = self.observation(context, goal.target_id)
                    if context.perception.tick - observation.acquired_tick >= 12:
                        return self.action(context, ActionVerb.INSPECT, goal.target_id,
                                           "refresh my observation before committing labor",
                                           sources=eligible[goal.goal_id].source_refs)
                    result = propose_labor(self, context, goal.target_id, goal.description,
                                           goal.quantity, eligible[goal.goal_id].source_refs)
                    if result:
                        return result
            quantity = goal.quantity
            if verb is ActionVerb.TAKE:
                quantity -= dict(context.inventory).get(goal.target_id, 0)
            if quantity > 0:
                return self.action(context, verb, goal.target_id, goal.description,
                                   quantity=quantity, sources=eligible[goal.goal_id].source_refs,
                                   speech=goal.description if verb is ActionVerb.SPEAK else "")
        result = self.daily_life(context)
        if result:
            return result
        return self.action(context, ActionVerb.WAIT, context.actor_id, "available for new information")

    def action(self, context, verb, target, intent, *, sources=None, **options):
        source = f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}"
        return ActionProposal(
            f"decision:{context.actor_id}:{context.perception.tick}",
            context.actor_id, verb, target, intent, sources or (source,), context.state_hash,
            **options,
        )

    def new_goal(self, context, verb, target, description, quantity=1, *, sources=None):
        if any(g.target_id == target and g.action_verb == verb for g in context.goals):
            return None
        return self.action(context, ActionVerb.PURSUE, target, description,
                           item_id=verb, quantity=quantity, sources=sources)

    def ask_for_material(self, context, target, description, shortage, sources):
        item, amount = shortage
        related = [r for r in context.requests if r.requester_id == context.actor_id
                   and r.item_id == item and r.purpose_id == target]
        if any(r.status == "open" for r in related):
            return None
        people = [e.entity_id for e in context.perception.entities if e.kind == "character"]
        for helper in sorted(people, key=lambda p: (-dict(context.relationships).get(p, 0), p)):
            if any(r.helper_id == helper and context.perception.tick < r.deadline_tick - 12
                   for r in related):
                continue
            return self.action(context, ActionVerb.REQUEST, helper,
                               f"ask for {item} to continue {description}",
                               item_id=item, quantity=amount, reply_to=target,
                               sources=sources)
        return None

    def answer_requests(self, context, visible):
        for request in context.requests:
            if request.status != "open" or request.helper_id != context.actor_id or request.requester_id not in visible:
                continue
            if any(o.sender_id == context.actor_id and o.recipient_id == request.requester_id
                   and o.item_id == request.item_id for o in context.offers):
                continue
            outstanding = any(
                loan.lender_id == context.actor_id and loan.borrower_id == request.requester_id
                and loan.item_id == request.item_id and loan.status in {"proposed", "accepted", "overdue"}
                for loan in context.loans
            )
            if request.request_id in context.loaned_requests:
                if outstanding:
                    continue
                return self.action(context, ActionVerb.REJECT, request.request_id,
                                   "decline a request after my loan was not accepted",
                                   sources=request.source_refs)
            reserve = resource_reserves(context).get(request.item_id, 0)
            available = dict(context.inventory).get(request.item_id, 0) - reserve
            if dict(context.relationships).get(request.requester_id, 0) > -20:
                if available >= request.quantity:
                    trust_source = dict(context.trust_sources).get(request.requester_id)
                    trust = dict(context.relationships).get(request.requester_id, 0)
                    overdue = any(
                        loan.lender_id == context.actor_id and loan.borrower_id == request.requester_id
                        and loan.status == "overdue" for loan in context.loans
                    )
                    if (request.item_id in context.stocking_interests and trust >= 0
                            and (trust == 0 or trust_source) and not overdue):
                        if outstanding:
                            return self.action(context, ActionVerb.REJECT, request.request_id,
                                               "decline a request while an equivalent loan remains open",
                                               sources=request.source_refs)
                        return self.action(
                            context, ActionVerb.LEND, request.requester_id,
                            "lend requested surplus I want to replenish",
                            item_id=request.item_id, quantity=request.quantity,
                            sources=tuple(dict.fromkeys(
                                (*request.source_refs, *((trust_source,) if trust_source else ()))
                            )),
                        )
                    desired_item, desired_quantity = exchange_preference(context, request.item_id)
                    return self.action(context, ActionVerb.OFFER, request.requester_id,
                                       "exchange surplus for my own needs" if desired_item else
                                       "offer surplus in response to a personal request",
                                       item_id=request.item_id, quantity=request.quantity,
                                       requested_item_id=desired_item, requested_quantity=desired_quantity,
                                       sources=request.source_refs)
                take = next((o for o in context.operations if o.verb is ActionVerb.TAKE
                             and o.target_id == request.item_id
                             and o.available_quantity >= request.quantity - available), None)
                if take and request.quantity - available <= 100:
                    return self.action(context, ActionVerb.TAKE, request.item_id,
                                       "collect available materials for a voluntary delivery",
                                       quantity=request.quantity - available, sources=request.source_refs)
            return self.action(context, ActionVerb.REJECT, request.request_id,
                               "decline help beyond my resources or trust", sources=request.source_refs)
        return None

    @staticmethod
    def observation(context, target):
        claims = [c for c in context.knowledge if c.subject == target
                  and c.predicate == "condition" and c.channel == "observation"]
        return max(claims, key=lambda c: (c.acquired_tick, c.claim_id)) if claims else None

    def travel(self, context, destination, reason):
        origin = context.perception.location_id
        queue, seen = deque([(origin, None)]), {origin}
        while queue:
            place, first = queue.popleft()
            if place == destination:
                if first in context.perception.known_routes:
                    return self.action(context, ActionVerb.MOVE, first, reason)
                return None
            for route, start, end in context.known_map:
                if start == place and end not in seen:
                    seen.add(end)
                    queue.append((end, first or route))
        return None

    def daily_life(self, context):
        needs = dict(context.needs)
        if needs.get("resources", 0) >= 30:
            for operation in context.operations:
                if operation.verb is ActionVerb.USE and operation.available_quantity > 0:
                    if dict(operation.use_effects).get("resources", 0) < 0:
                        return self.action(context, ActionVerb.USE, operation.target_id, "use held daily supplies",
                                           sources=(operation.source_ref,))
            consumables = {o.target_id for o in context.operations if o.verb is ActionVerb.USE}
            for operation in context.operations:
                if operation.verb is ActionVerb.TAKE and operation.target_id in consumables and operation.available_quantity > 0:
                    result = self.new_goal(context, "take", operation.target_id, "obtain daily supplies")
                    if result:
                        return result
            if needs.get("resources", 0) >= 60:
                for _, location in context.supply_places:
                    result = self.travel(context, location, "seek known daily supplies")
                    if result:
                        return result
        stock = dict(context.inventory)
        reserves = resource_reserves(context)
        for loan in sorted(context.loans, key=lambda value: (value.deadline_tick, value.loan_id)):
            if loan.borrower_id != context.actor_id or loan.status not in {"accepted", "overdue"}:
                continue
            own_needs = max(0, reserves.get(loan.item_id, 0) - loan.repayment_quantity)
            if loan.item_id in context.stocking_interests:
                own_needs = max(own_needs, 1)
            shortage = loan.repayment_quantity + own_needs - stock.get(loan.item_id, 0)
            take = next((op for op in context.operations if op.verb is ActionVerb.TAKE
                         and op.target_id == loan.item_id and op.available_quantity > 0), None)
            if shortage > 0 and take:
                return self.action(
                    context, ActionVerb.TAKE, loan.item_id, "obtain available material to repay my debt",
                    quantity=min(shortage, loan.repayment_quantity, take.available_quantity, 100),
                    sources=tuple(dict.fromkeys((*loan.source_refs, take.source_ref))),
                )
        hour = context.perception.tick % 24
        reading = self.read_local_record(context)
        if reading:
            return reading
        for item in context.stocking_interests:
            if dict(context.inventory).get(item, 0):
                continue
            take = next((o for o in context.operations if o.verb is ActionVerb.TAKE
                         and o.target_id == item and o.available_quantity > 0), None)
            if take:
                return self.action(context, ActionVerb.TAKE, item, "stock a personally chosen useful material",
                                   sources=(take.source_ref,))
            if 7 <= hour < 18:
                for resource_id, location in context.stocking_places:
                    if resource_id == item:
                        result = self.travel(context, location, "visit a known source of useful materials")
                        if result:
                            return result
        if 7 <= hour < 18:
            for operation in context.operations:
                if operation.verb is ActionVerb.LEARN and operation.learned_skill in context.learning_interests:
                    result = self.new_goal(context, "learn", operation.target_id, "learn a personally chosen skill")
                    if result:
                        return result
            for skill, _, location in context.learning_places:
                if skill not in context.skills:
                    result = self.travel(context, location, "visit a known learning place")
                    if result:
                        return result
            repairs = {o.target_id: o for o in context.operations if o.verb is ActionVerb.REPAIR}
            for target, location in context.responsibilities:
                responsibility_ref = dict(context.responsibility_sources).get(target)
                sources = (responsibility_ref,) if responsibility_ref else None
                if target in repairs:
                    observation = self.observation(context, target)
                    if observation is None or context.perception.tick - observation.acquired_tick >= 12:
                        return self.action(context, ActionVerb.INSPECT, target, "check a device in my care", sources=sources)
                    if observation.content.isdigit() and int(observation.content) < 80:
                        operation = repairs[target]
                        condition = min(80, operation.restored_condition)
                        result = propose_labor(self, context, target, "maintain a device in my care",
                                               condition, observation.source_refs)
                        if result:
                            return result
                        shortage = next(((item, amount - dict(context.inventory).get(item, 0)
                                          - dict(operation.material_stock).get(item, 0))
                                         for item, amount in operation.inputs if amount >
                                         dict(context.inventory).get(item, 0) + dict(operation.material_stock).get(item, 0)), None)
                        if shortage:
                            request = self.ask_for_material(context, target, "maintain a device in my care",
                                                            shortage, observation.source_refs)
                            if request:
                                return request
                        result = self.new_goal(context, "repair", target, "maintain a device in my care", condition, sources=sources)
                        if result:
                            return result
                elif location != context.perception.location_id:
                    result = self.travel(context, location, "visit my workplace responsibilities")
                    if result:
                        return result
        if needs.get("knowledge", 0) >= 30 and not any(
            c.promisor_id == context.actor_id and c.status == "accepted" for c in context.commitments
        ):
            for operation in context.operations:
                if operation.verb is not ActionVerb.RECORD:
                    continue
                for claim in context.capabilities:
                    if (claim.subject == context.actor_id and claim.owner_id == context.actor_id
                            and (operation.target_id, claim.claim_id) not in context.recorded_organization_claims):
                        return self.action(context, ActionVerb.RECORD, operation.target_id,
                                           "archive my own sourced capability without accepting work",
                                           item_id=claim.claim_id,
                                           sources=tuple(dict.fromkeys((*claim.source_refs, operation.source_ref))))
        membership = choose_join(self, context)
        if membership:
            return membership
        invitation = choose_invitation(self, context)
        if invitation:
            return invitation
        if needs.get("social", 0) >= 30:
            for organization, participants in context.organization_groups:
                for claim in context.capabilities:
                    signature = "|".join((claim.subject, claim.predicate, claim.content))
                    if (claim.subject == context.actor_id and claim.owner_id == context.actor_id
                            and claim.predicate[6:] in context.skills
                            and any((person, signature) not in context.reported_claims
                                    for person in participants if person != context.actor_id)):
                        return self.action(context, ActionVerb.SPEAK, organization,
                                           "share my own capability with present organization members",
                                           item_id=claim.claim_id, speech=f"I can {claim.predicate[6:]}.",
                                           sources=claim.source_refs)
            for entity in context.perception.entities:
                if entity.kind != "character":
                    continue
                for claim in context.capabilities:
                    signature = "|".join((claim.subject, claim.predicate, claim.content))
                    if (claim.subject == context.actor_id and claim.owner_id == context.actor_id
                            and claim.predicate[6:] in context.skills
                            and (entity.entity_id, signature) not in context.reported_claims):
                        return self.action(context, ActionVerb.SPEAK, entity.entity_id,
                                           "share my own capability without committing to work",
                                           item_id=claim.claim_id, speech=f"I can {claim.predicate[6:]}.",
                                           sources=claim.source_refs)
                for claim in reversed(context.knowledge):
                    signature = "|".join((claim.subject, claim.predicate, claim.content))
                    if claim.channel in {"observation", "learned"} and (entity.entity_id, signature) not in context.reported_claims:
                        return self.action(context, ActionVerb.SPEAK, entity.entity_id,
                                           "share a new personally observed result",
                                           item_id=claim.claim_id, speech=f"{claim.subject}: {claim.content}",
                                           sources=claim.source_refs)
        if context.routine_locations:
            destination = context.routine_locations[(hour // 6) % len(context.routine_locations)]
            return self.travel(context, destination, "follow my chosen daily routine")
        return None

    def read_local_record(self, context):
        curious = bool(context.learning_interests) and 7 <= context.perception.tick % 24 < 18
        if (not curious and dict(context.needs).get("knowledge", 0) < 30) or any(
            c.promisor_id == context.actor_id and c.status == "accepted" for c in context.commitments
        ):
            return None
        for record, organization, author, _ in context.organization_records:
            if author == context.actor_id or record in context.read_organization_records:
                continue
            operation = next((o for o in context.operations
                              if o.verb is ActionVerb.READ and o.target_id == organization), None)
            if operation:
                return self.action(context, ActionVerb.READ, organization,
                                   "read unfamiliar local evidence for my own learning",
                                   item_id=record, sources=(operation.source_ref,))
        return None
