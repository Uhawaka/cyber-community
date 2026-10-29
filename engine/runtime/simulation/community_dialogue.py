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
    if proposal.topic_ref:
        visible = {e.entity_id for e in context.perception.entities} | {proposal.actor_id}
        if proposal.topic_ref not in visible:
            raise ValueError("speech topic must be locally visible")
    replies_to = ""
    if proposal.reply_to and proposal.speech_act in {"refuse", "promise"}:
        from engine.runtime.character.community_asks import request_by_ref
        if request_by_ref(run, proposal.reply_to, proposal.actor_id) is None:
            raise ValueError("reply requires an open request addressed to you")
        replies_to = proposal.reply_to
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
    spoken_event = commit(
        run, EventType.DIALOGUE, actor_id=proposal.actor_id,
        observers=present(run, place),
        delta=Delta(
            actions=(ActionRecord(
                proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick,
            ),),
            needs=tuple(NeedDelta(actor_id, "social", -8) for actor_id in recipients),
        ),
        data={"utterance": proposal.speech, **audience, "reported_claim": reported, "location_id": place,
              "speech_act": proposal.speech_act, "topic_ref": proposal.topic_ref,
              "replies_to": replies_to},
        commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
        target_id=proposal.target_id, sources=sources,
    )
    if replies_to and proposal.speech_act == "promise":
        _register_promise(run, proposal, replies_to, spoken_event)


def _register_promise(run, proposal, replies_to, spoken_event):
    """答应了就要还：口头承诺在他们之间落成一条有期限的义务。"""
    from engine.contracts.community import Commitment
    from engine.runtime.character.community_asks import request_by_ref
    from engine.runtime.simulation.community_society import write_commitment

    ask = request_by_ref(run, replies_to, proposal.actor_id)
    if ask is None:
        return
    obligation = Commitment(
        f"promise:{spoken_event.sequence}", proposal.actor_id, ask[0],
        proposal.speech[:200], (f"event:{spoken_event.sequence}", replies_to),
        run.state.tick + 24, status="proposed", target_id=ask[0],
        action_verb="speak", quantity=1,
    )
    write_commitment(run, obligation, proposal.actor_id, system=True)
