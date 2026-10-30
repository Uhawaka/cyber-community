"""Model window: an index of what exists, with bodies only for the current focus.

Life policy and source checks keep the full DecisionContext. The model sees this
projection. Reflections stay indexed so a recalled line is not loaded as new text.
"""

from __future__ import annotations

import json

WINDOW_JSON_LIMIT = 3500
_LOADED_OPS = 8
_LOADED_NOTES = 3
_INDEX_OPS = 24
_INDEX_NOTES = 12
_LOADED_DIRECTIVES = ("values", "taboos", "drives", "voice", "long_term_desire")


def assemble_window(context) -> dict:
    """Bounded JSON-ready view. Truncation drops index lines, not stored records."""
    focus = _focus(context)
    here = context.perception.location_id
    loaded_ops, op_index = _operations(context.operations, focus)
    loaded_notes, note_index = _notes(context.memories, focus)
    window = {
        "actor_id": context.actor_id,
        "perception": _perception(context.perception),
        "needs": [list(item) for item in context.needs],
        "inventory": [list(item) for item in context.inventory],
        "pressing_need": context.pressing_need,
        "private_knowledge": [list(item) for item in context.private_knowledge],
        "relationship_stances": [list(item) for item in context.relationship_stances],
        "reachable": [list(item) for item in context.reachable],
        "errands": [list(item) for item in context.errands],
        "authored_goals": list(context.authored_goals),
        "requests_to_me": [list(item) for item in context.requests_to_me],
        "soul": _soul_loaded(context.soul),
        "soul_index": _soul_index(context.soul),
        "goals": [_goal(goal) for goal in context.goals],
        "intent_plans": [_plan(plan) for plan in context.intent_plans],
        "intent_plan_history": [_plan(plan) for plan in context.intent_plan_history],
        "plan_review_inputs": [list(item) for item in context.plan_review_inputs[:4]],
        "known_map": [
            [route, origin, destination]
            for route, origin, destination in context.known_map
            if origin == here
        ],
        "loaded": {"operations": loaded_ops, "notes": loaded_notes},
        "operations_index": op_index,
        "memory_index": note_index,
        "claims_index": [[ref, text[:48]] for ref, text in context.claims[:_INDEX_NOTES]],
    }
    _fit(window)
    window["allowed_source_refs"] = sorted(_refs(window, context))
    _fit(window)
    window["allowed_source_refs"] = sorted(_refs(window, context))
    return window


def _focus(context):
    ids = set()
    for goal in context.goals:
        if goal.target_id:
            ids.add(goal.target_id)
    for errand in context.errands:
        if errand and errand[0]:
            ids.add(errand[0])
    for record in (*context.commitments, *context.requests, *context.offers):
        target = getattr(record, "target_id", "") or getattr(record, "item_id", "")
        if isinstance(target, str) and target:
            ids.add(target)
    return ids


def _perception(perception):
    return {
        "actor_id": perception.actor_id,
        "tick": perception.tick,
        "location_id": perception.location_id,
        "known_routes": list(perception.known_routes),
        "entities": [
            {"entity_id": entity.entity_id, "kind": entity.kind, "name": entity.name}
            for entity in perception.entities
        ],
    }


def _operations(operations, focus):
    loaded, index = [], []
    for operation in operations:
        verb = operation.verb.value
        if operation.target_id in focus and len(loaded) < _LOADED_OPS:
            body = {"verb": verb, "target_id": operation.target_id, "source_ref": operation.source_ref}
            if operation.available_quantity:
                body["available_quantity"] = operation.available_quantity
            if operation.inputs:
                body["inputs"] = [list(item) for item in operation.inputs]
            loaded.append(body)
        elif len(index) < _INDEX_OPS:
            index.append([verb, operation.target_id])
    return loaded, index


def _soul_loaded(soul):
    loaded = []
    for key, value in soul:
        if key.rsplit(":", 1)[-1] in _LOADED_DIRECTIVES:
            loaded.append([key, value[:48]])
    return loaded


def _soul_index(soul):
    return [key for key, _value in soul if key.rsplit(":", 1)[-1] not in _LOADED_DIRECTIVES]


def _label(text):
    body = text.split("] ", 1)[-1] if text.startswith("[") else text
    return body[:24]


def _notes(memories, focus):
    """Retrieve order is already ranked. Load the first few bodies; index the rest."""
    del focus
    loaded, index = [], []
    for ref, text in memories:
        if text.startswith("[reflection]"):
            if len(index) < _INDEX_NOTES:
                index.append([ref, _label(text)])
            continue
        if len(loaded) < _LOADED_NOTES:
            loaded.append([ref, text[:180]])
        elif len(index) < _INDEX_NOTES:
            index.append([ref, _label(text)])
    return loaded, index


def _goal(goal):
    return {
        "goal_id": goal.goal_id,
        "description": goal.description[:120],
        "target_id": goal.target_id,
        "action_verb": goal.action_verb,
        "source_refs": list(goal.source_refs),
    }


def _plan(plan):
    card = {
        "plan_id": plan.plan_id,
        "status": plan.status,
        "cursor": plan.cursor,
        "goal_id": plan.goal_id,
        "source_refs": list(plan.source_refs),
        "steps": [{"verb": step.verb, "target_id": step.target_id} for step in plan.steps],
    }
    if plan.deadline_tick is not None:
        card["deadline_tick"] = plan.deadline_tick
    return card


def _refs(window, context):
    refs = {f"perception:{context.actor_id}:{context.perception.tick}:{context.perception.location_id}"}
    refs.update(key for key, _value in window["soul"])
    for goal in window["goals"]:
        refs.update(goal["source_refs"])
    for plan in (*window["intent_plans"], *window["intent_plan_history"]):
        refs.update(plan["source_refs"])
    for item in window["plan_review_inputs"]:
        if len(item) > 1 and isinstance(item[1], str):
            refs.add(item[1])
    for operation in window["loaded"]["operations"]:
        refs.add(operation["source_ref"])
    for ref, _text in window["loaded"]["notes"]:
        refs.add(ref)
    refs.update(ref for ref, _text in window["claims_index"])
    for item in window["memory_index"]:
        refs.add(item[0] if isinstance(item, list) else item)
    return {ref for ref in refs if isinstance(ref, str) and ref}


def _fit(window):
    """Keep the indexes. Shorten loaded text before dropping a name."""
    def size():
        return len(json.dumps(window, ensure_ascii=False))

    while size() > WINDOW_JSON_LIMIT:
        longest = max(range(len(window["soul"])), key=lambda i: len(window["soul"][i][1]), default=None)
        if longest is None or len(window["soul"][longest][1]) <= 24:
            break
        key, value = window["soul"][longest]
        window["soul"][longest] = [key, value[: max(24, len(value) // 2)]]
    while size() > WINDOW_JSON_LIMIT and window["claims_index"]:
        window["claims_index"].pop()
    while size() > WINDOW_JSON_LIMIT and len(window["known_map"]) > 4:
        window["known_map"].pop()
    while size() > WINDOW_JSON_LIMIT:
        notes = window["loaded"]["notes"]
        longer = next((index for index, (_ref, text) in enumerate(notes) if len(text) > 48), None)
        if longer is None:
            break
        ref, text = notes[longer]
        notes[longer] = [ref, text[:48]]
    while size() > WINDOW_JSON_LIMIT and window["operations_index"]:
        window["operations_index"].pop()
    while size() > WINDOW_JSON_LIMIT and window["memory_index"]:
        window["memory_index"].pop()
    if size() > WINDOW_JSON_LIMIT:
        raise ValueError("model window exceeds character budget")
