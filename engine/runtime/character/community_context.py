"""Budgeted decision inputs belonging to exactly one character."""

from __future__ import annotations

import json
from dataclasses import replace

from engine.contracts.community import (
    UTTERANCE_COOLDOWN_TICKS,
    ActionVerb,
    DecisionContext,
    KnownOperation,
)
from engine.runtime.character.community_projection import community_projection
from engine.runtime.character.community_knowledge import owned_claims, visible_claims, visible_capabilities
from engine.runtime.character.community_operations import known_operations
from engine.runtime.character.community_secrets import confidences, leaked_by, told_recently, told_secrets
from engine.runtime.character.community_event_view import visible_event_summary
from engine.runtime.space.community_perception import perceive


def decision_source_refs(context):
    """Sources explicitly available to this actor for this decision."""
    sources = {ref for ref, _ in (*context.soul, *context.memories, *context.claims)}
    sources.update(entity.source_ref for entity in context.perception.entities)
    sources.add(f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}")
    sources.update(context.perception.received_event_refs)
    sources.update(source for plan in (*context.goals, *context.plans, *context.intent_plans,
                                       *context.intent_plan_history) for source in plan.source_refs)
    sources.update(source for _, source, _, _, _, _ in context.plan_review_inputs)
    sources.update(source for record in (
        *context.offers, *context.commitments, *context.requests, *context.commitment_history,
        *context.handoffs, *context.handoff_history, *context.loans, *context.leases,
    ) for source in record.source_refs)
    sources.update(operation.source_ref for operation in context.known_repair_costs)
    sources.update(ref for _, ref in context.responsibility_sources)
    sources.update(source for claim in context.capabilities for source in claim.source_refs)
    sources.update(source for _, _, source in context.maintenance_requirements)
    sources.update(source for _, _, source in context.membership_invitations)
    sources.update(source for _, source in context.trust_sources)
    return frozenset(sources)


def resolve_visible_claim_refs(context, refs):
    """Resolve only claim identifiers actually exposed to their owner."""
    if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
        return refs
    if len(refs) != len(set(refs)):
        return refs
    visible = {ref for ref, _ in context.claims}
    aliases = {
        claim.claim_id: claim.source_refs[0]
        for claim in context.knowledge
        if claim.owner_id == context.actor_id and claim.source_refs[0] in visible
        and (claim.expires_tick is None or claim.expires_tick > context.perception.tick)
    }
    aliases.update({
        claim.claim_id: claim.source_refs[0]
        for claim in context.capabilities
        if claim.owner_id == context.actor_id
        and (claim.expires_tick is None or claim.expires_tick > context.perception.tick)
    })
    return list(dict.fromkeys(aliases.get(ref, ref) for ref in refs))


