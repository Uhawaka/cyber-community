"""Personal workload choices, never inferred consent or another's skills."""

from engine.contracts.community import ActionVerb


def capability_evidence(context, person, skills):
    return tuple(c for c in context.capabilities if c.subject == person
                 and c.predicate[6:] in skills and c.confidence >= 0.6)


def prepare_for_handoff(policy, context, record, required, fatigue):
    missing = set(required) - set(context.skills)
    if not missing or not missing <= set(context.learning_interests):
        return None
    for operation in context.operations:
        if (operation.verb is ActionVerb.LEARN and operation.learned_skill in missing
                and operation.duration_ticks + 3 <= record.deadline_tick - context.perception.tick
                and fatigue + operation.duration_ticks + 5 < 45):
            return policy.new_goal(context, "learn", operation.target_id,
                                   "prepare for care through a personally chosen skill",
                                   sources=record.source_refs)
    return None


def choose_handoff(policy, context):
    fatigue = dict(context.needs).get("fatigue", 0)
    visible = {e.entity_id for e in context.perception.entities}
    repairs = {o.target_id for o in context.operations if o.verb is ActionVerb.REPAIR}
    requirements = {target: skills for target, skills, _ in context.maintenance_requirements}
    for record in sorted(context.handoffs, key=lambda h: (h.deadline_tick, h.handoff_id)):
        if record.recipient_id != context.actor_id or record.sender_id not in visible or record.target_id not in visible:
            continue
        trusted = dict(context.relationships).get(record.sender_id, 0) > -20
        free = len(context.responsibilities) < 2 and not any(
            c.promisor_id == context.actor_id and c.status == "accepted" for c in context.commitments
        )
        interested = bool(set(requirements.get(record.target_id, ())) & set(context.learning_interests)) or any(
            g.target_id == record.target_id and g.action_verb == "repair" for g in context.goals
        )
        if (trusted and free and interested and record.target_id in repairs and 45 <= fatigue < 60
                and dict(context.needs).get("resources", 0) < 60
                and record.deadline_tick - context.perception.tick >= 3):
            source = f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}"
            sources = tuple(dict.fromkeys((*record.source_refs, source)))
            if len(sources) <= 16:
                return policy.action(context, ActionVerb.REST, context.actor_id,
                                     "recover for my own interest before deciding about care", sources=sources)
        if record.target_id not in repairs:
            learning = prepare_for_handoff(
                policy, context, record, requirements.get(record.target_id, ()), fatigue,
            ) if trusted and free else None
            if learning:
                return learning
            if trusted and free and any(g.action_verb == "learn" and g.target_id in {
                o.target_id for o in context.operations if o.verb is ActionVerb.LEARN
                and o.learned_skill in set(requirements.get(record.target_id, ())) - set(context.skills)
            } for g in context.goals):
                continue
        consent = (
            record.target_id in repairs and fatigue < 45 and trusted and free
        )
        skill_sources = tuple(ref for c in context.capabilities
                              if c.subject == context.actor_id
                              and c.predicate[6:] in requirements.get(record.target_id, ())
                              for ref in c.source_refs) if consent else ()
        sources = tuple(dict.fromkeys((*record.source_refs, *skill_sources)))
        if len(sources) > 16:
            continue
        return policy.action(
            context, ActionVerb.ACCEPT if consent else ActionVerb.REJECT, record.handoff_id,
            "volunteer for care within my capacity" if consent else "decline care beyond my capacity or trust",
            sources=sources,
        )
    if fatigue < 45:
        return None
    for target, location in context.responsibilities:
        if location != context.perception.location_id or target not in repairs:
            continue
        if any(h.target_id == target for h in context.handoffs):
            continue
        if any(h.target_id == target and context.perception.tick <= h.deadline_tick
               for h in context.handoff_history):
            continue
        if any(g.target_id == target and g.action_verb == "repair" for g in context.goals):
            continue
        if any(c.promisor_id == context.actor_id and c.status == "accepted" and c.target_id == target
               for c in context.commitments):
            continue
        people = [e.entity_id for e in context.perception.entities if e.kind == "character"]
        required = requirements.get(target, ())
        def rank(person):
            evidence = capability_evidence(context, person, required)
            informed = bool(required) and set(required) <= {c.predicate[6:] for c in evidence}
            return (not informed, -dict(context.relationships).get(person, 0), person)
        for recipient in sorted(people, key=rank):
            evidence = capability_evidence(context, recipient, required)
            refused = [h for h in context.handoff_history
                       if h.target_id == target and h.recipient_id == recipient and h.sender_id == context.actor_id
                       and h.status in {"rejected", "expired"}]
            if any(not any(
                source.startswith("event:") and int(source[6:]) > int(h.source_refs[0][6:])
                for c in evidence for source in c.source_refs
            ) for h in refused):
                continue
            if dict(context.relationships).get(recipient, 0) > -20:
                source = f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}"
                sources = tuple(dict.fromkeys((source, *(ref for c in evidence for ref in c.source_refs))))
                if len(sources) > 16:
                    continue
                return policy.action(context, ActionVerb.HANDOFF, recipient,
                                     "seek voluntary relief using my known capability evidence" if evidence else
                                     "ask about voluntary relief without assuming capability",
                                     item_id=target, sources=sources)
    return None
