"""Durable attempts and responses; uncertain calls are never silently retried."""

from dataclasses import asdict

from engine.contracts.community import ActionProposal, ActionVerb
from engine.runtime.kernel.events import EventPersistenceError, EventType, EventValidationError
from engine.runtime.simulation.community_events import commit


def prepare_model_policy(run, policy):
    config = {"max_requests": policy.max_requests, "timeout_seconds": policy.timeout_seconds}
    index = getattr(getattr(run, "log", None), "_validation_index", None)
    if index is not None:
        if index.model_request_count and index.model_budget != config:
            raise ValueError("persisted model decision budget differs from requested configuration")
        pending = {}
        for key, (_, response) in reversed(index.pending_model_attempts.items()):
            if response is None:
                raise ValueError("unresolved model attempt: call outcome is uncertain; refusing automatic retry")
            if key[0] != run.state.tick:
                raise ValueError("cached response belongs to an unfinished earlier tick")
            pending[key] = response
        policy.requests = index.model_request_count
        policy.pending_responses = pending
        return
    completed = set()
    responses = {}
    pending = {}
    count = 0
    # A result must follow its own request, not just share an actor and tick.
    for event in reversed(run.events):
        key = event.tick, event.actor_id
        if event.delta.actions or event.event_type is EventType.ACTION_REJECTED:
            completed.add(key)
        if event.event_type is EventType.MODEL_DECISION_RESOLVED:
            responses[key] = event.data["model_response"]
        if event.event_type is EventType.MODEL_DECISION_REQUESTED:
            if event.data["model_budget"] != config:
                raise ValueError("persisted model decision budget differs from requested configuration")
            if key not in completed:
                if key not in responses:
                    raise ValueError("unresolved model attempt: call outcome is uncertain; refusing automatic retry")
                if event.tick != run.state.tick:
                    raise ValueError("cached response belongs to an unfinished earlier tick")
                pending[key] = responses[key]
            count += 1
    policy.requests = count
    policy.pending_responses = pending


def request_model_decision(run, policy, context):
    if policy.requests >= policy.max_requests:
        raise RuntimeError("community model request budget exhausted")
    source = f"perception:{context.actor_id}:{run.state.tick}:{context.perception.location_id}"
    return commit(
        run, EventType.MODEL_DECISION_REQUESTED, actor_id=context.actor_id, observers=(context.actor_id,),
        data={"model_budget": {"max_requests": policy.max_requests, "timeout_seconds": policy.timeout_seconds},
              "request_index": policy.requests + 1, "summary": "bounded model decision requested"},
        sources=(source,), commit_id=f"model-request:{context.actor_id}:{run.state.tick}",
    )


def resolved_model_decision(run, policy, context):
    key = run.state.tick, context.actor_id
    response = policy.pending_responses.get(key)
    if response is None:
        request = request_model_decision(run, policy, context)
        try:
            proposal = policy.propose(context)
            response = {"request_sequence": request.sequence, "proposal": asdict(proposal), "error": None}
            sources = tuple(dict.fromkeys((f"event:{request.sequence}", *proposal.source_refs)))
            if len(sources) > 16:
                sources = proposal.source_refs
        except (ValueError, TimeoutError, RuntimeError) as exc:
            error = str(exc)[:500].encode("utf-8", errors="backslashreplace").decode("utf-8")[:500]
            response = {"request_sequence": request.sequence, "proposal": None,
                        "error": error if error.strip() else type(exc).__name__}
            sources = (f"event:{request.sequence}",)
        try:
            commit(
                run, EventType.MODEL_DECISION_RESOLVED, actor_id=context.actor_id, observers=(context.actor_id,),
                data={"model_response": response}, sources=sources,
                commit_id=f"model-response:{context.actor_id}:{run.state.tick}",
            )
        except EventPersistenceError:
            raise
        except EventValidationError as exc:
            if response["proposal"] is None:
                raise
            detail = f"{exc}; proposed source_refs={proposal.source_refs!r}"
            response = {"request_sequence": request.sequence, "proposal": None,
                        "error": detail[:500]}
            commit(
                run, EventType.MODEL_DECISION_RESOLVED, actor_id=context.actor_id, observers=(context.actor_id,),
                data={"model_response": response}, sources=(f"event:{request.sequence}",),
                commit_id=f"model-response:{context.actor_id}:{run.state.tick}",
            )
    if response["error"] is not None:
        raise ValueError(response["error"])
    raw = response["proposal"]
    return ActionProposal(**{**raw, "verb": ActionVerb(raw["verb"]), "source_refs": tuple(raw["source_refs"])})
