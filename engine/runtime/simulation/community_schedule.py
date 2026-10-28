"""Event wakeups and bounded idle polling over durable decision records."""

from __future__ import annotations

from engine.runtime.character.community_projection import community_projection


def awake(run, actor_id):
    projection = community_projection(run)
    sequence = projection.last_decisions.get(actor_id)
    previous = run.log.event_at(sequence) if sequence is not None else None
    if previous is None:
        return True
    actor = run.state.characters[actor_id]
    if actor.needs.get("fatigue", 0) >= 60:
        return True
    profile = dict(next(c for c in run.compiled.world.characters if c.id == actor_id).profile)
    if profile.get("routine_locations") and run.state.tick % 24 in {0, 6, 7, 12, 18}:
        return True
    if previous.event_type.value == "inspected" and run.state.tick == previous.tick + 1:
        return True
    if any(
        p.owner_id == actor_id and p.status in {"ready", "blocked"}
        and p.next_attempt_tick <= run.state.tick
        and projection.goals[p.goal_id].status == "active"
        for p in projection.plans.pending_owned(actor_id)
    ):
        return True
    if any(
        plan.status == "ready" and (
            not plan.goal_id or (
                (goal := projection.goals.get(plan.goal_id)) is not None and goal.status == "active"
            )
        )
        for plan in projection.intent_plans.pending_owned(actor_id)
    ):
        return True
    if projection.last_wakeups.get(actor_id, -1) > previous.sequence:
        return True
    return run.state.tick - previous.tick >= run.compiled.community.idle_interval_ticks
