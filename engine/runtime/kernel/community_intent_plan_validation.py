"""Validate private step plans against explicitly linked committed actions."""

from collections import Counter
from dataclasses import replace

from engine.contracts.intent import IntentPlan, ready_intent_steps
from engine.runtime.kernel.events import (
    ActionRecord, Delta, EventType, EventValidationError, MoveDelta, NeedDelta, QuantityDelta,
)


def latest_plan(events, plan_id):
    return next((event for event in reversed(events)
                 if event.event_type is EventType.INTENT_PLAN_UPDATED
                 and event.data["intent_plan"]["plan_id"] == plan_id), None)


def decode_plan(raw):
    return IntentPlan(**{**raw, "source_refs": tuple(raw["source_refs"])})


def check_owned_goal(plan, events):
    if not plan.goal_id:
        return
    goal = next((event.data["goal"] for event in reversed(events)
                 if event.event_type is EventType.GOAL_UPDATED
                 and event.data["goal"]["goal_id"] == plan.goal_id), None)
    if goal is None or goal["owner_id"] != plan.owner_id or goal["status"] != "active":
        raise ValueError("personal plan requires an owned active goal")


def check_deadline_ready(plan, tick):
    if plan.deadline_tick is not None and tick > plan.deadline_tick and not plan.deadline_reached:
        raise ValueError("personal plan deadline requires review")


def deadline_review(plan, previous, events, tick):
    if (plan.deadline_tick is None or plan.deadline_reached or tick <= plan.deadline_tick
            or plan.status not in {"ready", "blocked"} or step_has_attempt(events, plan, previous.sequence)):
        raise ValueError("personal plan deadline cannot be reviewed yet")
    check_owned_goal(plan, events)
    clock = next((event for event in reversed(events) if event.event_type is EventType.COMMUNITY_TICK
                  and event.data.get("phase") == "open" and event.tick + 1 == tick), None)
    if clock is None:
        raise ValueError("plan deadline requires a committed clock event")
    return replace(plan, status="blocked", deadline_reached=True,
                   source_refs=(f"event:{previous.sequence}", f"event:{clock.sequence}"))


def selectable_step(plan, index):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(plan.steps):
        return False
    return index == plan.cursor if plan.status == "blocked" else index in ready_intent_steps(plan)


def check_conditions(plan, index, state):
    for guard in plan.steps[index].guards:
        if guard.kind == "at_location":
            satisfied = state.characters[plan.owner_id].location_id == guard.target_id
        else:
            satisfied = state.inventories[plan.owner_id].get(guard.target_id, 0) >= guard.quantity
        if not satisfied:
            raise ValueError("personal plan condition is not satisfied")


def progress_plan(plan, index, success, sequence):
    sources = (f"event:{sequence}",)
    if not success:
        return replace(plan, cursor=index, status="blocked", source_refs=sources)
    completed = tuple(sorted((*plan.completed_steps, index)))
    updated = replace(plan, completed_steps=completed, source_refs=sources)
    if len(completed) + len(plan.skipped_steps) == len(plan.steps):
        return replace(updated, cursor=len(plan.steps), status="completed")
    ready = ready_intent_steps(updated)
    if not ready:
        raise ValueError("plan dependencies leave no available step")
    return replace(updated, cursor=ready[0], status="ready")


def failure_branch(plan, sources):
    branch = plan.steps[plan.cursor].on_failure
    if branch < 0:
        raise ValueError("personal plan has no failure branch")
    skipped = tuple(sorted(set(plan.skipped_steps) | (
        set(range(plan.cursor, branch)) - set(plan.completed_steps))))
    updated = replace(plan, cursor=branch, status="ready", skipped_steps=skipped, source_refs=sources)
    if branch not in ready_intent_steps(updated):
        raise ValueError("failure branch does not satisfy plan dependencies")
    for index, step in enumerate(plan.steps):
        if index not in skipped and index not in plan.completed_steps and step.depends_on is not None:
            if set(step.depends_on) & set(skipped):
                raise ValueError("failure branch leaves unsatisfied plan dependencies")
    return updated


