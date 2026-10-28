"""Persistent desires, concrete goals and bounded retry plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace

from engine.contracts.community import Goal, Plan
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def write_goal(run, goal, *, action=None):
    return commit(
        run, EventType.GOAL_UPDATED, actor_id=goal.owner_id, observers=(goal.owner_id,),
        data={"goal": asdict(goal), "summary": f"{goal.status}: {goal.description}"},
        delta=Delta(actions=(action,)) if action else None,
        sources=goal.source_refs, target_id=goal.target_id or goal.owner_id,
        commit_id=f"goal:{goal.goal_id}:{len(run.events)}",
    )


def write_plan(run, plan):
    return commit(
        run, EventType.PLAN_UPDATED, actor_id=plan.owner_id, observers=(plan.owner_id,),
        data={"plan": asdict(plan)}, sources=plan.source_refs,
        commit_id=f"plan:{plan.plan_id}:{len(run.events)}", target_id=plan.owner_id,
    )


def pursue(run, proposal, context):
    projection = community_projection(run)
    if proposal.verb.value == "abandon":
        goal = projection.goals.get(proposal.target_id)
        if goal is None or goal.owner_id != proposal.actor_id or goal.status != "active":
            raise ValueError("abandon requires an active owned goal")
        goal = replace(goal, status="abandoned", source_refs=proposal.source_refs)
    else:
        visible = {e.entity_id for e in context.perception.entities}
        if proposal.target_id not in visible | set(context.perception.known_routes):
            raise ValueError("concrete goal target must be currently known")
        goal = Goal(
            f"{proposal.actor_id}:{proposal.proposal_id}", proposal.actor_id,
            proposal.intent, proposal.source_refs, target_id=proposal.target_id,
            action_verb=proposal.item_id, quantity=proposal.quantity,
        )
        if goal.action_verb == "wait":
            raise ValueError("pursue requires a concrete completion criterion")
        if any(g.owner_id == goal.owner_id and g.status == "active"
               and (g.target_id, g.action_verb) == (goal.target_id, goal.action_verb)
               for g in projection.goals.pending_owned(goal.owner_id)):
            raise ValueError("goal already active; continue or replan it")
    write_goal(run, goal, action=ActionRecord(
        proposal.actor_id, proposal.verb.value, proposal.target_id, run.state.tick,
    ))


def seed_desires(run):
    projection = community_projection(run)
    for character in run.compiled.world.characters:
        if not run.state.characters[character.id].active:
            continue
        for number, description in enumerate(dict(character.profile).get("goals", ())):
            goal_id = f"desire:{character.id}:{number}"
            if goal_id not in projection.goals:
                write_goal(run, Goal(
                    goal_id, character.id, description,
                    (f"soul:{character.id}:drives",), priority=30,
                ))
    reconcile(run)


def satisfied(run, goal):
    actor = run.state.characters[goal.owner_id]
    projection = community_projection(run)
    origin = projection.goal_evidence.origins.get(goal.goal_id)
    if origin is None:
        return False
    evidence = [e for e in projection.goal_evidence.for_goal(goal, run.events)
                if e.sequence > origin]
    if goal.action_verb == "take":
        return run.state.inventories[goal.owner_id].get(goal.target_id, 0) >= goal.quantity and any(
            e.event_type is EventType.GATHERED and e.target_entity_id == goal.target_id for e in evidence
        )
    if goal.action_verb == "learn":
        rule = next((r for r in run.compiled.community.learning if r.resource_id == goal.target_id), None)
        return rule is not None and rule.skill in community_projection(run).learned_skills.get(goal.owner_id, set()) and any(
            e.event_type is EventType.ACTIVITY_FINISHED and e.data.get("learned_skill") == rule.skill
            and e.target_entity_id == goal.target_id for e in evidence
        )
    if goal.action_verb == "repair":
        claim = [
            c for c in projection.claims.owned(goal.owner_id)
            if c.owner_id == goal.owner_id and c.subject == goal.target_id
            and c.predicate == "condition" and c.channel == "observation"
            and any(c.source_refs[0] == f"event:{e.sequence}" for e in evidence)
        ]
        if claim and max(claim, key=lambda c: c.acquired_tick).content.isdigit():
            if int(max(claim, key=lambda c: c.acquired_tick).content) >= goal.quantity:
                return True
        return any(
            e.actor_id == goal.owner_id and e.event_type is EventType.ACTIVITY_FINISHED
            and e.data.get("status") == "completed" and e.target_entity_id == goal.target_id
            and run.state.entities[goal.target_id].components["attributes"]["condition"] >= goal.quantity
            for e in evidence
        )
    if goal.action_verb == "move":
        route = next((p for p in run.compiled.world.passages if p.id == goal.target_id), None)
        return route is not None and actor.location_id == route.destination_id and any(
            e.event_type is EventType.ACTIVITY_FINISHED and e.target_entity_id == goal.target_id
            and e.data.get("status") == "completed" for e in evidence
        )
    if goal.action_verb == "speak":
        return any(
            e.actor_id == goal.owner_id and e.event_type is EventType.DIALOGUE
            and e.data.get("listener_id") == goal.target_id
            for e in evidence
        )
    return False


def reconcile(run):
    projection = community_projection(run)
    candidates = {g.goal_id for g in projection.goals.pending()}
    candidates.update(p.goal_id for p in projection.plans.pending())
    for identity in sorted(candidates, key=projection.goal_evidence.origins.__getitem__):
        goal = projection.goals[identity]
        if goal.action_verb == "wait":
            continue
        plan_id = f"plan:{goal.goal_id}"
        plan = projection.plans.get(plan_id)
        if plan is None and goal.status == "active":
            origin = run.events[projection.goal_evidence.origins[goal.goal_id]]
            write_plan(run, Plan(plan_id, goal.owner_id, goal.goal_id, (f"event:{origin.sequence}",)))
            projection = community_projection(run)
            plan = projection.plans[plan_id]
        if plan is None:
            continue
        if goal.status != "active":
            if plan.status not in {"completed", "abandoned"}:
                write_plan(run, replace(plan, status=goal.status,
                           source_refs=goal.source_refs if goal.status == "completed" else plan.source_refs))
            continue
        evidence = projection.goal_evidence.for_goal(goal, run.events)
        if satisfied(run, goal):
            refs = (f"event:{evidence[-1].sequence}",) if evidence else goal.source_refs
            write_goal(run, replace(goal, status="completed", source_refs=refs))
            write_plan(run, replace(plan, status="completed", source_refs=refs))
        elif goal.deadline_tick is not None and run.state.tick > goal.deadline_tick:
            write_goal(run, replace(goal, status="abandoned"))
            write_plan(run, replace(plan, status="abandoned"))


def record_rejection(run, actor_id, source_event):
    projection = community_projection(run)
    recorded = next((e.data["plan"] for e in run.events if e.event_type is EventType.PLAN_UPDATED
                     and e.actor_id == actor_id and f"event:{source_event.sequence}" in e.data["plan"]["source_refs"]), None)
    if recorded is not None:
        goal = projection.goals[recorded["goal_id"]]
        if recorded["status"] == "abandoned" and goal.status == "active":
            write_goal(run, replace(goal, status="abandoned", source_refs=tuple(recorded["source_refs"])))
        return
    proposal = source_event.data.get("proposal")
    if not isinstance(proposal, Mapping):
        return
    if proposal.get("intent_plan_id"):
        return
    ready = sorted((
        p for p in projection.plans.pending_owned(actor_id)
        if p.owner_id == actor_id and p.status in {"ready", "blocked"}
        and p.next_attempt_tick <= run.state.tick
        and projection.goals[p.goal_id].status == "active"
        and (
            bool(set(p.source_refs) & set(proposal.get("source_refs", ())))
            or (proposal.get("verb"), proposal.get("target_id")) == (
                projection.goals[p.goal_id].action_verb, projection.goals[p.goal_id].target_id,
            )
        )
    ), key=lambda p: (-projection.goals[p.goal_id].priority, p.plan_id))
    if not ready:
        return
    plan = ready[0]
    attempts = plan.attempts + 1
    refs = (f"event:{source_event.sequence}",)
    write_plan(run, replace(
        plan, attempts=attempts, status="abandoned" if attempts >= 4 else "blocked",
        next_attempt_tick=run.state.tick + min(24, 2 ** attempts), source_refs=refs,
    ))
    if attempts >= 4:
        write_goal(run, replace(projection.goals[plan.goal_id], status="abandoned", source_refs=refs))
