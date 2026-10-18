"""Bounded detailed tick execution and coarse catch-up."""
from __future__ import annotations
import hashlib
from dataclasses import replace
from typing import Any

from engine.runtime.autonomous_director import _run_incident_scheduler, get_pending_user_gate, open_due_user_gate, wait_on_pending_user_gate
from engine.runtime.character.contracts import SchemeStatus
from engine.runtime.character.policy import ActorPolicy
from engine.runtime.kernel.events import Delta, EventType, NeedDelta, SchemeDelta, WorldEvent
from engine.runtime.simulation.coarse import coarse_boundary
from engine.runtime.simulation.coarse_commit import append_coarse_summary
from engine.runtime.scene.executor import run_scene_turns
from engine.runtime.simulation.observability import TickReport, _TickUsage, _tick_report
from engine.runtime.simulation.planner import opportunities_for
from engine.runtime.simulation.policy import SimulationPolicy
from engine.runtime.simulation.phases import check_phase_snapshots
from engine.runtime.simulation.resolver import Resolver
from engine.runtime.simulation.reservations import ReservationBook, ReservationRejection, append_scheduling_event
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.space import ActionAttempt, ActionKind
from engine.runtime.workflow import StepResult, TickContext, execute_workflow, workflow_step_scope
MAX_CATCHUP_TICKS = 24
def run_ticks(
    run: AutonomousRun,
    count: int,
    *,
    action_budget: int | None = None,
    incident_budget: int | None = None,
    opportunity_budget: int | None = None,
    memory_budget: int | None = None,
    policy: SimulationPolicy | None = None,
    actor_policy: ActorPolicy | None = None,
) -> TickReport:
    if count < 0:
        raise ValueError("tick count must be non-negative")
    active_policy = policy or SimulationPolicy.from_compiled(run.compiled)
    updates: dict[str, Any] = {}
    if action_budget is not None:
        updates["action_budget"] = action_budget
    if opportunity_budget is not None:
        updates["opportunity_budget"] = opportunity_budget
    if incident_budget is not None:
        updates["incident_budget"] = incident_budget
    if memory_budget is not None:
        updates["memory_budget"] = memory_budget
    if updates:
        active_policy = replace(active_policy, **updates)
    start_tick = run.state.tick
    start_sequence = len(run.events)
    usage = _TickUsage()
    executed = 0
    for _ in range(count):
        completed, tick_usage = _run_tick(
            run, active_policy, actor_policy or run.actor_policy
        )
        usage.add(tick_usage)
        if run.state.tick > start_tick + executed:
            executed += 1
        if not completed:
            break
    return _tick_report(
        run,
        start_tick,
        start_sequence,
        count,
        executed,
        usage,
    )


