"""Versioned community loop shared by model and offline decision policies."""

from __future__ import annotations

from dataclasses import asdict, replace

from engine.contracts.community import (
    ActionProposal, ActionVerb, Activity, MINUTES_PER_TICK,
)
from engine.runtime.character.community_context import decision_context, decision_source_refs
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventPersistenceError, EventType, MoveDelta, NeedDelta
from engine.runtime.simulation.community_events import commit, open_tick, present
from engine.runtime.simulation.observability import _TickUsage, _tick_report


class RestOrWaitPolicy:
    """Conservative bootstrap policy; life goals are added in R08."""

    def propose(self, context):
        fatigue = dict(context.needs).get("fatigue", 0)
        verb = ActionVerb.REST if fatigue >= 60 else ActionVerb.WAIT
        source = f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}"
        return ActionProposal(
            f"decision:{context.actor_id}:{context.perception.tick}", context.actor_id,
            verb, context.actor_id, "recover energy" if fatigue >= 60 else "wait",
            (source,), context.state_hash,
        )


def run_community_catchup(run, requested_ticks, *, max_ticks=None, action_budget=None):
    """Advance only detailed community ticks, deferring any over the limit."""
    limit = 24 if max_ticks is None else max_ticks
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in (requested_ticks, limit)):
        raise ValueError("community catchup limits must be non-negative integers")
    permitted = min(requested_ticks, limit)
    report = run_community_ticks(run, permitted, action_budget=action_budget)
    return replace(
        report, requested_ticks=requested_ticks,
        truncated_ticks=requested_ticks - permitted,
        budget_exhausted=report.budget_exhausted or requested_ticks > permitted,
    )


def run_managed_community_ticks(run, count, *, decision_policy=None, action_budget=None, memory_budget=None):
    """Run only histories that bind their policy and budgets in the creation event."""
    try:
        creation = run.log.event_at(0)
    except IndexError as exc:
        raise ValueError("run has no persisted community configuration") from exc
    if "community_config" not in creation.data:
        raise ValueError("run has no persisted community configuration")
    return run_community_ticks(run, count, decision_policy=decision_policy,
                               action_budget=action_budget, memory_budget=memory_budget)


def run_community_ticks(run, count, *, decision_policy=None, action_budget=None, memory_budget=None):
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("tick count must be a non-negative integer")
    if run.compiled.community is None:
        raise ValueError("community loop requires an explicit versioned package")
    if action_budget is not None and (
        isinstance(action_budget, bool) or not isinstance(action_budget, int) or action_budget < 0
    ):
        raise ValueError("action budget must be non-negative")
    if memory_budget is not None and (
        isinstance(memory_budget, bool) or not isinstance(memory_budget, int) or memory_budget < 0
    ):
        raise ValueError("memory budget must be a non-negative integer")
    from engine.runtime.character.community_policy import CommunityLifePolicy
    from engine.runtime.simulation.community_config import resolve_community_config
    selected_policy = decision_policy if decision_policy is not None else getattr(run, "community_policy", None)
    policy, action_budget, memory_budget = resolve_community_config(
        run, selected_policy, action_budget, memory_budget,
    )
    if policy is None:
        policy = CommunityLifePolicy()
    if getattr(policy, "records_model_attempts", False):
        from engine.runtime.simulation.community_model_budget import prepare_model_policy
        prepare_model_policy(run, policy)
    start_tick = run.state.tick
    start_sequence = len(run.events)
    usage = _TickUsage()
    for _ in range(count):
        _tick(run, policy, action_budget, memory_budget, usage)
    return _tick_report(run, start_tick, start_sequence, count, count, usage)