def decision_context(run, actor_id):
    character = next((c for c in run.compiled.world.characters if c.id == actor_id), None)
    perception = perceive(run, actor_id)
    projection = community_projection(run)
    profile = dict(character.profile) if character else {}
    skills = tuple(sorted(set(profile.get("skills", ())) |
                          projection.learned_skills.get(actor_id, set())))
    soul = tuple(
        (f"soul:{actor_id}:{key}", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        for key, value in (character.soul if character else ())
    )
    goals = tuple(
        goal for goal in projection.goals.pending_owned(actor_id)
        if goal.owner_id == actor_id and goal.status == "active"
    )
    recent_utterances = tuple(
        (event.tick, str(event.data.get("utterance") or ""))
        for event in run.events
        if event.event_type.value == "dialogue" and event.actor_id == actor_id
        and isinstance(event.data.get("utterance"), str) and event.data.get("utterance")
        and run.state.tick - event.tick < UTTERANCE_COOLDOWN_TICKS
    )[-3:]
    stances = tuple(
        (edge.target_id, edge.stance, edge.interest)
        for edge in (run.compiled.world.relationships or ())
        if edge.source_id == actor_id
    )
    need_values = dict(run.state.characters[actor_id].needs)
    here = run.state.characters[actor_id].location_id
    places = {location.id: location.name for location in run.compiled.world.locations}
    outbound, inbound = {}, {}
    for passage in run.compiled.world.passages:
        if passage.id not in profile.get("known_routes", ()) or dict(passage.properties).get("hidden") is True:
            continue
        if passage.origin_id == here:
            outbound.setdefault(passage.destination_id, passage.id)
        elif passage.destination_id == here:
            inbound.setdefault(passage.origin_id, passage.id)
    reachable = tuple(
        (outbound.get(destination) or inbound[destination], places.get(destination, ""))
        for destination in sorted(set(outbound) | set(inbound))
    )
    errands = tuple(
        (str(item.get("object_id") or ""), str(item.get("place_id") or ""),
         places.get(str(item.get("place_id") or ""), ""), str(item.get("goal") or ""))
        for item in (profile.get("errands") or ()) if isinstance(item, dict)
    )
    from engine.runtime.character.community_asks import requests_to_me as _requests_to_me
    requests_here = _requests_to_me(run, actor_id)
    authored_goals = tuple(str(item) for item in (profile.get("goals") or ()) if str(item).strip())
    danger_here = next(
        (int(getattr(location, "danger", 0) or 0) for location in run.compiled.world.locations
         if location.id == here), 0,
    )
    pressing_need = (
        "你很久没有和谁真正说过话，攒着的话在顶你"
        if need_values.get("social", 100) < 30 and not told_recently(run, actor_id)
        else "你累了，注意力在往下掉" if need_values.get("fatigue", 0) > 70 else ""
    )
    private_knowledge = tuple(
        (str(item.get("kind")), str(item.get("summary")).strip())
        for character in run.compiled.world.characters if character.id == actor_id
        for item in character.memory_seed
        if str(item.get("kind")) in ("secret", "belief") and str(item.get("summary") or "").strip()
    )[:6]
    retrieved = projection.index.retrieve(
        actor_id, tick=run.state.tick,
        entity_ids=tuple(e.entity_id for e in perception.entities),
        participant_ids=tuple(e.entity_id for e in perception.entities if e.kind == "character"),
        query=" ".join(goal.description for goal in goals),
        limit=12, character_budget=3000,
    )
    memories = tuple(
        (item.record.source_refs[0], f"[{item.record.kind}] {item.record.summary}")
        for item in retrieved
    )
    def received_record(record, key, id_field):
        origin = run.log.event_at(projection.social_latest[(key, getattr(record, id_field))])
        return replace(record, source_refs=(f"event:{origin.sequence}",))
    claims = visible_claims(projection, actor_id, run.state.tick,
                            tuple(e.entity_id for e in perception.entities))
    repair_targets = {g.target_id for g in goals if g.action_verb == "repair"} | {
        c.target_id for c in projection.commitments.owned(actor_id)
        if c.promisor_id == actor_id and c.status == "accepted" and c.action_verb == "repair"
    }
    observed = {}
    for claim in owned_claims(projection.claims, actor_id):
        if (claim.owner_id == actor_id and claim.channel == "observation"
                and claim.predicate == "condition" and claim.subject in repair_targets):
            old = observed.get(claim.subject)
            if old is None or (claim.acquired_tick, claim.claim_id) > (old.acquired_tick, old.claim_id):
                observed[claim.subject] = claim
    local_people = {p for p, actor in run.state.characters.items()
                    if actor.active and actor.location_id == perception.location_id}
    visible_people = {actor_id, *(e.entity_id for e in perception.entities if e.kind == "character")}
    members = {}
    for organization, person in projection.memberships:
        members.setdefault(organization, set()).add(person)
    invitation_groups = tuple(
        (o.organization_id, tuple(sorted(members.get(o.organization_id, set()) & local_people)))
        for o in run.compiled.community.organizations
        if (o.organization_id, actor_id) in projection.memberships and o.location_id == perception.location_id
        and (members.get(o.organization_id, set()) & local_people) <= visible_people
    )
    local_groups = tuple(group for group in invitation_groups if len(group[1]) >= 2)
    local_records = sorted(
        (identity for organization in run.compiled.community.organizations
         if (organization.organization_id, actor_id) in projection.memberships
         and organization.location_id == perception.location_id
         for identity in projection.records_by_group.get(organization.organization_id, ())[-16:]),
        key=projection.record_sequences.__getitem__,
    )[-16:]
    plan_history = sorted(
        (plan for plan in projection.intent_plans.owned(actor_id)
         if plan.status in {"completed", "abandoned"}),
        key=lambda plan: projection.intent_plan_sequences[plan.plan_id],
    )[-8:]
    pending_plans = tuple(projection.intent_plans.pending_owned(actor_id))
    review_inputs = []
    for plan in pending_plans:
        targets = {step.target_id for index, step in enumerate(plan.steps)
                   if index not in plan.completed_steps and index not in plan.skipped_steps
                   and step.target_id != actor_id}
        after = max(projection.intent_plan_sequences[plan.plan_id],
                    projection.last_decisions.get(actor_id, -1))
        for sequence in range(max(after + 1, projection.cursor - 64), projection.cursor):
            event = run.log.event_at(sequence)
            if (actor_id in event.observers and event.actor_id and event.actor_id != actor_id
                    and event.event_type.value in {
                        "dialogue", "activity_finished", "commitment_updated", "exchange_updated",
                        "request_updated", "responsibility_updated",
                    } and ({event.actor_id, event.target_entity_id} & targets)):
                summary = visible_event_summary(event, actor_id)
                summary = summary if len(summary) <= 500 else summary[:500] + "..."
                review_inputs.append((plan.plan_id, f"event:{sequence}", event.event_type.value,
                                      event.actor_id, event.target_entity_id or "", summary))
    return DecisionContext(
        actor_id, run.state.state_hash(), perception, soul, memories[-16:],
        claims,
        goals,
        tuple(sorted(run.state.characters[actor_id].needs.items())),
        (ActionVerb.WAIT, ActionVerb.REST, ActionVerb.MOVE, ActionVerb.INSPECT,
         ActionVerb.REPAIR, ActionVerb.TAKE, ActionVerb.USE, ActionVerb.SPEAK, ActionVerb.LEARN,
         ActionVerb.PURSUE, ActionVerb.ABANDON, ActionVerb.OFFER, ActionVerb.TRANSFER,
         ActionVerb.ACCEPT, ActionVerb.REJECT, ActionVerb.COMMIT, ActionVerb.REQUEST, ActionVerb.HANDOFF,
         ActionVerb.RECORD, ActionVerb.READ, ActionVerb.LEND, ActionVerb.REPAY, ActionVerb.RESIGN,
         ActionVerb.JOIN, ActionVerb.INVITE, ActionVerb.TAKE_ROLE, ActionVerb.LEAVE_ROLE, ActionVerb.CENSURE,
         ActionVerb.LEASE, ActionVerb.RETURN_LEASE, ActionVerb.PLAN, ActionVerb.ABANDON_PLAN, ActionVerb.BRANCH_PLAN),
        skills,
        tuple(p for p in projection.plans.pending_owned(actor_id)
              if p.owner_id == actor_id and p.status in {"ready", "blocked"}),
        tuple(received_record(o, "offer", "offer_id") for o in projection.offers.owned(actor_id)
              if actor_id in {o.sender_id, o.recipient_id} and o.status == "proposed"),
        tuple(received_record(c, "commitment", "commitment_id") for c in projection.commitments.owned(actor_id)
              if actor_id in {c.promisor_id, c.beneficiary_id}
              and c.status in {"proposed", "accepted"}),
        tuple(sorted((target, trust) for (owner, target), trust in projection.subjective_trust.items()
                     if owner == actor_id)),
        tuple(sorted(run.state.inventories[actor_id].items())),
        known_operations(run, actor_id, perception, skills),
        tuple((p.id, p.origin_id, p.destination_id) for p in run.compiled.world.passages
              if p.id in profile.get("known_routes", ()) and dict(p.properties).get("hidden") is not True),
        tuple((r.id, r.location_id) for r in run.compiled.world.resources
              if (actor_id, r.id) in projection.responsibilities),
        tuple(profile.get("learning_interests", ())),
        profile.get("home_location_id", perception.location_id),
        tuple(profile.get("routine_locations", ())),
        tuple(sorted(projection.reported_claims.get(actor_id, ()))),
        tuple((o.organization_id, o.name, o.norms) for o in run.compiled.community.organizations
              if (o.organization_id, actor_id) in projection.memberships or o.location_id == perception.location_id),
        tuple(c for c in owned_claims(projection.claims, actor_id) if c.owner_id == actor_id
              and c.source_refs[0] in {ref for ref, _ in claims})[-12:],
        tuple((rule.skill, resource.id, resource.location_id)
              for rule in run.compiled.community.learning
              for resource in run.compiled.world.resources if resource.id == rule.resource_id
              and rule.skill in profile.get("learning_interests", ())
              and dict(resource.properties).get("hidden") is not True),
        tuple((r.id, r.location_id) for r in run.compiled.world.resources
              if dict(r.properties).get("public_access") is True
              and dict(r.properties).get("consumable") is True),
        tuple(received_record(r, "request", "request_id") for r in projection.requests.owned(actor_id)
              if actor_id in {r.requester_id, r.helper_id})[-16:],
        tuple(profile.get("stocking_interests", ())),
        tuple((r.id, r.location_id) for r in run.compiled.world.resources
              if r.id in profile.get("stocking_interests", ())
              and dict(r.properties).get("hidden") is not True),
        tuple(KnownOperation(ActionVerb.REPAIR, rule.target_id,
                             observed[rule.target_id].source_refs[0],
                             duration_ticks=rule.duration_ticks, inputs=rule.inputs,
                             restored_condition=rule.restored_condition)
              for rule in run.compiled.community.repairs
              if rule.target_id in observed and set(rule.required_skills) <= set(skills))[:16],
        tuple(received_record(c, "commitment", "commitment_id") for c in projection.commitments.owned(actor_id)
              if actor_id in {c.promisor_id, c.beneficiary_id}
              and c.status in {"rejected", "fulfilled", "breached"})[-16:],
        tuple(received_record(h, "handoff", "handoff_id") for h in projection.handoffs.owned(actor_id)
              if actor_id in {h.sender_id, h.recipient_id} and h.status == "proposed"),
        tuple(received_record(h, "handoff", "handoff_id") for h in projection.handoffs.owned(actor_id)
              if actor_id in {h.sender_id, h.recipient_id} and h.status != "proposed")[-16:],
        tuple(sorted((target, ref) for (owner, target), ref in projection.responsibility_sources.items()
                     if owner == actor_id)),
        visible_capabilities(projection, actor_id, run.state.tick,
                             tuple(e.entity_id for e in perception.entities if e.kind == "character")),
        tuple((rule.target_id, tuple(sorted(set((*resource.required_skills, *rule.required_skills)))),
               next(e.source_ref for e in perception.entities if e.entity_id == rule.target_id))
              for rule in run.compiled.community.repairs for resource in run.compiled.world.resources
              if resource.id == rule.target_id and resource.location_id == perception.location_id
              and any(e.entity_id == resource.id for e in perception.entities))[:16],
        local_groups,
        tuple((r.record_id, r.organization_id, r.author_id, r.tick)
              for identity in local_records for r in (projection.organization_records[identity],)),
        tuple(sorted(projection.read_records_by_owner.get(actor_id, ()))),
        tuple((r.organization_id, r.claim.claim_id)
              for identity in projection.records_by_author.get(actor_id, ())
              for r in (projection.organization_records[identity],)),
        tuple(received_record(r, "loan", "loan_id") for r in projection.loans.owned(actor_id)
              if r.status in {"proposed", "accepted", "overdue"}),
        tuple((group.organization_id, role.role_id,
               projection.role_holders[(group.organization_id, role.role_id)],
               role.required_skills, role.permissions)
              for group in run.compiled.community.organizations
              if (group.organization_id, actor_id) in projection.memberships
              and group.location_id == perception.location_id for role in group.roles),
        tuple(received_record(record, "lease", "lease_id") for record in projection.leases.owned(actor_id)
              if record.status in {"proposed", "accepted", "overdue"}),
        tuple((group.organization_id, group.location_id, role.role_id,
               projection.role_holders[(group.organization_id, role.role_id)],
               role.required_skills, role.permissions)
              for group in run.compiled.community.organizations
              if (group.organization_id, actor_id) in projection.memberships for role in group.roles),
        tuple((operation.target_id, run.log.event_at(int(operation.source_ref[6:])).actor_id, operation.source_ref)
              for operation in known_operations(run, actor_id, perception, skills)
              if operation.verb is ActionVerb.JOIN),
        tuple((record.organization_id, record.subject_id, record.norm_index, record.evidence_sequence)
              for sequence in projection.censures_by_issuer.get(actor_id, ())
              for record in (projection.censures[sequence],)),
        tuple(sorted(projection.sent_membership_invitations.get(actor_id, ()))),
        invitation_groups,
        tuple(sorted((target, source) for (owner, target), source in projection.trust_sources.items()
                     if owner == actor_id)),
        tuple(sorted(r.request_id for r in projection.requests.pending_owned(actor_id)
                     if r.helper_id == actor_id
                     and (r.requester_id, r.item_id,
                          f"event:{projection.social_origins[('request', r.request_id, 'open')]}")
                     in projection.loan_proposal_sources.get(actor_id, set()))),
        tuple(replace(plan, source_refs=(f"event:{projection.intent_plan_sequences[plan.plan_id]}",))
              for plan in pending_plans),
        tuple(replace(plan, source_refs=(f"event:{projection.intent_plan_sequences[plan.plan_id]}",))
              for plan in plan_history),
        tuple(review_inputs[-16:]),
        relationship_stances=stances,
        recent_utterances=recent_utterances,
        private_knowledge=private_knowledge,
        pressing_need=pressing_need,
        told_secrets=told_secrets(run, actor_id),
        confidences=confidences(run, actor_id),
        leaked=leaked_by(run, actor_id),
        danger_here=danger_here,
        reachable=reachable,
        authored_goals=authored_goals,
        errands=errands,
        requests_to_me=requests_here,
    )
