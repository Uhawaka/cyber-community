"""Custody and accounting for personally contributed repair inputs."""

from collections import Counter

from engine.contracts.ecology import validate_quantities
from engine.contracts.community import require_int


def validate_repair_completion(event, started, state, community=None):
    from engine.contracts import ComponentPatch, ComponentValue, PatchOperation
    from engine.runtime.kernel.events import EventValidationError

    activity = started.data["activity"]
    if event.target_entity_id != activity["target_id"]:
        raise EventValidationError("activity outcome must target its started object")
    if activity["verb"] != "repair" or community is None:
        return
    if event.delta.resources or event.delta.inventories or event.delta.moves:
        raise EventValidationError("repair completion cannot change unrelated materials or locations")
    if event.data["status"] != "completed":
        if event.delta.entity_patches:
            raise EventValidationError("unsuccessful repair cannot improve a device")
        return
    recipe = next((r for r in community.repairs if r.target_id == activity["target_id"]), None)
    entity = state.entities.get(activity["target_id"])
    actor = state.characters[event.actor_id]
    if (recipe is None or entity is None or entity.version != activity["target_version"]
            or not actor.active or actor.location_id != entity.components["attributes"]["location_id"]):
        raise EventValidationError("successful repair requires its current object and local worker")
    expected = ComponentPatch(
        PatchOperation.UPSERT_COMPONENT, activity["target_id"], entity.version,
        component=ComponentValue("attributes", {
            **dict(entity.components["attributes"]), "condition": recipe.restored_condition,
        }),
    )
    if event.delta.entity_patches != (expected,) or f"event:{started.sequence}" not in event.data.get("source_refs", ()):
        raise EventValidationError("successful repair requires the registered committed outcome")


def validate_repair_materials(event, activity, state, community=None):
    from engine.runtime.kernel.events import EventValidationError
    recipe = None
    if activity.verb.value == "repair" and community is not None:
        recipe = next((r for r in community.repairs if r.target_id == activity.target_id), None)
        entity = state.entities.get(activity.target_id)
        if recipe is None or entity is None or activity.due_tick - activity.started_tick != recipe.duration_ticks:
            raise EventValidationError("repair requires its registered recipe and duration")
        if activity.target_version != entity.version or state.characters[activity.actor_id].location_id != entity.components["attributes"]["location_id"]:
            raise EventValidationError("repair requires current target version and local worker")
    if "material_ledger" not in event.data and "repair_inputs" not in event.data:
        if activity.verb.value == "repair" and event.delta.inventories:
            raise EventValidationError("personal repair inputs require a material ledger")
        if recipe is not None and tuple((q.item_id, -q.amount) for q in event.delta.resources) != recipe.inputs:
            raise EventValidationError("repair resources must match registered recipe")
        return
    try:
        if activity.verb.value != "repair":
            raise ValueError("only repairs may consume contributed materials")
        if recipe is None:
            raise ValueError("contributed repair requires authoritative recipe context")
        inputs = tuple(tuple(row) for row in event.data["repair_inputs"])
        validate_quantities(inputs)
        if inputs != recipe.inputs:
            raise ValueError("repair inputs must match registered recipe")
        ledger = tuple(tuple(row) for row in event.data["material_ledger"])
        if not inputs or not ledger or len(ledger) > 64:
            raise ValueError("repair ledger must be nonempty and bounded")
        keys, totals = set(), Counter()
        for owner, item, amount in ledger:
            require_int(amount, "material amount", 1)
            if amount > 1000 or owner not in {"world", activity.actor_id}:
                raise ValueError("repair cannot spend another person's custody")
            if (owner, item) in keys or item not in state.resources:
                raise ValueError("repair ledger has duplicate or unknown stock")
            keys.add((owner, item))
            totals[item] += amount
        actual = tuple((q.owner_id, q.item_id, -q.amount)
                       for q in (*event.delta.resources, *event.delta.inventories))
        if len(actual) != len(ledger) or set(actual) != set(ledger) or dict(totals) != dict(inputs):
            raise ValueError("repair delta must exactly match its input ledger")
        if any(q.owner_id != "world" for q in event.delta.resources) or any(
            q.owner_id != activity.actor_id for q in event.delta.inventories
        ):
            raise ValueError("repair custody must match resource/inventory channels")
    except (ValueError, TypeError, KeyError) as exc:
        raise EventValidationError("invalid repair material ledger: " + str(exc)) from exc