def _tick(run, policy, budget, memory_budget, usage):
    if not open_tick(run):
        commit(
            run, EventType.COMMUNITY_TICK,
            delta=Delta(
                advance_tick=1, advance_time=MINUTES_PER_TICK,
                needs=tuple(
                    NeedDelta(actor_id, need, amount)
                    for actor_id, actor in run.state.characters.items() if actor.active
                    for need, amount in run.compiled.community.need_decay
                ),
            ),
            data={"phase": "open", "elapsed_minutes": MINUTES_PER_TICK},
            commit_id=f"tick:{run.state.tick + 1}:open",
        )
    from engine.runtime.character.community_goals import seed_desires, reconcile
    from engine.runtime.simulation.community_processes import settle_processes
    from engine.runtime.simulation.community_society import settle_society
    from engine.runtime.simulation.community_requests import settle_requests
    # Any committed decision proves preparation finished before this interruption.
    deciding = any(e.tick == run.state.tick and (
        e.delta.actions or e.event_type in {EventType.ACTION_REJECTED, EventType.MODEL_DECISION_REQUESTED}
    )
                   for e in run.log.current_tick_events())
    if not deciding:
        projection = community_projection(run)
        # Once settlement started, rerunning early reconciliation reorders history.
        settling = any(e.tick == run.state.tick and (
            e.event_type in {EventType.ACTIVITY_FINISHED, EventType.PROCESS_SETTLED}
            or e.data.get("system_update")
        ) for e in run.log.current_tick_events())
        if not settling:
            seed_desires(run)
        for activity in sorted(tuple(projection.activities.values()), key=lambda a: (a.due_tick, a.activity_id)):
            if activity.due_tick <= run.state.tick:
                _complete(run, activity)
        settle_processes(run)
        settle_society(run)
        settle_requests(run)
        reconcile(run)
        from engine.runtime.character.community_intent_plans import reconcile_intent_plans
        reconcile_intent_plans(run)
    actors = sorted(
        actor_id for actor_id, actor in run.state.characters.items()
        if actor.active and actor.participant_kind == "npc"
    )
    if actors:
        offset = (run.state.seed + run.state.tick) % len(actors)
        actors = actors[offset:] + actors[:offset]
    limit = len(actors) if budget is None else budget
    usage.action_budget += limit
    # An interrupted open tick retains the decisions already committed to its log.
    spent = sum(_acted_this_tick(run, actor_id) for actor_id in actors)
    used = 0
    if getattr(policy, "records_model_attempts", False):
        due = []
        for actor_id in actors:
            if not _claim_decision_slot(run, actor_id, spent, used, limit, usage):
                if usage.action_exhausted:
                    break
                continue
            due.append(actor_id)
            used += 1
        from dataclasses import replace
        from engine.runtime.simulation.community_model_budget import decide_model_wave
        contexts = [decision_context(run, actor_id) for actor_id in due]
        for context, proposal, error in decide_model_wave(run, policy, contexts):
            try:
                if error is not None:
                    raise error
                _start(run, replace(proposal, expected_state_hash=run.state.state_hash()), context)
            except EventPersistenceError:
                raise
            except (ValueError, TimeoutError, RuntimeError) as exc:
                _reject_decision(run, context.actor_id, proposal, exc)
    else:
        for actor_id in actors:
            if not _claim_decision_slot(run, actor_id, spent, used, limit, usage):
                if usage.action_exhausted:
                    break
                continue
            context = decision_context(run, actor_id)
            proposal = None
            try:
                proposal = policy.propose(context)
                _start(run, proposal, context)
            except EventPersistenceError:
                raise
            except (ValueError, TimeoutError, RuntimeError) as exc:
                _reject_decision(run, actor_id, proposal, exc)
            used += 1
    usage.actions_used += used
    settle_society(run)
    settle_requests(run)
    reconcile(run)
    from engine.runtime.character.community_intent_plans import reconcile_intent_plans
    reconcile_intent_plans(run)
    from engine.runtime.character.community_consolidation import consolidate
    memory_spent = sum(
        e.event_type is EventType.COGNITION_RECORDED
        and any(m.get("kind") == "reflection" for m in e.data.get("memories", ()))
        for e in run.log.current_tick_events()
    )
    memory_used, memory_pending = consolidate(run, max(0, memory_budget - memory_spent))
    usage.memory_budget += memory_budget
    usage.memory_updates_used += memory_used
    usage.memory_exhausted |= memory_pending
    commit(run, EventType.COMMUNITY_TICK, data={"phase": "closed"},
           commit_id=f"tick:{run.state.tick}:closed")
    usage.executed_workflow_steps += ("community_runtime",)


def _claim_decision_slot(run, actor_id, spent, used, limit, usage):
    from engine.runtime.character.community_goals import record_rejection
    from engine.runtime.simulation.community_schedule import awake
    if _acted_this_tick(run, actor_id):
        rejection = next((e for e in run.log.current_tick_events()
                          if e.actor_id == actor_id and e.event_type is EventType.ACTION_REJECTED), None)
        if rejection:
            record_rejection(run, actor_id, rejection)
        return False
    if community_projection(run).pending_for(actor_id) or not awake(run, actor_id):
        return False
    if spent + used >= limit:
        usage.action_exhausted = True
        return False
    return True


