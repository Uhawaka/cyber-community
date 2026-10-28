"""Voluntary office-taking and sourced norm judgments chosen by the actor alone."""

from engine.contracts.community import ActionVerb


def choose_role(policy, context):
    """Claim a vacant registered office of a group the actor belongs to and can staff."""
    seats = sorted(context.organization_seats, key=lambda seat: (seat[0], seat[2]))
    here = context.perception.location_id
    for organization_id, location_id, role_id, holder_id, required_skills, _ in seats:
        if holder_id or not set(required_skills) <= set(context.skills):
            continue
        if location_id == here:
            return policy.action(
                context, ActionVerb.TAKE_ROLE, organization_id,
                f"take the vacant {role_id} office I am qualified for", item_id=role_id,
            )
        travel = policy.travel(context, location_id, f"go to take up the vacant {role_id} office")
        if travel:
            return travel
    return None


def breach_evidence(context):
    """Real witnessed conduct that a member could judge: breaches and overdue debts."""
    for record in context.commitment_history:
        if record.status == "breached" and record.beneficiary_id == context.actor_id:
            yield record.promisor_id, record.source_refs[0], "未履行此前的约定"
    for record in context.loans:
        if record.status == "overdue" and record.lender_id == context.actor_id:
            yield record.borrower_id, record.source_refs[0], "未按期偿还借款"


def choose_censure(policy, context):
    """State a personal judgment on a real breach, only while holding the censure office."""
    local_members = dict(context.organization_groups)
    norms = {organization_id: norm_list for organization_id, _, norm_list in context.organizations}
    holders = {organization_id: permissions
               for organization_id, _, holder_id, _, permissions in context.organization_roles
               if holder_id == context.actor_id}
    for organization_id, permissions in sorted(holders.items()):
        if "censure" not in permissions or not norms.get(organization_id):
            continue
        members = set(local_members.get(organization_id, ()))
        for subject, reference, description in breach_evidence(context):
            if subject not in members or not reference.startswith("event:"):
                continue
            sequence = reference[len("event:"):]
            if not sequence.isdigit() or (organization_id, subject, 0, int(sequence)) in context.own_censures:
                continue
            return policy.action(
                context, ActionVerb.CENSURE, organization_id,
                f"judge {subject}'s unfinished duty before local members",
                item_id=subject, quantity=1, reply_to=sequence,
                speech=f"我认为{subject}{description}，需要说明。", sources=(reference,),
            )
    return None
