"""Voluntary responsibility transfer, separate from promises and inventory."""

from dataclasses import asdict, replace

from engine.contracts.community import ActionVerb
from engine.contracts.society import ResponsibilityHandoff
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def write_handoff(run, record, actor_id, *, action=None, system=False):
    return commit(
        run, EventType.RESPONSIBILITY_UPDATED, actor_id=actor_id,
        observers=tuple(sorted(p for p in (record.sender_id, record.recipient_id)
                               if run.state.characters[p].active)),
        delta=Delta(actions=(action,)) if action else None,
        data={"handoff": asdict(record), "system_update": system,
              "summary": f"responsibility {record.target_id}: {record.status}"},
        sources=record.source_refs, target_id=record.target_id,
        commit_id=f"handoff:{record.handoff_id}:{record.status}",
    )


def begin_handoff(run, proposal):
    projection = community_projection(run)
    action = ActionRecord(proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick)
    if proposal.verb is ActionVerb.HANDOFF:
        record = ResponsibilityHandoff(
            proposal.proposal_id, proposal.actor_id, proposal.target_id,
            proposal.item_id, proposal.source_refs, run.state.tick + 24,
        )
    else:
        old = projection.handoffs.get(proposal.target_id)
        if old is None or old.recipient_id != proposal.actor_id or old.status != "proposed":
            raise ValueError("only recipient may answer a pending handoff")
        origin = next(e for e in reversed(run.events)
                      if e.event_type is EventType.RESPONSIBILITY_UPDATED
                      and e.data["handoff"]["handoff_id"] == old.handoff_id)
        record = replace(
            old, status="accepted" if proposal.verb is ActionVerb.ACCEPT else "rejected",
            source_refs=tuple(dict.fromkeys((*proposal.source_refs, f"event:{origin.sequence}"))),
        )
    return write_handoff(run, record, proposal.actor_id, action=action)


def settle_handoffs(run):
    projection = community_projection(run)
    for record in projection.handoffs.pending():
        if record.status != "proposed" or run.state.tick <= record.deadline_tick:
            continue
        origin = run.events[projection.social_origins[("handoff", record.handoff_id, "proposed")]]
        write_handoff(run, replace(record, status="expired", source_refs=(f"event:{origin.sequence}",)),
                      record.sender_id, system=True)
