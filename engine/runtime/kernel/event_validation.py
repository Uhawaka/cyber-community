"""Source and visibility validation for cognitive community events."""

from __future__ import annotations

from typing import Any


def validate_versioned_event(event, events, state, community=None, world=None, *, index=None):
    kinds = {
        "activity_started", "activity_finished", "cognition_recorded", "goal_updated", "plan_updated", "intent_plan_updated",
        "commitment_updated", "exchange_updated", "request_updated", "responsibility_updated",
        "process_settled", "organization_recorded", "organization_read", "loan_updated", "membership_updated",
        "community_tick", "model_decision_requested", "model_decision_resolved",
        "organization_role_updated", "organization_censured", "lease_updated",
    }
    if (event.event_type.value in kinds or event.data.get("runtime_version") == "community-runtime/v1"
            or "intent_step" in event.data):
        validate_community_event(event, events, state, community, world, index=index)


def validate_memory_consolidation(event: Any, events: tuple) -> None:
    from engine.runtime.kernel.events import EventValidationError

    required = {"source_sequences", "target_tier", "belief_type", "confidence", "summary"}
    if not required.issubset(event.data):
        raise EventValidationError("memory consolidation is missing typed fields")
    sources = tuple(event.data["source_sequences"])
    if not sources or any(
        isinstance(sequence, bool) or not isinstance(sequence, int)
        for sequence in sources
    ):
        raise EventValidationError("memory consolidation requires source sequences")
    if event.data["target_tier"] not in {"semantic", "core"}:
        raise EventValidationError("memory target tier must be semantic or core")
    if event.data["belief_type"] not in {"fact", "inference", "misbelief"}:
        raise EventValidationError("memory belief type is invalid")
    confidence = event.data["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise EventValidationError("memory confidence must be between zero and one")
    if not isinstance(event.data["summary"], str) or not event.data["summary"].strip():
        raise EventValidationError("memory consolidation requires a summary")
    for sequence in sources:
        if sequence < 0 or sequence >= len(events):
            raise EventValidationError("memory source must reference a prior event")
        if not set(event.observers).issubset(set(events[sequence].observers)):
            raise EventValidationError("memory source must be visible to every observer")


def validate_community_event(event: Any, events, state: Any, community=None, world=None, *, index=None) -> None:
    from engine.contracts.community import Activity, ActionVerb, COMMUNITY_RUNTIME_VERSION
    from engine.runtime.kernel.events import EventValidationError, EventType

    if event.data.get("runtime_version") != COMMUNITY_RUNTIME_VERSION:
        raise EventValidationError("community event requires a supported runtime version")
    if event.event_type is EventType.RUN_CREATED:
        return
    commit_id = event.data.get("commit_id")
    duplicate = commit_id in index.commit_ids if index is not None and isinstance(commit_id, str) else any(
        prior.data.get("commit_id") == commit_id for prior in events)
    if not isinstance(commit_id, str) or not commit_id.strip() or duplicate:
        raise EventValidationError("community commit id must be non-empty and unique")
    from engine.runtime.kernel.community_intent_plan_validation import validate_intent_plan, validate_linked_action
    validate_linked_action(event, events, state, world)
    deadline_clock_source = None
    if event.event_type is EventType.INTENT_PLAN_UPDATED:
        validate_intent_plan(event, events)
        from engine.runtime.kernel.community_intent_plan_validation import latest_plan
        plan = event.data["intent_plan"]
        prior = latest_plan(events, plan["plan_id"])
        if (prior is not None and not prior.data["intent_plan"].get("deadline_reached", False)
                and plan.get("deadline_reached") is True):
            deadline_clock_source = plan["source_refs"][-1]
    if event.event_type is EventType.ACTIVITY_STARTED:
        try:
            raw = event.data["activity"]
            activity = Activity(**{
                **raw, "verb": ActionVerb(raw["verb"]),
                "source_refs": tuple(raw["source_refs"]),
            })
        except (ValueError, TypeError, KeyError) as exc:
            raise EventValidationError("invalid activity record") from exc
        if activity.actor_id != event.actor_id or activity.started_tick != state.tick:
            raise EventValidationError("activity must start now and belong to actor")
        if tuple(event.data.get("source_refs", ())) != activity.source_refs:
            raise EventValidationError("activity sources must match event")
        from engine.runtime.kernel.community_material_validation import validate_repair_materials
        validate_repair_materials(event, activity, state, community)
        from engine.runtime.kernel.community_learning_validation import validate_learning_start
        validate_learning_start(event, activity, events, state, community, world)
        starts = index.activity_starts if index is not None else {
            prior.data["activity"]["activity_id"]: prior
            for prior in events if prior.event_type is EventType.ACTIVITY_STARTED
        }
        finished = index.activity_finishes if index is not None else {
            prior.data.get("activity_id") for prior in events
            if prior.event_type is EventType.ACTIVITY_FINISHED
        }
        occupied = activity.actor_id in index.pending_actors if index is not None else any(
            prior.actor_id == activity.actor_id and key not in finished for key, prior in starts.items())
        if activity.activity_id in starts or occupied:
            raise EventValidationError("actor already has a pending activity")
    if event.event_type is EventType.ACTIVITY_FINISHED:
        activity_id = event.data.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id:
            raise EventValidationError("activity completion requires a pending activity id")
        started = index.activity_starts.get(activity_id) if index is not None else next((
            prior for prior in events
            if prior.event_type is EventType.ACTIVITY_STARTED
            and prior.data["activity"]["activity_id"] == activity_id
        ), None)
        completed = activity_id in index.activity_finishes if index is not None else any(
            prior.event_type is EventType.ACTIVITY_FINISHED and prior.data.get("activity_id") == activity_id
            for prior in events)
        if started is None or started.actor_id != event.actor_id or completed:
            raise EventValidationError("activity completion requires pending owned activity")
        if event.data.get("status") not in {"completed", "cancelled", "failed"}:
            raise EventValidationError("invalid activity completion status")
        from engine.runtime.kernel.community_material_validation import validate_repair_completion
        validate_repair_completion(event, started, state, community)
        from engine.runtime.kernel.community_learning_validation import validate_learning_completion
        validate_learning_completion(event, started, state, community)
        if event.data["status"] == "completed" and state.tick < started.data["activity"]["due_tick"]:
            raise EventValidationError("activity cannot finish before due time")
        from engine.runtime.kernel.community_intent_plan_validation import validate_linked_finish
        validate_linked_finish(event, started, state, world)
        if event.data.get("learned_skill") and (
            started.data["activity"]["verb"] != "learn" or event.data["status"] != "completed"
            or not isinstance(event.data["learned_skill"], str)
        ):
            raise EventValidationError("skill acquisition requires completed learning activity")
    if event.event_type is EventType.REQUEST_UPDATED:
        from engine.runtime.kernel.community_request_validation import validate_request
        validate_request(event, events, state, community)
    if event.event_type is EventType.LOAN_UPDATED:
        from engine.runtime.kernel.community_loan_validation import validate_loan
        validate_loan(event, events, state)
    if event.event_type is EventType.LEASE_UPDATED:
        from engine.runtime.kernel.community_lease_validation import validate_lease
        validate_lease(event, events, state, world)
    if event.event_type is EventType.MEMBERSHIP_UPDATED:
        from engine.runtime.kernel.community_membership_validation import validate_membership_change
        validate_membership_change(event, events, state, community, index)
    if event.event_type is EventType.ORGANIZATION_ROLE_UPDATED:
        from engine.runtime.kernel.community_role_validation import validate_role
        validate_role(event, events, state, community, world, index)
    if event.event_type is EventType.ORGANIZATION_CENSURED:
        from engine.runtime.kernel.community_censure_validation import validate_censure
        validate_censure(event, events, state, community, index)
    if event.event_type is EventType.MODEL_DECISION_REQUESTED:
        from engine.runtime.kernel.community_model_validation import validate_model_request
        validate_model_request(event, events, state, index)
    if event.event_type is EventType.MODEL_DECISION_RESOLVED:
        from engine.runtime.kernel.community_model_validation import validate_model_response
        validate_model_response(event, events, state, index)
    if event.event_type is EventType.RESPONSIBILITY_UPDATED:
        from engine.runtime.kernel.community_handoff_validation import validate_handoff
        validate_handoff(event, events, state, community, world)
    if event.event_type in {EventType.ORGANIZATION_RECORDED, EventType.ORGANIZATION_READ}:
        from engine.runtime.kernel.community_organization_validation import validate_organization_record
        validate_organization_record(event, events, state, community, world, index)
    if event.event_type in {
        EventType.COGNITION_RECORDED, EventType.GOAL_UPDATED, EventType.PLAN_UPDATED,
    } and (event.actor_id is None or event.observers != (event.actor_id,)):
        raise EventValidationError("private cognition must be owned by its sole observer")
    if event.event_type in {EventType.GOAL_UPDATED, EventType.PLAN_UPDATED}:
        from engine.runtime.kernel.community_goal_validation import validate_goal_event
        validate_goal_event(event, events, state)
    if event.event_type in {EventType.COMMITMENT_UPDATED, EventType.EXCHANGE_UPDATED}:
        from engine.runtime.kernel.community_society_validation import validate_society_event
        validate_society_event(event, events, state)
    if event.event_type is EventType.COGNITION_RECORDED:
        from engine.contracts.cognition import KnowledgeClaim, MemoryRecord
        try:
            records = []
            for raw in event.data.get("memories", ()):
                record = MemoryRecord(**{
                    **raw, **{key: tuple(raw.get(key, ())) for key in (
                        "source_refs", "participants", "entity_ids", "topics",
                    )},
                })
                records.append(record)
            for raw in event.data.get("claims", ()):
                claim = KnowledgeClaim(**{
                    **raw, "source_refs": tuple(raw["source_refs"]),
                    "contradicts": tuple(raw.get("contradicts", ())),
                })
                from engine.runtime.kernel.community_claim_validation import validate_claim
                validate_claim(claim, event, events, index)
                records.append(claim)
            if not records or len(records) > 16 or any(r.owner_id != event.actor_id for r in records):
                raise ValueError("cognition must contain bounded owned records")
            if any(not set(r.source_refs) <= set(event.data.get("source_refs", ())) for r in records):
                raise ValueError("cognition record sources do not match event")
        except EventValidationError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise EventValidationError("invalid private cognition records") from exc
    sources = event.data.get("source_refs", ())
    if not isinstance(sources, (tuple, list)) or len(sources) > 16:
        raise EventValidationError("invalid community sources")
    for source in sources:
        if not isinstance(source, str):
            raise EventValidationError("invalid source reference")
        if source.startswith("event:"):
            try:
                sequence = int(source.split(":", 1)[1])
            except ValueError as exc:
                raise EventValidationError("invalid event source") from exc
            if not 0 <= sequence < len(events):
                raise EventValidationError("source must reference a prior event")
            origin = events[sequence]
            from engine.runtime.kernel.community_process_validation import process_source_allowed
            if event.actor_id is None and event.event_type is EventType.PROCESS_SETTLED:
                if not process_source_allowed(event, origin, state):
                    raise EventValidationError("process source must change its material or service dependencies")
            elif source == deadline_clock_source:
                continue
            elif event.actor_id not in origin.observers and event.actor_id != origin.actor_id:
                raise EventValidationError("source is not visible to actor")
        elif source.startswith("soul:"):
            if not source.startswith(f"soul:{event.actor_id}:"):
                raise EventValidationError("another character's soul is private")
        elif source.startswith("seed:"):
            parts = source.split(":", 2)
            if len(parts) != 3 or parts[1] != event.actor_id or f"{parts[1]}:memory:{parts[2]}" not in state.facts:
                raise EventValidationError("seed source is not owned by actor")
        elif source.startswith("public:"):
            number = source.removeprefix("public:")
            if (community is None or not number.isascii() or not number.isdigit()
                    or len(number) > 2 or source != f"public:{int(number)}"
                    or int(number) >= len(community.public_knowledge)):
                raise EventValidationError("unknown public knowledge source")
        elif source.startswith("perception:"):
            prefix = f"perception:{event.actor_id}:{state.tick}:"
            if not source.startswith(prefix):
                raise EventValidationError("perception source must be current and owned")
            target = source[len(prefix):]
            actor = state.characters[event.actor_id]
            entity = state.entities.get(target)
            target_location = (
                actor.location_id if state.inventories[event.actor_id].get(target, 0) > 0 else
                state.characters[target].location_id if target in state.characters
                else entity.components.get("attributes", {}).get("location_id") if entity
                else target if target in state.location_ids else None
            )
            if target_location != actor.location_id:
                raise EventValidationError("perception source is not at actor location")
        else:
            raise EventValidationError("unsupported source reference")
    if event.event_type is EventType.DIALOGUE:
        from engine.runtime.kernel.community_claim_validation import validate_report
        if not isinstance(event.data.get("utterance"), str) or not event.data["utterance"].strip():
            raise EventValidationError("speech requires non-empty bounded text")
        actor = state.characters.get(event.actor_id)
        if "organization_id" in event.data or "participant_ids" in event.data:
            from engine.runtime.kernel.community_claim_validation import validate_group_speech
            validate_group_speech(event, state, community, events, index)
        else:
            listener = state.characters.get(event.data.get("listener_id"))
            if actor is None or listener is None or not listener.active or listener.location_id != actor.location_id:
                raise EventValidationError("speech requires a locally reachable listener")
        expected = tuple(sorted(
            key for key, person in state.characters.items()
            if person.active and person.location_id == actor.location_id
        ))
        if event.observers != expected or len(event.data["utterance"]) > 2000:
            raise EventValidationError("speech audience or size does not match local reach")
        validate_report(event, events, state, world, index, community=community)
    if event.event_type is EventType.PROCESS_SETTLED:
        try:
            if event.data.get("service_dependencies"):
                from engine.runtime.kernel.community_process_validation import process_dependencies
                devices, _, _ = process_dependencies(event, state)
                if event.data["status"] == "settled" and any(
                    state.entities[device_id].components["attributes"]["condition"] < threshold
                    for device_id, threshold in devices
                ):
                    raise ValueError("unavailable service cannot produce output")
                finished = index.activity_finishes if index is not None else {e.data.get("activity_id") for e in events
                            if e.event_type is EventType.ACTIVITY_FINISHED}
                reserved = bool(set(dict(devices)) & index.pending_repairs) if index is not None else any(
                    e.event_type is EventType.ACTIVITY_STARTED
                    and e.data["activity"]["verb"] == "repair"
                    and e.data["activity"]["target_id"] in dict(devices)
                    and e.data["activity"]["activity_id"] not in finished for e in events)
                if event.data["status"] == "settled" and reserved:
                    raise ValueError("reserved service cannot produce output")
            expected = tuple((q.item_id, q.amount) for q in event.delta.resources)
            actual = tuple(tuple(row) for row in event.data["ledger"])
            if event.actor_id is not None or expected != actual:
                raise ValueError("process ledger must match authoritative material delta")
            if event.data["status"] not in {"settled", "paused", "blocked"}:
                raise ValueError("invalid process status")
            if event.data["status"] != "settled" and (
                event.delta.resources or event.delta.entity_patches
            ):
                raise ValueError("blocked process cannot change materials or devices")
            if event.delta.inventories or event.delta.knowledge or event.delta.actions:
                raise ValueError("process cannot act for a character")
        except (ValueError, TypeError, KeyError) as exc:
            raise EventValidationError("invalid process settlement") from exc