def step_outcome(events, plan, after):
    """Return one linked result; activity starts are not completed outcomes."""
    for event in events[after + 1:]:
        if event.actor_id != plan.owner_id:
            continue
        selection = event.data.get("intent_step")
        attempted = event.data.get("proposal") if event.event_type is EventType.ACTION_REJECTED else None
        rejected = (isinstance(attempted, dict)
                    and attempted.get("intent_plan_id") == plan.plan_id
                    and selectable_step(plan, attempted.get("intent_step_index")))
        if rejected:
            return event, False, attempted["intent_step_index"]
        if (not isinstance(selection, dict) or selection.get("plan_id") != plan.plan_id
                or not selectable_step(plan, selection.get("index"))):
            continue
        index = selection["index"]
        if event.event_type is not EventType.ACTIVITY_STARTED:
            return event, True, index
        activity = event.data["activity"]["activity_id"]
        finish = next((item for item in events[event.sequence + 1:]
                       if item.event_type is EventType.ACTIVITY_FINISHED
                       and item.actor_id == plan.owner_id and item.data.get("activity_id") == activity), None)
        if finish is None:
            return None
        return finish, finish.data.get("status") == "completed", index
    return None


def withdrawals(event, owner_id):
    amounts = Counter()
    for item in event.delta.resources:
        if item.amount < 0:
            amounts[item.item_id] -= item.amount
    for item in event.delta.inventories:
        if item.owner_id == owner_id and item.amount < 0:
            amounts[item.item_id] -= item.amount
    return amounts


def step_has_attempt(events, plan, after):
    for item in events[after + 1:]:
        if item.actor_id != plan.owner_id:
            continue
        selection = item.data.get("intent_step")
        attempted = item.data.get("proposal")
        if (isinstance(selection, dict) and selection.get("plan_id") == plan.plan_id
                and selectable_step(plan, selection.get("index"))) or (
            item.event_type is EventType.ACTION_REJECTED and isinstance(attempted, dict)
            and attempted.get("intent_plan_id") == plan.plan_id
            and selectable_step(plan, attempted.get("intent_step_index"))
        ):
            return True
    return False