def _run_tick(
    run: AutonomousRun,
    policy: SimulationPolicy,
    actor_policy: ActorPolicy,
) -> tuple[bool, _TickUsage]:
    """Run one compiled evolution workflow."""

    hot_actor_ids = policy.hot_characters(run.state)
    observer_ids = frozenset(
        hot_actor_ids
        + tuple(
            actor_id
            for actor_id, character in run.state.characters.items()
            if character.participant_kind != "npc" and character.active
        )
    )
    action_limit = (
        policy.action_budget
        if policy.action_budget is not None
        else max(1, len(hot_actor_ids) * 3)
    )
    opportunity_limit = (
        policy.opportunity_budget
        if policy.opportunity_budget is not None
        else max(1, len(hot_actor_ids) * 8)
    )
    usage = _TickUsage(
        action_budget=action_limit,
        opportunity_budget=opportunity_limit,
        incident_budget=policy.incident_budget,
        memory_budget=policy.memory_budget,
    )
    enabled_steps: set[str] = set()

    def enable(step: str) -> StepResult:
        enabled_steps.add(step)
        return StepResult()

    usage.executed_workflow_steps = execute_workflow(
        run.compiled.workflow.evolution,
        TickContext(
            {
                step.op: (lambda name=step.op: enable(name))
                for step in run.compiled.workflow.evolution.steps
            }
        ),
    )
    if hot_actor_ids:
        usage.action_exhausted = action_limit == 0
        usage.opportunity_exhausted = opportunity_limit == 0
        usage.memory_exhausted = policy.memory_budget == 0
    intervention = dict(run.compiled.workflow.intervention.policy)
    gates_enabled = bool(intervention["allow_gates"])
    incidents_enabled = bool(intervention["allow_incidents"])
    if gates_enabled and get_pending_user_gate(run) is not None:
        wait_on_pending_user_gate(run)
        return True, usage
    if gates_enabled and open_due_user_gate(run) is not None:
        return False, usage
    all_actor_ids = tuple(sorted(run.state.characters))
    actor_ids = (
        hot_actor_ids
        if {"actor_windows", "scene_turns"}.intersection(enabled_steps)
        else ()
    )
    decay = tuple(
        change
        for actor_id in all_actor_ids
        for change in tuple(
            NeedDelta(actor_id, need, amount)
            for need, amount in policy.need_decay
        )
    )
    pre_state_hash = run.state.state_hash()
    cursor = len(run.events)
    if "environment_update" not in enabled_steps:
        return False, usage
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.ENVIRONMENT_DECAYED,
            actor_id=None,
            observers=tuple(observer_ids),
            delta=Delta(needs=decay, advance_time=1, advance_tick=1),
            data={
                "elapsed": 1,
                "pre_state_hash": pre_state_hash,
                "world_hash": run.state.world_hash,
                "deterministic_cursor": cursor,
                "target_entity_id": run.state.world_id,
                "rule_basis": ("one autonomous tick elapsed",),
            },
            pre_state_hash=pre_state_hash,
            world_hash=run.state.world_hash,
            deterministic_cursor=cursor,
            target_entity_id=run.state.world_id,
            rule_basis=("one autonomous tick elapsed",),
        )
    )
    incident_start = len(run.events)
    with workflow_step_scope("evolution", "incident_scheduler"):
        incident_event = (
            _run_incident_scheduler(
                run,
                policy.incident_budget,
                observer_ids=tuple(observer_ids),
            )
            if incidents_enabled and "incident_scheduler" in enabled_steps
            else None
        )
    if incident_event is not None:
        usage.incidents_used = int(
            incident_event.event_type is EventType.INCIDENT_OCCURRED
        )
        usage.incident_exhausted = (
            incident_event.event_type is EventType.INCIDENT_RESTED
            and policy.incident_budget == 0
        )
    if gates_enabled and open_due_user_gate(run) is not None:
        return False, usage
    if "scene_turns" in enabled_steps:
        with workflow_step_scope("evolution", "scene_turns"):
            scene_usage = run_scene_turns(
                run, actor_ids, turn_budget=action_limit
            )
        usage.actions_used += scene_usage.total_turns
    remaining_opportunities = opportunity_limit
    snapshot = run.state
    options_by_actor: dict[str, tuple[Any, ...]] = {}
    attempts: dict[str, ActionAttempt] = {}
    reservation_book = ReservationBook(
        run.compiled.world, snapshot, action_budget=action_limit
    )
    accepted: tuple[ActionAttempt, ...] = ()
    for actor_id in (
        actor_ids if "actor_windows" in enabled_steps else ()
    ):
        options = opportunities_for(
            run.compiled.world,
            snapshot,
            actor_id,
            limit=remaining_opportunities,
            character_scope=observer_ids,
        )
        usage.opportunities_evaluated += len(options)
        remaining_opportunities -= len(options)
        if not options:
            usage.opportunity_exhausted = True
            attempt = ActionAttempt(
                actor_id,
                ActionKind.WAIT,
                actor_id,
                snapshot.characters[actor_id].location_id,
                0,
                "tick opportunity budget exhausted",
                pre_state_hash=snapshot.state_hash(),
            )
            options_by_actor[actor_id] = ()
        else:
            attempt = actor_policy.choose(
                run.compiled.world, snapshot, actor_id, options
            )
            options_by_actor[actor_id] = options
        attempts[actor_id] = attempt

    rejection_history: list[ReservationRejection] = []
    while attempts:
        reservation_book = ReservationBook(
            run.compiled.world, snapshot, action_budget=action_limit
        )
        accepted, rejected = reservation_book.allocate(tuple(attempts.values()))
        if not rejected:
            break
        rejection_history.extend(rejected)
        accepted_by_actor = {item.actor_id: item for item in accepted}
        attempts = dict(accepted_by_actor)
        for rejection in rejected:
            contested_winner = next(
                (
                    attempt
                    for attempt in accepted
                    if attempt.kind is rejection.attempt.kind
                    and attempt.target_id == rejection.attempt.target_id
                ),
                None,
            )
            remaining_options = tuple(
                (
                    replace(
                        option,
                        utility=option.utility + 140,
                        reason=(
                            "negotiate with the actor who secured "
                            f"{rejection.attempt.target_id}"
                        ),
                    )
                    if contested_winner is not None
                    and option.affordance.kind is ActionKind.TALK
                    and option.affordance.target_id
                    == contested_winner.actor_id
                    else option
                )
                for option in options_by_actor.get(rejection.actor_id, ())
                if option.opportunity_id != rejection.attempt.opportunity_id
            )
            options_by_actor[rejection.actor_id] = remaining_options
            if remaining_options:
                attempts[rejection.actor_id] = actor_policy.choose(
                    run.compiled.world,
                    snapshot,
                    rejection.actor_id,
                    remaining_options,
                )
            else:
                attempts[rejection.actor_id] = ActionAttempt(
                    rejection.actor_id,
                    ActionKind.WAIT,
                    rejection.actor_id,
                    snapshot.characters[rejection.actor_id].location_id,
                    0,
                    f"replanned after {rejection.reason}",
                    pre_state_hash=snapshot.state_hash(),
                )

    for rejection in rejection_history:
        append_scheduling_event(
            run,
            EventType.ACTION_REJECTED,
            rejection.actor_id,
            {
                "reason": rejection.reason,
                "contested_key": rejection.contested_key,
                "rejected_opportunity_id": rejection.attempt.opportunity_id,
            },
        )
        append_scheduling_event(
            run,
            EventType.ACTION_REPLANNED,
            rejection.actor_id,
            {
                "reason": rejection.reason,
                "replacement_kind": attempts[rejection.actor_id].kind.value,
                "replacement_target_id": attempts[rejection.actor_id].target_id,
            },
        )
        usage.action_exhausted |= rejection.reason == "action_budget_exhausted"

    final_attempts = {
        item.actor_id: item for item in accepted
    }
    resolver = Resolver(
        run.compiled.world,
        run.log,
        observer_scope=observer_ids,
        reservation_book=reservation_book,
    )
    for actor_id in sorted(final_attempts):
        attempt = final_attempts[actor_id]
        if "scheme_progress" in enabled_steps:
            _sync_scheme(run, attempt)
        event = resolver.resolve(attempt)
        if "scheme_progress" in enabled_steps:
            _advance_scheme_after_action(run, attempt, event)
        usage.actions_used += attempt.cost
    memory_remaining = policy.memory_budget
    consolidated = (
        _consolidate_memory(
            run, budget=memory_remaining, observer_ids=tuple(observer_ids)
        )
        if "memory_consolidation" in enabled_steps
        else 0
    )
    usage.memory_updates_used += consolidated
    memory_remaining -= consolidated
    evolved = (
        _evolve_souls(run, actor_ids=actor_ids, budget=memory_remaining)
        if "memory_consolidation" in enabled_steps
        else 0
    )
    usage.memory_updates_used += evolved
    if "phase_check" in enabled_steps:
        check_phase_snapshots(run, observer_ids=tuple(observer_ids))
    if (
        policy.memory_budget == 0
        or usage.memory_updates_used >= policy.memory_budget
    ):
        usage.memory_exhausted |= _memory_work_due(run, actor_ids)
    del incident_start
    return True, usage


