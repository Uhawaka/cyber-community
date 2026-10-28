"""Norm enforcement is a sourced human judgment, never an automatic verdict."""

from engine.contracts.society import OrganizationCensure
from engine.runtime.kernel.community_membership_validation import current_members
from engine.runtime.kernel.community_role_validation import role_holders


def evidence_subject(event):
    if event.event_type.value == "commitment_updated" and event.data["commitment"]["status"] == "breached":
        return event.data["commitment"]["promisor_id"]
    if event.event_type.value == "loan_updated" and event.data["loan"]["status"] == "overdue":
        return event.data["loan"]["borrower_id"]
    return event.actor_id


def validate_censure(event, events, state, community, index=None):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError
    try:
        notice = OrganizationCensure(**event.data["censure"])
        group = next(group for group in community.organizations if group.organization_id == notice.organization_id)
        members = current_members(group, events, index)
        if event.target_entity_id != group.organization_id or notice.issuer_id != event.actor_id:
            raise ValueError("censure must belong to its issuer and organization")
        if notice.issuer_id not in members or notice.subject_id not in members:
            raise ValueError("censure requires current members")
        if any(not state.characters[person].active
               or state.characters[person].location_id != group.location_id
               for person in (notice.issuer_id, notice.subject_id)):
            raise ValueError("censure requires both parties at the organization")
        holders = role_holders(group, events, index)
        if not any(holders[role.role_id] == notice.issuer_id and "censure" in role.permissions
                   for role in group.roles):
            raise ValueError("issuer lacks a current office with censure permission")
        if notice.norm_index >= len(group.norms) or notice.evidence_sequence >= len(events):
            raise ValueError("unknown norm or non-past evidence")
        origin = events[notice.evidence_sequence]
        if (notice.issuer_id not in origin.observers or evidence_subject(origin) != notice.subject_id
                or not origin.delta.actions and origin.event_type.value not in {"commitment_updated", "loan_updated"}):
            raise ValueError("censure requires visible committed conduct by its subject")
        if f"event:{notice.evidence_sequence}" not in event.data["source_refs"]:
            raise ValueError("censure must cite its evidence")
        key = tuple(getattr(notice, field) for field in (
            "organization_id", "issuer_id", "subject_id", "norm_index", "evidence_sequence",
        ))
        repeated = key in index.censures if index is not None else any(
            prior.event_type.value == "organization_censured"
            and tuple(prior.data["censure"][field] for field in (
                "organization_id", "issuer_id", "subject_id", "norm_index", "evidence_sequence",
            )) == key for prior in events
        )
        if repeated:
            raise ValueError("same issuer cannot repeatedly censure the same evidence")
        audience = tuple(sorted(person for person, actor in state.characters.items()
                                if actor.active and actor.location_id == group.location_id))
        if event.observers != audience or event.delta != Delta(actions=(
            ActionRecord(event.actor_id, "censure", group.organization_id, state.tick),
        )):
            raise ValueError("censure cannot seize goods, revoke consent or erase duties")
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError) as exc:
        raise EventValidationError("invalid organization censure: " + str(exc)) from exc
