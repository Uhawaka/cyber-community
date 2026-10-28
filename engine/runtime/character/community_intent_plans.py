"""Owned plans record intentions, then advance only from linked outcomes."""

from dataclasses import asdict, replace

from engine.contracts.intent import IntentPlan, ready_intent_steps
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.community_intent_plan_validation import (
    check_conditions, check_deadline_ready, check_owned_goal, deadline_review, failure_branch, latest_plan,
    progress_plan, selectable_step, step_has_attempt, step_outcome,
)
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def create_intent_plan(run, proposal):
    existing = community_projection(run).intent_plans
    if proposal.proposal_id in existing or len(tuple(existing.pending_owned(proposal.actor_id))) >= 8:
        raise ValueError("personal plan identity or active plan budget exceeded")
    plan = IntentPlan(proposal.proposal_id, proposal.actor_id, proposal.intent,
                      proposal.plan_steps, proposal.source_refs, plan_budget=proposal.plan_budget,
                      goal_id=proposal.plan_goal_id, deadline_tick=proposal.plan_deadline_tick)
    check_owned_goal(plan, run.events)
    if plan.deadline_tick is not None and plan.deadline_tick < run.state.tick:
        raise ValueError("personal plan deadline must start in the present or future")
    plan = replace(plan, cursor=ready_intent_steps(plan)[0])
    return commit(
        run, EventType.INTENT_PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
        data={"intent_plan": asdict(plan)},
        delta=Delta(actions=(ActionRecord(plan.owner_id, "plan", plan.owner_id, run.state.tick),)),
        sources=plan.source_refs, target_id=plan.owner_id,
        commit_id=f"intent-plan:{plan.plan_id}:created",
    )


def validate_selection(run, proposal):
    plan = community_projection(run).intent_plans.get(proposal.intent_plan_id)
    if plan is None or plan.owner_id != proposal.actor_id:
        raise ValueError("step requires an owned personal plan")
    if plan.status not in {"ready", "blocked"} or not selectable_step(plan, proposal.intent_step_index):
        raise ValueError("step dependencies are not satisfied in the personal plan")
    check_owned_goal(plan, run.events)
    check_deadline_ready(plan, run.state.tick)
    check_conditions(plan, proposal.intent_step_index, run.state)
    step = plan.steps[proposal.intent_step_index]
    if (proposal.verb.value, proposal.target_id, proposal.quantity, proposal.item_id, proposal.speech) != (
        step.verb, step.target_id, step.quantity, step.item_id, step.speech,
    ) or proposal.reply_to or proposal.requested_item_id or proposal.requested_quantity:
        raise ValueError("selected action does not match personal plan step")


def abandon_intent_plan(run, proposal):
    plan = community_projection(run).intent_plans.get(proposal.target_id)
    if plan is None or plan.owner_id != proposal.actor_id or plan.status not in {"ready", "blocked"}:
        raise ValueError("abandonment requires an owned active personal plan")
    plan = replace(plan, status="abandoned", source_refs=proposal.source_refs)
    return commit(
        run, EventType.INTENT_PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
        data={"intent_plan": asdict(plan)},
        delta=Delta(actions=(ActionRecord(plan.owner_id, "abandon_plan", plan.plan_id, run.state.tick),)),
        sources=plan.source_refs, target_id=plan.owner_id,
        commit_id=f"intent-plan:{plan.plan_id}:abandoned",
    )


def branch_intent_plan(run, proposal):
    plan = community_projection(run).intent_plans.get(proposal.target_id)
    if plan is None or plan.owner_id != proposal.actor_id or plan.status != "blocked":
        raise ValueError("failure branch requires an owned blocked personal plan")
    prior = latest_plan(run.events, plan.plan_id)
    sources = tuple(dict.fromkeys((*proposal.source_refs, f"event:{prior.sequence}")))
    updated = failure_branch(plan, sources)
    return commit(
        run, EventType.INTENT_PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
        data={"intent_plan": asdict(updated)},
        delta=Delta(actions=(ActionRecord(plan.owner_id, "branch_plan", plan.plan_id, run.state.tick),)),
        sources=sources, target_id=plan.owner_id,
        commit_id=f"intent-plan:{plan.plan_id}:branch:{prior.sequence}",
    )


def reconcile_intent_plans(run):
    projection = community_projection(run)
    for plan in sorted(tuple(projection.intent_plans.pending()), key=lambda value: value.plan_id):
        previous = latest_plan(run.events, plan.plan_id)
        outcome = step_outcome(run.events, plan, previous.sequence)
        if outcome is not None:
            result, success, index = outcome
            plan = progress_plan(plan, index, success, result.sequence)
            previous = commit(
                run, EventType.INTENT_PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
                data={"intent_plan": asdict(plan)}, sources=plan.source_refs, target_id=plan.owner_id,
                commit_id=f"intent-plan:{plan.plan_id}:outcome:{result.sequence}",
            )
        goal = projection.goals.get(plan.goal_id) if plan.goal_id else None
        if (plan.status in {"ready", "blocked"} and plan.deadline_tick is not None
                and not plan.deadline_reached and run.state.tick > plan.deadline_tick
                and (not plan.goal_id or goal is not None and goal.status == "active")
                and not step_has_attempt(run.events, plan, previous.sequence)):
            updated = deadline_review(plan, previous, run.events, run.state.tick)
            commit(
                run, EventType.INTENT_PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
                data={"intent_plan": asdict(updated), "system_update": True},
                sources=updated.source_refs, target_id=plan.owner_id,
                commit_id=f"intent-plan:{plan.plan_id}:deadline",
            )