def validate_linked_action(event, events, state, world):
    selection = event.data.get("intent_step")
    if selection is None:
        return
    try:
        if not isinstance(selection, dict) or set(selection) != {"plan_id", "index"}:
            raise ValueError("invalid step selection")
        prior = latest_plan(events, selection["plan_id"])
        if prior is None:
            raise ValueError("step requires an owned plan")
        plan = decode_plan(prior.data["intent_plan"])
        if (plan.owner_id != event.actor_id or plan.status not in {"ready", "blocked"}
                or not selectable_step(plan, selection["index"])):
            raise ValueError("step requires owned plan with satisfied dependencies")
        check_owned_goal(plan, events)
        check_deadline_ready(plan, event.tick)
        check_conditions(plan, selection["index"], state)
        step = plan.steps[selection["index"]]
        if event.delta.actions != (ActionRecord(event.actor_id, step.verb, step.target_id, event.tick),):
            raise ValueError("step action does not match plan")
        resource = None
        if step.verb in {"inspect", "repair", "take", "use", "learn"}:
            resource = next((item for item in world.resources if item.id == step.target_id), None) if world else None
            character = next((item for item in world.characters if item.id == plan.owner_id), None) if world else None
            if resource is None or character is None:
                raise ValueError("selected object step requires a registered resource and actor")
            skills = set(dict(character.profile).get("skills", ()))
            skills.update(item.data["learned_skill"] for item in events
                          if item.actor_id == plan.owner_id and item.event_type is EventType.ACTIVITY_FINISHED
                          and item.data.get("status") == "completed" and item.data.get("learned_skill"))
            if not set(resource.required_skills) <= skills:
                raise ValueError("selected object step requires the actor's skills")
        if event.event_type is EventType.ACTIVITY_STARTED:
            activity = event.data["activity"]
            if (activity["actor_id"], activity["verb"], activity["target_id"]) != (
                plan.owner_id, step.verb, step.target_id,
            ):
                raise ValueError("activity does not match selected step")
        elif step.verb in {"move", "repair", "learn"}:
            raise ValueError("step requires a started activity")
        if step.verb == "take" and (
            event.event_type is not EventType.GATHERED or event.data.get("quantity") != step.quantity
        ):
            raise ValueError("gathered quantity does not match selected step")
        if step.verb == "take" and (
            event.target_entity_id != step.target_id
            or event.delta.resources != (QuantityDelta("world", step.target_id, -step.quantity),)
            or event.delta.inventories != (QuantityDelta(plan.owner_id, step.target_id, step.quantity),)
        ):
            raise ValueError("gathered step requires a committed material transfer")
        if step.verb == "take":
            properties = dict(resource.properties)
            shared = properties.get("public_access") is True and resource.owner_id == resource.location_id
            if (properties.get("portable") is not True or resource.location_id != state.characters[plan.owner_id].location_id
                    or resource.owner_id not in {"world", plan.owner_id} and not shared):
                raise ValueError("taking requires a local portable resource and authorized ownership")
        if step.verb == "use" and event.delta.inventories != (
            QuantityDelta(plan.owner_id, step.target_id, -step.quantity),
        ):
            raise ValueError("consumption does not match selected step")
        if step.verb == "use" and event.event_type is not EventType.RESTED:
            raise ValueError("consumption requires a registered use result")
        if step.verb == "use":
            properties = dict(resource.properties)
            effects = properties.get("use_effects")
            allowed = {"fatigue", "social", "resources", "knowledge", "exploration"}
            if (properties.get("consumable") is not True or not isinstance(effects, dict) or not effects
                    or set(effects) - allowed or any(isinstance(amount, bool) or not isinstance(amount, int)
                                                     or not -30 <= amount <= 0 for amount in effects.values())
                    or event.target_entity_id != step.target_id or event.delta.resources
                    or event.delta.needs != tuple(NeedDelta(plan.owner_id, need, amount * step.quantity)
                                                  for need, amount in sorted(effects.items()))):
                raise ValueError("consumption requires registered effects")
        if step.verb == "speak" and (
            event.event_type is not EventType.DIALOGUE or event.data.get("utterance") != step.speech
            or event.data.get("listener_id") != step.target_id
        ):
            raise ValueError("speech does not match selected step")
        if step.verb == "inspect" and (
            event.event_type is not EventType.INSPECTED or event.target_entity_id != step.target_id
        ):
            raise ValueError("inspection does not match selected step")
        if step.verb == "inspect":
            entity = state.entities.get(step.target_id)
            owner = state.characters[plan.owner_id]
            held = state.inventories[plan.owner_id].get(step.target_id, 0) > 0
            if (entity is None or (resource.location_id != owner.location_id and not held)
                    or event.observers != (plan.owner_id,)
                    or event.data.get("condition") != entity.components["attributes"]["condition"]
                    or event.data.get("finding") != str(dict(resource.properties).get("inspection", resource.name))):
                raise ValueError("inspection must reflect a visible object's actual condition")
        if step.verb == "rest" and (event.event_type is not EventType.RESTED or step.target_id != plan.owner_id):
            raise ValueError("rest does not match selected step")
        if step.verb == "wait" and (event.event_type is not EventType.WAITED or step.target_id != plan.owner_id):
            raise ValueError("wait does not match selected step")
        if step.verb in {"rest", "wait"}:
            needs = (NeedDelta(plan.owner_id, "fatigue", -18),) if step.verb == "rest" else ()
            action = ActionRecord(plan.owner_id, step.verb, plan.owner_id, event.tick)
            if event.delta != Delta(needs=needs, actions=(action,)):
                raise ValueError("rest/wait needs and state changes must match registered effects")
        if plan.plan_budget:
            spent = Counter()
            for item in events:
                selected = item.data.get("intent_step")
                if item.actor_id == plan.owner_id and isinstance(selected, dict) and selected.get("plan_id") == plan.plan_id:
                    spent.update(withdrawals(item, plan.owner_id))
            spent.update(withdrawals(event, plan.owner_id))
            budget = dict(plan.plan_budget)
            if any(amount > budget.get(resource, 0) for resource, amount in spent.items()):
                raise ValueError("personal plan material budget exceeded")
        if step_has_attempt(events, plan, prior.sequence):
            raise ValueError("step already has an unresolved attempt")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise EventValidationError("invalid personal plan action: " + str(exc)) from exc


