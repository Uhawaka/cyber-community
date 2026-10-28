"""Take or leave a local office without assigning another person's labor."""

from dataclasses import asdict

from engine.contracts.community import ActionVerb
from engine.contracts.society import OrganizationCensure
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def role_action(run, proposal, context):
    group = next((group for group in run.compiled.community.organizations
                  if group.organization_id == proposal.target_id), None)
    projection = community_projection(run)
    if (group is None or (group.organization_id, proposal.actor_id) not in projection.memberships
            or context.perception.location_id != group.location_id):
        raise ValueError("office action requires current local membership")
    if proposal.verb is ActionVerb.CENSURE:
        if not proposal.reply_to.isdigit():
            raise ValueError("censure requires an explicit past evidence sequence")
        notice = OrganizationCensure(group.organization_id, proposal.actor_id, proposal.item_id,
                                     proposal.quantity - 1, int(proposal.reply_to),
                                     proposal.speech or proposal.intent)
        audience = tuple(sorted(person for person, actor in run.state.characters.items()
                                if actor.active and actor.location_id == group.location_id))
        return commit(
            run, EventType.ORGANIZATION_CENSURED, actor_id=proposal.actor_id, observers=audience,
            delta=Delta(actions=(ActionRecord(proposal.actor_id, "censure", group.organization_id, run.state.tick),)),
            data={"censure": asdict(notice), "summary": notice.statement},
            sources=proposal.source_refs, target_id=group.organization_id,
            commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
        )
    role = next((role for role in group.roles if role.role_id == proposal.item_id), None)
    if role is None:
        raise ValueError("unknown registered office")
    audience = tuple(sorted(person for organization, person in projection.memberships
                            if organization == group.organization_id
                            and run.state.characters[person].active
                            and run.state.characters[person].location_id == group.location_id))
    return commit(
        run, EventType.ORGANIZATION_ROLE_UPDATED, actor_id=proposal.actor_id, observers=audience,
        delta=Delta(actions=(ActionRecord(proposal.actor_id, proposal.verb.value,
                                         group.organization_id, run.state.tick),)),
        data={"role": {"organization_id": group.organization_id, "role_id": role.role_id,
                       "holder_id": proposal.actor_id,
                       "status": "held" if proposal.verb is ActionVerb.TAKE_ROLE else "vacant"},
              "summary": proposal.intent},
        sources=proposal.source_refs, target_id=group.organization_id,
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
    )
