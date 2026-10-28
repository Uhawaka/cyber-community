"""Member-controlled, immutable records with explicit local reading."""

from dataclasses import asdict

from engine.contracts.community import ActionVerb
from engine.contracts.society import OrganizationRecord
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def organization_action(run, proposal, context):
    group = next((g for g in run.compiled.community.organizations
                  if g.organization_id == proposal.target_id), None)
    if group is None or context.perception.location_id != group.location_id:
        if proposal.verb in {ActionVerb.RECORD, ActionVerb.READ}:
            raise ValueError("organization records require local member access")
        raise ValueError("organization actions require presence at the organization")
    projection = community_projection(run)
    member = (group.organization_id, proposal.actor_id) in projection.memberships
    if proposal.verb is ActionVerb.JOIN:
        if member:
            raise ValueError("only a non-member can join a local organization")
        if not proposal.reply_to.isdigit():
            raise ValueError("joining requires an invitation sequence")
        return membership_change(run, proposal, group, projection, joining=True,
                                 invitation_sequence=int(proposal.reply_to))
    if not member:
        raise ValueError("organization action requires current local member access")
    if proposal.verb is ActionVerb.INVITE:
        people = {entity.entity_id for entity in context.perception.entities if entity.kind == "character"}
        if proposal.item_id not in people:
            raise ValueError("invitation requires a visible local person")
        return membership_invitation(run, proposal, group, projection)
    if proposal.verb is ActionVerb.RESIGN:
        return membership_change(run, proposal, group, projection, joining=False)
    posting = proposal.verb is ActionVerb.RECORD
    if posting:
        claim = projection.claims.get(proposal.item_id)
        if claim is None or claim.owner_id != proposal.actor_id:
            raise ValueError("record requires an owned claim")
        record = OrganizationRecord(
            f"record:{proposal.actor_id}:{run.state.tick}", group.organization_id,
            proposal.actor_id, claim, run.state.tick,
        )
        sources = tuple(dict.fromkeys((*proposal.source_refs, *claim.source_refs)))
        origin = None
    else:
        if not any(row[0] == proposal.item_id and row[1] == group.organization_id
                   for row in context.organization_records):
            raise ValueError("read requires a visible organization record")
        record = projection.organization_records[proposal.item_id]
        sources = proposal.source_refs
        origin = projection.record_sequences[record.record_id]
    commit(
        run, EventType.ORGANIZATION_RECORDED if posting else EventType.ORGANIZATION_READ,
        actor_id=proposal.actor_id, observers=(proposal.actor_id,),
        delta=Delta(actions=(ActionRecord(proposal.actor_id, proposal.verb.value, group.organization_id, run.state.tick),)),
        data={"record": asdict(record), "record_sequence": origin,
              "summary": f"{record.author_id} recorded {record.claim.subject}.{record.claim.predicate}: {record.claim.content}"},
        target_id=group.organization_id, sources=sources,
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
    )


def membership_change(run, proposal, group, projection, *, joining, invitation_sequence=None):
    members = {person for organization, person in projection.memberships
               if organization == group.organization_id}
    audience = tuple(sorted(person for person in members | {proposal.actor_id}
                            if run.state.characters[person].active
                            and run.state.characters[person].location_id == group.location_id))
    return commit(
        run, EventType.MEMBERSHIP_UPDATED, actor_id=proposal.actor_id, observers=audience,
        delta=Delta(actions=(ActionRecord(proposal.actor_id, "join" if joining else "resign",
                                          group.organization_id, run.state.tick),)),
        data={"membership": {"organization_id": group.organization_id, "member_id": proposal.actor_id,
                             "status": "joined", "invitation_sequence": invitation_sequence} if joining else
              {"organization_id": group.organization_id, "member_id": proposal.actor_id, "status": "left"},
              "summary": proposal.intent},
        sources=proposal.source_refs, target_id=group.organization_id,
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
    )


def membership_invitation(run, proposal, group, projection):
    members = {person for organization, person in projection.memberships
               if organization == group.organization_id}
    audience = tuple(sorted(person for person in members | {proposal.item_id}
                            if run.state.characters[person].active
                            and run.state.characters[person].location_id == group.location_id))
    return commit(
        run, EventType.MEMBERSHIP_UPDATED, actor_id=proposal.actor_id, observers=audience,
        delta=Delta(actions=(ActionRecord(proposal.actor_id, "invite", group.organization_id, run.state.tick),)),
        data={"membership": {"organization_id": group.organization_id, "member_id": proposal.item_id,
                             "status": "invited"}, "summary": proposal.intent},
        sources=proposal.source_refs, target_id=group.organization_id,
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
    )
