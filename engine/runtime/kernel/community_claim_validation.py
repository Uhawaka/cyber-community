"""Semantic provenance checks in addition to source access checks."""

from __future__ import annotations

from engine.contracts.cognition import KnowledgeClaim


def validate_group_speech(event, state, community, events=(), index=None):
    from engine.runtime.kernel.events import ActionRecord, Delta, EventValidationError, NeedDelta
    from engine.runtime.kernel.community_membership_validation import current_members

    group = next((o for o in community.organizations
                  if o.organization_id == event.data.get("organization_id")), None) if community else None
    actor = state.characters.get(event.actor_id)
    members = current_members(group, events, index) if group is not None else set()
    if (group is None or actor is None or not actor.active
            or event.actor_id not in members or actor.location_id != group.location_id):
        raise EventValidationError("group speech requires a member at the organization location")
    participants = tuple(sorted(
        person for person in members if state.characters[person].active
        and state.characters[person].location_id == group.location_id
    ))
    raw_participants = event.data.get("participant_ids")
    if (len(participants) < 2 or not isinstance(raw_participants, (tuple, list))
            or tuple(raw_participants) != participants
            or "listener_id" in event.data or event.target_entity_id != group.organization_id
            or event.data.get("location_id") != group.location_id):
        raise EventValidationError("group speech participants must match actual local members")
    expected = Delta(
        actions=(ActionRecord(event.actor_id, "speak", group.organization_id, state.tick),),
        needs=tuple(NeedDelta(person, "social", -8) for person in participants),
    )
    if event.delta != expected:
        raise EventValidationError("group speech cannot act, consent or transfer for its listeners")


def validate_claim(claim, event, events, index=None):
    from engine.runtime.kernel.events import EventValidationError

    if claim.acquired_tick != event.tick:
        raise EventValidationError("claim acquisition must match current tick")
    if index is not None:
        if claim.owner_id in index.invalid_claim_history:
            raise TypeError("invalid prior claim record")
        existing = index.claims_by_actor.get(claim.owner_id, ())
    else:
        existing = {
            raw["claim_id"]: raw for prior in events
            if prior.actor_id == claim.owner_id
            for raw in prior.data.get("claims", ())
        }
    if claim.claim_id in existing:
        raise EventValidationError("claims are immutable; record a correction instead")
    for claim_id in claim.contradicts:
        if claim_id not in existing and not claim_id.startswith(f"claim:{claim.owner_id}:"):
            raise EventValidationError("contradiction must reference an owned prior claim")
    if claim.channel == "inference":
        return
    if claim.channel == "seed":
        raise EventValidationError("seed channel is author-owned and cannot be created at runtime")
    if len(claim.source_refs) != 1 or not claim.source_refs[0].startswith("event:"):
        raise EventValidationError("claim channel requires a direct event source")
    try:
        origin = events[int(claim.source_refs[0].split(":", 1)[1])]
    except (ValueError, IndexError) as exc:
        raise EventValidationError("claim channel has invalid source") from exc
    if claim.channel == "observation":
        valid = (
            origin.event_type.value == "inspected" and origin.actor_id == claim.owner_id
            and claim.subject == origin.data.get("resource_id") and claim.predicate == "condition"
            and claim.content == str(origin.data.get("condition")) and not claim.source_person
        )
        for patch in origin.delta.entity_patches:
            valid |= (
                origin.event_type.value == "activity_finished" and origin.data.get("status") == "completed"
                and patch.entity_id == claim.subject and patch.component is not None
                and claim.predicate == "condition"
                and claim.content == str(patch.component.data.get("condition"))
                and claim.owner_id in origin.observers and not claim.source_person
            )
    elif claim.channel == "heard":
        reading = origin.event_type.value == "organization_read"
        reported = origin.data["record"]["claim"] if reading else origin.data.get("reported_claim")
        valid = (
            (reading and claim.owner_id == origin.actor_id
             and claim.owner_id != origin.data["record"]["author_id"]
             or origin.event_type.value in {"dialogue", "organization_censured"} and claim.owner_id != origin.actor_id)
            and claim.source_person == (origin.data["record"]["author_id"] if reading else origin.actor_id)
        )
        if reported:
            valid &= (
                claim.subject == reported["subject"] and claim.predicate == reported["predicate"]
                and claim.content == reported["content"]
                and claim.confidence <= min(0.8, reported["confidence"]) * 0.9
            )
            if reading:
                valid &= claim.expires_tick == reported.get("expires_tick")
        else:
            valid &= (
                claim.subject == origin.actor_id and claim.predicate == "said"
                and claim.content == (origin.data["censure"]["statement"] if origin.event_type.value == "organization_censured"
                                      else origin.data.get("utterance")) and claim.confidence <= 0.5
            )
    elif claim.channel == "learned":
        valid = (
            origin.event_type.value == "activity_finished" and origin.actor_id == claim.owner_id
            and origin.data.get("status") == "completed"
            and (
                claim.subject == origin.data.get("resource_id") and claim.predicate == "skill"
                and claim.content == origin.data.get("learned_skill")
                or claim.subject == claim.owner_id
                and claim.predicate == f"skill:{origin.data.get('learned_skill')}"
                and claim.content == "acquired"
            )
        )
    else:
        valid = False
    if not valid:
        raise EventValidationError("claim channel or content does not match evidence")