def validate_linked_finish(event, started, state, world):
    activity = started.data["activity"]
    if not started.data.get("intent_step") or activity["verb"] != "move":
        return
    if event.data.get("status") != "completed":
        if event.delta.moves:
            raise EventValidationError("unsuccessful plan movement cannot move a character")
        return
    route = next((route for route in world.passages if route.id == activity["target_id"]), None) if world else None
    location = next((place for place in world.locations if route and place.id == route.destination_id), None) if world else None
    actor = state.characters[event.actor_id]
    occupancy = sum(person.active and person.location_id == route.destination_id
                    for person in state.characters.values()) if route else 0
    if (route is None or location is None or not actor.active or actor.location_id != route.origin_id
            or occupancy >= location.capacity
            or event.delta.moves != (MoveDelta(event.actor_id, route.origin_id, route.destination_id),)):
        raise EventValidationError("completed plan movement requires its actual valid movement delta")


def validate_intent_plan(event, events):
    try:
        raw = event.data["intent_plan"]
        plan = decode_plan(raw)
        if event.observers != (event.actor_id,) or plan.owner_id != event.actor_id:
            raise ValueError("personal plan must be private and owned")
        if tuple(plan.source_refs) != tuple(event.data["source_refs"]):
            raise ValueError("plan sources must match event")
        previous_event = latest_plan(events, plan.plan_id)
        if previous_event is None:
            check_owned_goal(plan, events)
            if plan.deadline_reached or (plan.deadline_tick is not None and plan.deadline_tick < event.tick):
                raise ValueError("personal plan deadline must start in the present or future")
            action = ActionRecord(plan.owner_id, "plan", plan.owner_id, event.tick)
            ready = ready_intent_steps(plan)
            if (not ready or plan.cursor != ready[0] or plan.status != "ready" or plan.skipped_steps
                    or plan.completed_steps or event.delta != Delta(actions=(action,))):
                raise ValueError("personal plan must start with the owner's decision")
            latest = {}
            for prior in events:
                if prior.event_type is EventType.INTENT_PLAN_UPDATED and prior.actor_id == plan.owner_id:
                    latest[prior.data["intent_plan"]["plan_id"]] = prior.data["intent_plan"]["status"]
            if sum(status in {"ready", "blocked"} for status in latest.values()) >= 8:
                raise ValueError("active personal plan budget exceeded")
            return
        previous = decode_plan(previous_event.data["intent_plan"])
        if (previous.owner_id, previous.description, previous.steps, previous.plan_budget,
                previous.goal_id, previous.deadline_tick) != (
            plan.owner_id, plan.description, plan.steps, plan.plan_budget, plan.goal_id, plan.deadline_tick,
        ):
            raise ValueError("personal plan identity and steps are immutable")
        if previous.status in {"completed", "abandoned"}:
            raise ValueError("terminal plan cannot change")
        if plan.deadline_reached != previous.deadline_reached:
            expected = deadline_review(previous, previous_event, events, event.tick)
            if plan != expected or event.delta != Delta() or event.data.get("system_update") is not True:
                raise ValueError("plan deadline review must match its committed clock")
            return
        if plan.status == "abandoned":
            action = ActionRecord(plan.owner_id, "abandon_plan", plan.plan_id, event.tick)
            if (plan.cursor != previous.cursor or plan.skipped_steps != previous.skipped_steps
                    or plan.completed_steps != previous.completed_steps
                    or event.delta != Delta(actions=(action,))
                    or step_has_attempt(events, previous, previous_event.sequence)):
                raise ValueError("abandonment requires an independent decision with no unresolved step")
            return
        if event.delta.actions:
            action = ActionRecord(plan.owner_id, "branch_plan", plan.plan_id, event.tick)
            expected = failure_branch(previous, plan.source_refs)
            if (previous.status != "blocked" or plan != expected or event.delta != Delta(actions=(action,))
                    or f"event:{previous_event.sequence}" not in plan.source_refs
                    or step_has_attempt(events, previous, previous_event.sequence)):
                raise ValueError("failure branch requires an independent owned decision")
            return
        if event.delta != Delta():
            raise ValueError("plan progress cannot change world state")
        outcome = step_outcome(events, previous, previous_event.sequence)
        if outcome is None:
            raise ValueError("step progress requires a committed outcome")
        result, success, index = outcome
        expected = progress_plan(previous, index, success, result.sequence)
        if plan != expected:
            raise ValueError("plan progress must match its exact committed outcome")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise EventValidationError("invalid personal plan: " + str(exc)) from exc