def _reject_decision(run, actor_id, proposal, exc):
    from engine.runtime.character.community_goals import record_rejection
    attempted = None
    if isinstance(proposal, ActionProposal) and proposal.actor_id == actor_id:
        attempted = {"verb": proposal.verb.value, "target_id": proposal.target_id,
                     "source_refs": proposal.source_refs,
                     "intent_plan_id": proposal.intent_plan_id,
                     "intent_step_index": proposal.intent_step_index}
    rejected = commit(
        run, EventType.ACTION_REJECTED, actor_id=actor_id, observers=(actor_id,),
        data={"reason": str(exc)[:500], "proposal": attempted},
        commit_id=f"decision:{actor_id}:{run.state.tick}:rejected",
    )
    record_rejection(run, actor_id, rejected)


def _acted_this_tick(run, actor_id):
    return any(
        event.actor_id == actor_id
        and (
            event.delta.actions
            or event.event_type in {EventType.ACTIVITY_STARTED, EventType.ACTION_REJECTED}
        )
        for event in run.log.current_tick_events()
    )


def _start(run, proposal, context):
    from engine.runtime.simulation.community_events import selected_intent_step
    selection = None
    if isinstance(proposal, ActionProposal) and proposal.intent_plan_id:
        if proposal.actor_id != context.actor_id:
            raise ValueError("policy may decide only for its own actor")
        from engine.runtime.character.community_intent_plans import validate_selection
        validate_selection(run, proposal)
        selection = {"plan_id": proposal.intent_plan_id, "index": proposal.intent_step_index}
    with selected_intent_step(selection):
        return _start_action(run, proposal, context)


def _start_action(run, proposal, context):
    if not isinstance(proposal, ActionProposal) or proposal.actor_id != context.actor_id:
        raise ValueError("policy may decide only for its own actor")
    if proposal.expected_state_hash != run.state.state_hash():
        raise ValueError("stale action proposal")
    if not set(proposal.source_refs) <= decision_source_refs(context):
        raise ValueError("decision cites inaccessible knowledge")
    if proposal.verb is ActionVerb.PLAN:
        from engine.runtime.character.community_intent_plans import create_intent_plan
        return create_intent_plan(run, proposal)
    if proposal.verb is ActionVerb.ABANDON_PLAN:
        from engine.runtime.character.community_intent_plans import abandon_intent_plan
        return abandon_intent_plan(run, proposal)
    if proposal.verb is ActionVerb.BRANCH_PLAN:
        from engine.runtime.character.community_intent_plans import branch_intent_plan
        return branch_intent_plan(run, proposal)
    place = run.state.characters[proposal.actor_id].location_id
    if proposal.verb in {ActionVerb.LEASE, ActionVerb.RETURN_LEASE} or (
        proposal.verb in {ActionVerb.ACCEPT, ActionVerb.REJECT}
        and any(record.lease_id == proposal.target_id for record in context.leases)
    ):
        from engine.runtime.simulation.community_leases import lease_action
        return lease_action(run, proposal, context)
    if proposal.verb in {ActionVerb.TAKE_ROLE, ActionVerb.LEAVE_ROLE, ActionVerb.CENSURE}:
        from engine.runtime.simulation.community_roles import role_action
        return role_action(run, proposal, context)
    if proposal.verb in {ActionVerb.LEND, ActionVerb.REPAY} or (
        proposal.verb in {ActionVerb.ACCEPT, ActionVerb.REJECT}
        and any(r.loan_id == proposal.target_id for r in context.loans)
    ):
        from engine.runtime.simulation.community_loans import loan_action
        return loan_action(run, proposal, context)
    if proposal.verb in {ActionVerb.RECORD, ActionVerb.READ, ActionVerb.RESIGN, ActionVerb.JOIN, ActionVerb.INVITE}:
        from engine.runtime.simulation.community_organizations import organization_action
        return organization_action(run, proposal, context)
    if proposal.verb in {ActionVerb.PURSUE, ActionVerb.ABANDON}:
        from engine.runtime.character.community_goals import pursue
        return pursue(run, proposal, context)
    if proposal.verb is ActionVerb.HANDOFF or proposal.verb in {ActionVerb.ACCEPT, ActionVerb.REJECT} and any(
        h.handoff_id == proposal.target_id for h in context.handoffs
    ):
        from engine.runtime.simulation.community_handoffs import begin_handoff
        return begin_handoff(run, proposal)
    if proposal.verb is ActionVerb.REQUEST or proposal.verb is ActionVerb.REJECT and any(
        request.request_id == proposal.target_id for request in context.requests
    ):
        from engine.runtime.simulation.community_requests import begin_request
        return begin_request(run, proposal, context)
    if proposal.verb in {ActionVerb.OFFER, ActionVerb.TRANSFER, ActionVerb.ACCEPT,
                         ActionVerb.REJECT, ActionVerb.COMMIT}:
        from engine.runtime.simulation.community_society import begin_social_action
        return begin_social_action(run, proposal, context)
    if proposal.verb is ActionVerb.SPEAK:
        from engine.runtime.simulation.community_dialogue import speak
        return speak(run, proposal, context)
    if proposal.verb in {ActionVerb.WAIT, ActionVerb.REST}:
        if proposal.target_id != proposal.actor_id:
            raise ValueError("rest/wait must target self")
        needs = (NeedDelta(proposal.actor_id, "fatigue", -18),) if proposal.verb is ActionVerb.REST else ()
        commit(
            run, EventType.RESTED if needs else EventType.WAITED,
            actor_id=proposal.actor_id, observers=present(run, place),
            delta=Delta(needs=needs, actions=(
                ActionRecord(proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick),
            )),
            data={"summary": proposal.intent, "proposal_id": proposal.proposal_id},
            commit_id=f"decision:{proposal.actor_id}:{run.state.tick}",
            target_id=proposal.target_id, sources=proposal.source_refs,
        )
        return
    if proposal.verb is not ActionVerb.MOVE:
        from engine.runtime.simulation.community_objects import begin_object_action
        return begin_object_action(run, proposal, context, _start_activity)
    passage = next((p for p in run.compiled.world.passages if p.id == proposal.target_id), None)
    if passage is None or passage.id not in context.perception.known_routes:
        raise ValueError("unknown or inaccessible route")
    destination = next(p for p in run.compiled.world.locations if p.id == passage.destination_id)
    authored = next(c for c in run.compiled.world.characters if c.id == proposal.actor_id)
    profile = dict(authored.profile)
    properties = dict(passage.properties)
    if properties.get("allowed_roles") and authored.role not in properties["allowed_roles"]:
        raise ValueError("route role restriction")
    if not set(properties.get("required_skills", ())) <= set(context.skills):
        raise ValueError("route requires unavailable skills")
    tags = set(profile.get("access_tags", ()))
    if not set(properties.get("required_access_tags", ())) <= tags or not set(destination.access_tags) <= tags:
        raise ValueError("route or destination requires unavailable access")
    if destination.allowed_roles and authored.role not in destination.allowed_roles:
        raise ValueError("destination role restriction")
    activity = Activity(
        proposal.proposal_id, proposal.actor_id, proposal.verb, passage.id,
        run.state.tick, run.state.tick + passage.travel_time, proposal.source_refs,
    )
    _start_activity(run, activity, proposal.intent)