def validate_report(event, events, state, world=None, index=None, *, community=None):
    from engine.runtime.character.community_knowledge import claims_from_event, public_claim, seed_claim, skill_claims
    from engine.runtime.kernel.events import EventValidationError

    reported = event.data.get("reported_claim")
    if not reported:
        return
    try:
        key = reported["claim_id"]
        character = next((c for c in world.characters if c.id == event.actor_id), None) if world else None
        known = next((c for c in skill_claims(character) if c.claim_id == key), None) if character else None
        if known is None and character and community:
            known = next((claim for number, text in enumerate(community.public_knowledge)
                          for claim in (public_claim(character.id, world.world_id, number, text),)
                          if claim.claim_id == key), None)
        if known is None and character:
            known = next((c for number, item in enumerate(character.memory_seed)
                          for c in (seed_claim(character, number, item),)
                          if c is not None and c.claim_id == key), None)
        relevant = (events if index is None else
                    (events[sequence] for sequence in index.report_event_sequences_by_actor.get(event.actor_id, ())))
        for prior in relevant:
            if prior.actor_id == event.actor_id:
                for raw in prior.data.get("claims", ()):
                    if raw["claim_id"] == key:
                        known = KnowledgeClaim(**{
                            **raw, "source_refs": tuple(raw["source_refs"]),
                            "contradicts": tuple(raw.get("contradicts", ())),
                        })
            if event.actor_id in prior.observers or event.actor_id == prior.actor_id:
                for claim in claims_from_event(prior, event.actor_id, {}):
                    if claim.claim_id == key:
                        known = claim
        if known is not None:
            valid = all(reported[field] == getattr(known, field) for field in (
                "subject", "predicate", "content", "confidence", "channel",
            )) and tuple(reported["source_refs"]) == known.source_refs
            valid &= known.expires_tick is None or known.expires_tick > event.tick
        elif key.startswith(f"claim:seed:{event.actor_id}:"):
            number = key.rsplit(":", 1)[1]
            valid = (
                reported["content"] == state.facts.get(f"{event.actor_id}:memory:{number}")
                and reported["channel"] == "seed"
                and tuple(reported["source_refs"]) == (f"seed:{event.actor_id}:{number}",)
                and 0 <= reported["confidence"] <= 1
            )
        else:
            valid = False
        valid &= set(reported["source_refs"]) <= set(event.data.get("source_refs", ()))
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid reported claim") from exc
    if not valid:
        raise EventValidationError("reported claim must match owned unexpired evidence")
    return known
