"""A model request is a private budget fact, never an action or world result."""

import math


def validate_model_request(event, events, state, index=None):
    from engine.runtime.kernel.events import Delta, EventValidationError
    try:
        config = event.data["model_budget"]
        if set(config) != {"max_requests", "timeout_seconds"}:
            raise ValueError("unknown or missing model budget settings")
        maximum, timeout = config["max_requests"], config["timeout_seconds"]
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 100000:
            raise ValueError("model request limit must be a bounded integer")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 600):
            raise ValueError("model timeout must be bounded and finite")
        prior = ([e for e in events if e.event_type.value == "model_decision_requested"]
                 if index is None else None)
        changed = (any(e.data["model_budget"] != config for e in prior) if prior is not None else
                   index.model_request_count > 0 and index.model_budget != config)
        if changed:
            raise ValueError("model budget settings cannot change mid-history")
        request_index = event.data["request_index"]
        count = len(prior) if prior is not None else index.model_request_count
        if (isinstance(request_index, bool) or not isinstance(request_index, int)
                or request_index != count + 1 or request_index > maximum):
            raise ValueError("model request index exceeds the persisted budget")
        actor = state.characters.get(event.actor_id)
        if actor is None or not actor.active or event.observers != (event.actor_id,) or event.delta != Delta():
            raise ValueError("model request must be a private active-actor budget record")
        already_decided = (
            (event.actor_id, state.tick) in index.decision_requests_or_actions if index is not None else
            any(e.tick == state.tick and e.actor_id == event.actor_id
                and (e.delta.actions or e.event_type.value in {"model_decision_requested", "action_rejected"})
                for e in events)
        )
        if already_decided:
            raise ValueError("actor has already requested or completed a decision this tick")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid model request: " + str(exc)) from exc


def validate_model_response(event, events, state, index=None):
    from engine.contracts.community import ActionProposal, ActionVerb
    from engine.runtime.kernel.events import Delta, EventValidationError
    try:
        response = event.data["model_response"]
        if set(response) != {"request_sequence", "proposal", "error"}:
            raise ValueError("response requires closed typed fields")
        sequence = response["request_sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or not 0 <= sequence < len(events):
            raise ValueError("response requires a prior request")
        request = events[sequence]
        if (request.event_type.value != "model_decision_requested"
                or request.actor_id != event.actor_id or request.tick != state.tick):
            raise ValueError("response must belong to this actor and tick")
        if event.observers != (event.actor_id,) or event.delta != Delta():
            raise ValueError("model response is a private no-effect record")
        already_resolved = (
            index.decision_responses_or_actions.get((event.actor_id, state.tick), -1) > sequence
            if index is not None else
            any(prior.tick == state.tick and prior.actor_id == event.actor_id
                and (prior.delta.actions or prior.event_type.value in {"action_rejected", "model_decision_resolved"})
                for prior in events[sequence + 1:])
        )
        if already_resolved:
            raise ValueError("request already resolved or acted")
        error, raw = response["error"], response["proposal"]
        if raw is None:
            if not isinstance(error, str) or not error.strip() or len(error) > 500:
                raise ValueError("failed response requires bounded error")
        else:
            if error is not None:
                raise ValueError("response cannot contain both proposal and error")
            proposal = ActionProposal(**{**raw, "verb": ActionVerb(raw["verb"]),
                                         "source_refs": tuple(raw["source_refs"])})
            if (proposal.actor_id != event.actor_id or proposal.expected_state_hash != state.state_hash()
                    or proposal.proposal_id != f"decision:{event.actor_id}:{state.tick}"
                    or not set(proposal.source_refs) <= set(event.data["source_refs"])):
                raise ValueError("model response proposal must bind actor, state and sources")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise EventValidationError("invalid model response: " + str(exc)) from exc