from engine.runtime.simulation.evolution import advance_scheme_after_action as _advance_scheme_after_action
from engine.runtime.simulation.evolution import consolidate_memory as _consolidate_memory
from engine.runtime.simulation.evolution import evolve_souls as _evolve_souls
from engine.runtime.simulation.evolution import memory_work_due as _memory_work_due
from engine.runtime.simulation.evolution import sync_scheme as _sync_scheme

def run_catchup(
    run: AutonomousRun,
    requested_ticks: int,
    *,
    max_ticks: int | None = None,
    action_budget: int | None = None,
    policy: SimulationPolicy | None = None,
) -> TickReport:
    active_policy = policy or SimulationPolicy.from_compiled(run.compiled)
    detailed_limit = (
        active_policy.max_catchup_ticks if max_ticks is None else max_ticks
    )
    if requested_ticks < 0 or detailed_limit < 0:
        raise ValueError("catchup limits must be non-negative")
    if action_budget is not None:
        active_policy = replace(active_policy, action_budget=action_budget)
    permitted = min(requested_ticks, detailed_limit)
    start_sequence = len(run.events)
    start_tick = run.state.tick
    detailed = run_ticks(run, permitted, policy=active_policy)
    usage = _TickUsage.from_report(detailed)
    detailed_ticks = detailed.executed_ticks
    coarse_ticks = 0
    target_tick = start_tick + requested_ticks
    while run.state.tick < target_tick:
        if get_pending_user_gate(run) is not None:
            waited = run_ticks(run, 1, policy=active_policy)
            usage.add(_TickUsage.from_report(waited))
            detailed_ticks += waited.executed_ticks
            continue
        if open_due_user_gate(run) is not None:
            continue
        boundary = coarse_boundary(run, target_tick)
        if boundary > run.state.tick:
            span = boundary - run.state.tick
            append_coarse_summary(
                run,
                span,
                requested_ticks=requested_ticks,
                detailed_ticks=detailed_ticks,
                start_tick=start_tick,
                start_sequence=start_sequence,
                policy=active_policy,
            )
            coarse_ticks += span
            check_phase_snapshots(
                run,
                observer_ids=active_policy.hot_characters(run.state),
            )
            # A gate at the segment endpoint must become pending before any
            # further coarse settlement is considered.
            open_due_user_gate(run)
            continue
        crossed = run_ticks(run, 1, policy=active_policy)
        usage.add(_TickUsage.from_report(crossed))
        detailed_ticks += crossed.executed_ticks
        if crossed.executed_ticks == 0 and get_pending_user_gate(run) is None:
            break
    return _tick_report(
        run,
        start_tick,
        start_sequence,
        requested_ticks,
        detailed_ticks,
        usage,
        truncated_ticks=coarse_ticks,
        coarse_ticks=coarse_ticks,
    )