def _start_activity(run, activity, intent, *, delta=None, data=None):
    place = run.state.characters[activity.actor_id].location_id
    delta = replace(delta or Delta(), actions=(
        ActionRecord(activity.actor_id, activity.verb.value, activity.target_id, run.state.tick),
    ))
    commit(
        run, EventType.ACTIVITY_STARTED, actor_id=activity.actor_id,
        observers=present(run, place), delta=delta,
        data={"activity": {**asdict(activity), "verb": activity.verb.value}, "summary": intent,
              **(data or {})},
        commit_id=f"activity:{activity.activity_id}:start", target_id=activity.target_id,
        sources=activity.source_refs,
    )


def _complete(run, activity):
    if activity.verb is not ActionVerb.MOVE:
        from engine.runtime.simulation.community_objects import complete_object_activity
        return complete_object_activity(run, activity)
    actor = run.state.characters[activity.actor_id]
    passage = next(p for p in run.compiled.world.passages if p.id == activity.target_id)
    destination = next(p for p in run.compiled.world.locations if p.id == passage.destination_id)
    if not actor.active or actor.location_id != passage.origin_id or len(present(run, destination.id)) >= destination.capacity:
        status, delta, summary = "failed", Delta(), "travel failed: origin or capacity changed"
    else:
        status = "completed"
        delta = Delta(moves=(MoveDelta(activity.actor_id, actor.location_id, passage.destination_id),))
        summary = f"arrived at {destination.name}"
    started = run.log.activity_start(activity.activity_id)
    commit(
        run, EventType.ACTIVITY_FINISHED, actor_id=activity.actor_id, observers=(activity.actor_id,),
        delta=delta, data={"activity_id": activity.activity_id, "status": status, "summary": summary},
        commit_id=f"activity:{activity.activity_id}:finish",
        target_id=activity.target_id, sources=(f"event:{started.sequence}",),
    )
