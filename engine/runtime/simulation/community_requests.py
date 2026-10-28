"""Material requests solicit help; only consented deliveries change custody."""

from dataclasses import asdict, replace

from engine.contracts.community import ActionVerb
from engine.contracts.society import MaterialRequest
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def write_request(run, request, actor_id, *, action=None, system=False):
    parties = tuple(sorted(p for p in (request.requester_id, request.helper_id)
                           if run.state.characters[p].active))
    return commit(
        run, EventType.REQUEST_UPDATED, actor_id=actor_id, observers=parties,
        delta=Delta(actions=(action,)) if action else None,
        data={"request": asdict(request), "system_update": system,
              "summary": f"material request {request.item_id} for {request.purpose_id}: {request.status}"},
        sources=request.source_refs, commit_id=f"request:{request.request_id}:{request.status}",
        target_id=request.purpose_id,
    )


def begin_request(run, proposal, context):
    requests = community_projection(run).requests
    action = ActionRecord(proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick)
    if proposal.verb is ActionVerb.REQUEST:
        people = {e.entity_id for e in context.perception.entities if e.kind == "character"}
        if proposal.target_id not in people:
            raise ValueError("request requires a locally reachable helper")
        repair = next((o for o in context.operations if o.verb is ActionVerb.REPAIR
                       and o.target_id == proposal.reply_to), None)
        if repair is None or proposal.item_id not in dict(repair.inputs):
            raise ValueError("request requires a known repair and registered input")
        if any(r.requester_id == proposal.actor_id and r.item_id == proposal.item_id
               and r.purpose_id == proposal.reply_to and r.status == "open" for r in requests.values()):
            raise ValueError("an equivalent request is already open")
        request = MaterialRequest(
            proposal.proposal_id, proposal.actor_id, proposal.target_id,
            proposal.item_id, proposal.quantity, proposal.reply_to,
            proposal.source_refs, run.state.tick + 24,
        )
    else:
        request = requests.get(proposal.target_id)
        if request is None or request.helper_id != proposal.actor_id or request.status != "open":
            raise ValueError("only addressed helper may decline an open request")
        origin = next(e for e in run.events if e.event_type is EventType.REQUEST_UPDATED
                      and e.data["request"]["request_id"] == request.request_id)
        request = replace(request, status="declined", source_refs=(f"event:{origin.sequence}",))
    return write_request(run, request, proposal.actor_id, action=action)


def settle_requests(run):
    projection = community_projection(run)
    for request in projection.requests.pending():
        origin = run.events[projection.social_origins[("request", request.request_id, "open")]]
        delivery = projection.outcomes.delivery(request, origin.sequence, run.events)
        if delivery or run.state.tick > request.deadline_tick:
            write_request(
                run, replace(request, status="fulfilled" if delivery else "expired",
                             source_refs=(f"event:{origin.sequence}", *(
                                 (f"event:{delivery.sequence}",) if delivery else ()
                             ))),
                request.requester_id, system=True,
            )
