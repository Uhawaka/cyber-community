"""Durable attempts and responses; uncertain calls are never silently retried."""

from concurrent.futures import ThreadPoolExecutor
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


def decide_model_wave(run, policy, contexts):
    """Ask every due character from the same snapshot, then commit in that order.

    People present together do not wait for one another's model call. The request
    records are written first, so a crash still refuses to retry an uncertain call.
    """
    jobs = []
    for context in contexts:
        key = run.state.tick, context.actor_id
        cached = getattr(policy, "pending_responses", {}).get(key)
        if cached is not None:
            jobs.append((context, None, cached))
            continue
        try:
            request = request_model_decision(run, policy, context)
        except RuntimeError as exc:
            jobs.append((context, None, {"error": str(exc)}))
            continue
        policy.requests += 1
        jobs.append((context, request, None))

    def fetch(job):
        context, _request, cached = job
        if cached is not None:
            return None
        try:
            return ("ok", policy.complete(context))
        except (ValueError, TimeoutError, RuntimeError) as exc:
            return ("err", exc)

    pending = [job for job in jobs if job[2] is None]
    if pending:
        with ThreadPoolExecutor(max_workers=len(pending)) as pool:
            fetched = list(pool.map(fetch, jobs))
    else:
        fetched = [None] * len(jobs)
    outcomes = []
    for (context, request, cached), result in zip(jobs, fetched):
        if cached is not None:
            response, proposal = cached, None
            if response.get("error") is not None:
                outcomes.append((context, None, ValueError(response["error"])))
                continue
        else:
            response, proposal = _response_from_call(policy, context, request, result)
            _commit_model_response(run, context, request, response, proposal)
            if response["error"] is not None:
                outcomes.append((context, None, ValueError(response["error"])))
                continue
        if proposal is None:
            raw = response["proposal"]
            proposal = ActionProposal(**{**raw, "verb": ActionVerb(raw["verb"]),
                                         "source_refs": tuple(raw["source_refs"])})
        outcomes.append((context, proposal, None))
    return outcomes


def _response_from_call(policy, context, request, result):
    if result[0] == "err":
        exc = result[1]
        error = str(exc)[:500].encode("utf-8", errors="backslashreplace").decode("utf-8")[:500]
        response = {"request_sequence": request.sequence, "proposal": None,
                    "error": error if error.strip() else type(exc).__name__}
        return response, None
    try:
        proposal = policy.interpret(context, result[1])
    except (ValueError, TimeoutError, RuntimeError) as exc:
        error = str(exc)[:500].encode("utf-8", errors="backslashreplace").decode("utf-8")[:500]
        response = {"request_sequence": request.sequence, "proposal": None,
                    "error": error if error.strip() else type(exc).__name__}
        return response, None
    response = {"request_sequence": request.sequence, "proposal": asdict(proposal), "error": None}
    return response, proposal


def _commit_model_response(run, context, request, response, proposal):
    sources = (f"event:{request.sequence}",) if response["proposal"] is None else tuple(
        dict.fromkeys((f"event:{request.sequence}", *proposal.source_refs)))
    if len(sources) > 16 and proposal is not None:
        sources = proposal.source_refs
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
        response = {"request_sequence": request.sequence, "proposal": None, "error": detail[:500]}
        commit(
            run, EventType.MODEL_DECISION_RESOLVED, actor_id=context.actor_id, observers=(context.actor_id,),
            data={"model_response": response}, sources=(f"event:{request.sequence}",),
            commit_id=f"model-response:{context.actor_id}:{run.state.tick}",
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
