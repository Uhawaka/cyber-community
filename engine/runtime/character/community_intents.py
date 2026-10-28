"""Compile bounded, structured personal intentions into registered actions."""

from collections import deque

from engine.contracts.community import ActionProposal, ActionVerb, IntentStep, require_text


def navigation_route(context, destination):
    require_text(destination, "destination")
    if len(context.known_map) > 256:
        raise ValueError("known map exceeds navigation budget")
    origin = context.perception.location_id
    if destination == origin:
        raise ValueError("already at intended destination")
    queue = deque([(origin, ())])
    visited = {origin}
    while queue:
        place, path = queue.popleft()
        for route, start, end in context.known_map:
            if start != place or end in visited:
                continue
            if not path and route not in context.perception.known_routes:
                continue
            next_path = (*path, route)
            if end == destination:
                return next_path
            visited.add(end)
            queue.append((end, next_path))
    raise ValueError("destination has no known accessible route")


def compile_navigation(context, destination, intention, sources):
    require_text(intention, "intent")
    route = navigation_route(context, destination)
    return ActionProposal(
        f"decision:{context.actor_id}:{context.perception.tick}",
        context.actor_id, ActionVerb.MOVE, route[0], intention,
        tuple(sources), context.state_hash,
    )


def compile_navigation_plan(context, destination, intention, sources):
    require_text(intention, "intent")
    route = navigation_route(context, destination)
    if len(route) > 8:
        raise ValueError("navigation plan exceeds step budget")
    return ActionProposal(
        f"decision:{context.actor_id}:{context.perception.tick}",
        context.actor_id, ActionVerb.PLAN, context.actor_id, intention,
        tuple(sources), context.state_hash,
        plan_steps=tuple(IntentStep("move", item) for item in route),
    )
