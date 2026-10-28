"""Archiving a statement and reading it do not promote it to a world fact."""

from dataclasses import replace

from engine.contracts.society import decode_organization_record
from engine.runtime.kernel.events import ActionRecord, Delta, EventType, EventValidationError
from engine.runtime.kernel.community_claim_validation import validate_report
from engine.runtime.kernel.community_membership_validation import current_members


def validate_organization_record(event, events, state, community, world, index=None):
    try:
        record = decode_organization_record(event.data["record"])
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid organization record") from exc
    group = next((g for g in community.organizations
                  if g.organization_id == record.organization_id), None) if community else None
    actor = state.characters.get(event.actor_id)
    if (group is None or actor is None or not actor.active or event.actor_id not in current_members(group, events, index)
            or actor.location_id != group.location_id or event.observers != (event.actor_id,)
            or event.target_entity_id != group.organization_id):
        raise EventValidationError("organization record requires a member at the record location")
    posting = event.event_type is EventType.ORGANIZATION_RECORDED
    verb = "record" if posting else "read"
    if event.delta != Delta(actions=(ActionRecord(event.actor_id, verb, group.organization_id, state.tick),)):
        raise EventValidationError("organization record cannot transfer goods, skills or duties")
    def find_origin():
        if index is not None:
            return index.organization_records.get(record.record_id)
        return next((e for e in events if e.event_type is EventType.ORGANIZATION_RECORDED
                     and e.data["record"]["record_id"] == record.record_id), None)

    if posting:
        if record.author_id != event.actor_id or record.tick != state.tick or find_origin() is not None:
            raise EventValidationError("organization record must be a new author-owned statement")
        known = validate_report(replace(event, data={
            **event.data, "reported_claim": vars(record.claim),
        }), events, state, world, index, community=community)
        if known != record.claim:
            raise EventValidationError("organization record must preserve its author's complete evidence")
    else:
        origin = find_origin()
        if origin is None or decode_organization_record(origin.data["record"]) != record:
            raise EventValidationError("organization read must match an existing immutable record")
        if event.data.get("record_sequence") != origin.sequence:
            raise EventValidationError("organization read must preserve the exact record origin")
