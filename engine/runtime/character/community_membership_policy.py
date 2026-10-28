"""Joining a local group is a personal choice with its own later consequences."""

from engine.contracts.community import ActionVerb


def choose_join(policy, context):
    """Consider only invitations actually received by the actor."""
    if dict(context.needs).get("social", 0) < 30:
        return None
    for organization, inviter, source in context.membership_invitations:
        if dict(context.relationships).get(inviter, 0) > -20:
            return policy.action(
                context, ActionVerb.JOIN, organization,
                "accept a local invitation to participate in communal life",
                sources=(source,), reply_to=source.removeprefix("event:"),
            )
    return None


def choose_invitation(policy, context):
    """Invite based on received capability testimony or personally earned trust."""
    if (dict(context.needs).get("social", 0) < 30
            or any(c.promisor_id == context.actor_id and c.status == "accepted"
                   for c in context.commitments)):
        return None
    visible = {e.entity_id for e in context.perception.entities if e.kind == "character"}
    sent = set(context.sent_membership_invitations)
    for organization, members in context.invitation_groups:
        if not any(o.verb is ActionVerb.INVITE and o.target_id == organization for o in context.operations):
            continue
        for claim in context.capabilities:
            skill = claim.predicate.removeprefix("skill:")
            if (claim.channel != "heard" or claim.source_person != claim.subject
                    or claim.subject not in visible or claim.subject in members
                    or skill not in context.learning_interests or skill in context.skills
                    or dict(context.relationships).get(claim.subject, 0) <= -20
                    or (organization, claim.subject, claim.source_refs[0]) in sent):
                continue
            return policy.action(
                context, ActionVerb.INVITE, organization,
                "invite someone whose stated skill interests me",
                item_id=claim.subject, sources=claim.source_refs,
            )
    trust = dict(context.relationships)
    trust_sources = dict(context.trust_sources)
    for organization, members in context.invitation_groups:
        if not any(o.verb is ActionVerb.INVITE and o.target_id == organization for o in context.operations):
            continue
        candidates = sorted(
            (person for person in visible
             if person != context.actor_id and person not in members and trust.get(person, 0) > 0
             and person in trust_sources
             and not any(group == organization and candidate == person for group, candidate, _ in sent)),
            key=lambda person: (-trust[person], person),
        )
        if candidates:
            return policy.action(
                context, ActionVerb.INVITE, organization,
                "invite someone I have learned to trust",
                item_id=candidates[0],
                sources=(f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}",
                         trust_sources[candidates[0]]),
            )
    return None
