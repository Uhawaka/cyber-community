"""Local speech records testimony without turning it into world truth."""

from __future__ import annotations

from engine.contracts.community import require_text
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType, NeedDelta
from engine.runtime.simulation.community_events import commit, present


def speak(run, proposal, context):
    require_text(proposal.speech, "speech")
    listeners = {
        e.entity_id for e in context.perception.entities if e.kind == "character"
    }
    groups = dict(context.organization_groups)
    participants = groups.get(proposal.target_id)
    if proposal.target_id not in listeners and participants is None:
        raise ValueError("listener must be active and locally reachable")
    if participants is not None and (
        proposal.actor_id not in participants or len(participants) < 2
        or not set(participants) <= listeners | {proposal.actor_id}
    ):
        raise ValueError("organization group requires locally present members")
    reported = None
    sources = proposal.source_refs
    if proposal.item_id:
        claim = community_projection(run).claims.get(proposal.item_id)
        if claim is None or claim.owner_id != proposal.actor_id:
            raise ValueError("reported claim must be owned by speaker")
        if claim.expires_tick is not None and claim.expires_tick <= run.state.tick:
            raise ValueError("expired claim requires fresh evidence")
        reported = {
            "claim_id": claim.claim_id, "subject": claim.subject,
            "predicate": claim.predicate, "content": claim.content,
            "confidence": claim.confidence, "channel": claim.channel,
            "source_refs": claim.source_refs,
        }
        sources = tuple(dict.fromkeys((*sources, *claim.source_refs)))
    place = context.perception.location_id
    recipients = participants if participants is not None else tuple(sorted((proposal.actor_id, proposal.target_id)))
    audience = {"organization_id": proposal.target_id, "participant_ids": participants} if participants else {
        "listener_id": proposal.target_id,
    }
    commit(
        run, EventType.DIALOGUE, actor_id=proposal.actor_id,
        observers=present(run, place),
        delta=Delta(
            actions=(ActionRecord(
                proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick,
            ),),
            needs=tuple(NeedDelta(actor_id, "social", -8) for actor_id in recipients),
        ),
        data={"utterance": proposal.speech, **audience, "reported_claim": reported, "location_id": place},
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
        target_id=proposal.target_id, sources=sources,
    )
