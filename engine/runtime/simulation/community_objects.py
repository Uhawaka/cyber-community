"""Physical object operations with real material and versioned consequences."""

from __future__ import annotations

from engine.contracts import ComponentPatch, ComponentValue, PatchOperation
from engine.contracts.community import ActionVerb, Activity
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import (
    ActionRecord, Delta, EventType, NeedDelta, QuantityDelta,
)
from engine.runtime.simulation.community_events import commit, present


def begin_object_action(run, proposal, context, start_activity):
    visible = {e.entity_id for e in context.perception.entities if e.kind == "resource"}
    if proposal.target_id not in visible:
        raise ValueError("object is not currently visible")
    resource = next(r for r in run.compiled.world.resources if r.id == proposal.target_id)
    actor = next(c for c in run.compiled.world.characters if c.id == proposal.actor_id)
    skills = set(dict(actor.profile).get("skills", ())) | community_projection(run).learned_skills.get(actor.id, set())
    if not set(resource.required_skills) <= skills:
        raise ValueError("object requires skills the actor does not have")
    entity = run.state.entities[resource.id]
    properties = dict(resource.properties)
    place = run.state.characters[proposal.actor_id].location_id
    actions = (ActionRecord(proposal.actor_id, proposal.verb.value, resource.id, run.state.tick),)
    if proposal.verb is ActionVerb.LEARN:
        rule = next((r for r in run.compiled.community.learning if r.resource_id == resource.id), None)
        if rule is None or not set(rule.prerequisite_skills) <= skills:
            raise ValueError("learning requires a registered carrier and prerequisite skills")
        if rule.skill in skills:
            raise ValueError("skill is already learned")
        start_activity(run, Activity(
            proposal.proposal_id, proposal.actor_id, proposal.verb, resource.id,
            run.state.tick, run.state.tick + rule.duration_ticks,
            proposal.source_refs, entity.version,
        ), proposal.intent, delta=Delta(needs=(NeedDelta(proposal.actor_id, "fatigue", 2),)))
        return
    if proposal.verb is ActionVerb.INSPECT:
        condition = entity.components["attributes"]["condition"]
        finding = str(properties.get("inspection", resource.name))
        commit(
            run, EventType.INSPECTED, actor_id=proposal.actor_id,
            observers=(proposal.actor_id,), delta=Delta(actions=actions),
            data={"resource_id": resource.id, "condition": condition, "finding": finding,
                  "summary": f"{resource.name}: condition {condition}; {finding}", "location_id": place},
            commit_id=f"decision:{proposal.actor_id}:{run.state.tick}", target_id=resource.id,
            sources=proposal.source_refs,
        )
        return
    if proposal.verb is ActionVerb.REPAIR:
        recipe = next((r for r in run.compiled.community.repairs if r.target_id == resource.id), None)
        if recipe is None:
            raise ValueError("object has no registered repair")
        if not set(recipe.required_skills) <= skills:
            raise ValueError("repair requires unavailable skills")
        if place != resource.location_id:
            raise ValueError("repair requires the registered workshop and local materials")
        if entity.components["attributes"]["condition"] >= recipe.restored_condition:
            raise ValueError("repair has no possible improvement")
        if any(a.target_id == resource.id for a in community_projection(run).activities.values()):
            raise ValueError("object is reserved by another activity")
        held = run.state.inventories[proposal.actor_id]
        if any(run.state.resources[item] + held.get(item, 0) < quantity for item, quantity in recipe.inputs):
            raise ValueError("insufficient repair materials")
        own = tuple((item, min(quantity, held.get(item, 0))) for item, quantity in recipe.inputs)
        ledger = tuple(
            (owner, item, amount)
            for item, quantity in recipe.inputs for owner, amount in (
                (proposal.actor_id, dict(own)[item]), ("world", quantity - dict(own)[item])
            ) if amount
        )
        sources = list(proposal.source_refs)
        for item, amount in own:
            if not amount:
                continue
            receipt = next((e for e in reversed(run.events) if any(
                q.owner_id == proposal.actor_id and q.item_id == item and q.amount > 0
                for q in e.delta.inventories
            ) and proposal.actor_id in e.observers), None)
            if receipt and f"event:{receipt.sequence}" not in sources:
                sources.append(f"event:{receipt.sequence}")
        if len(sources) > 16:
            raise ValueError("repair material provenance exceeds source budget")
        activity = Activity(
            proposal.proposal_id, proposal.actor_id, proposal.verb, resource.id,
            run.state.tick, run.state.tick + recipe.duration_ticks,
            tuple(sources), entity.version,
        )
        start_activity(
            run, activity, proposal.intent,
            delta=Delta(
                resources=tuple(QuantityDelta(owner, item, -amount) for owner, item, amount in ledger if owner == "world"),
                inventories=tuple(QuantityDelta(owner, item, -amount) for owner, item, amount in ledger if owner != "world"),
                needs=(NeedDelta(proposal.actor_id, "fatigue", 4),),
            ),
            data={"repair_inputs": recipe.inputs, "material_ledger": ledger}
            if any(amount for _, amount in own) else None,
        )
        return
    if proposal.verb is ActionVerb.TAKE:
        if place != resource.location_id:
            raise ValueError("taking stock requires presence at its registered location")
        if properties.get("portable") is not True:
            raise ValueError("object is not portable")
        shared = properties.get("public_access") is True and resource.owner_id == resource.location_id
        if resource.owner_id not in {"world", proposal.actor_id} and not shared:
            raise ValueError("taking another owner's property requires consent")
        if run.state.resources[resource.id] < proposal.quantity:
            raise ValueError("insufficient available objects")
        commit(
            run, EventType.GATHERED, actor_id=proposal.actor_id, observers=present(run, place),
            delta=Delta(
                resources=(QuantityDelta("world", resource.id, -proposal.quantity),),
                inventories=(QuantityDelta(proposal.actor_id, resource.id, proposal.quantity),),
                actions=actions,
            ),
            data={"resource_id": resource.id, "quantity": proposal.quantity, "summary": proposal.intent},
            commit_id=f"decision:{proposal.actor_id}:{run.state.tick}", target_id=resource.id,
            sources=proposal.source_refs,
        )
        return
    if proposal.verb is ActionVerb.USE:
        effects = properties.get("use_effects")
        allowed = {"fatigue", "social", "resources", "knowledge", "exploration"}
        if properties.get("consumable") is not True or not isinstance(effects, dict) or not effects:
            raise ValueError("object has no registered consumable effects")
        if set(effects) - allowed or any(
            isinstance(amount, bool) or not isinstance(amount, int) or not -30 <= amount <= 0
            for amount in effects.values()
        ):
            raise ValueError("consumable effects exceed capability bounds")
        if run.state.inventories[proposal.actor_id].get(resource.id, 0) < proposal.quantity:
            raise ValueError("using an object requires enough personally held stock")
        commit(
            run, EventType.RESTED, actor_id=proposal.actor_id, observers=present(run, place),
            delta=Delta(
                inventories=(QuantityDelta(proposal.actor_id, resource.id, -proposal.quantity),),
                needs=tuple(NeedDelta(proposal.actor_id, need, amount * proposal.quantity) for need, amount in sorted(effects.items())),
                actions=actions,
            ),
            data={"resource_id": resource.id, "summary": proposal.intent},
            commit_id=f"decision:{proposal.actor_id}:{run.state.tick}", target_id=resource.id,
            sources=proposal.source_refs,
        )
        return
    raise ValueError("object capability is not implemented")


def complete_object_activity(run, activity):
    entity = run.state.entities[activity.target_id]
    learning = activity.verb is ActionVerb.LEARN
    recipe = (
        next(r for r in run.compiled.community.learning if r.resource_id == activity.target_id)
        if learning else next(r for r in run.compiled.community.repairs if r.target_id == activity.target_id)
    )
    actor = run.state.characters[activity.actor_id]
    attributes = entity.components["attributes"]
    held = run.state.inventories[activity.actor_id].get(activity.target_id, 0) > 0
    if not actor.active or (actor.location_id != attributes["location_id"] and not (learning and held)) or entity.version != activity.target_version:
        status, delta = "failed", Delta()
        summary = "activity failed: worker presence or target version changed; committed inputs remain consumed"
    elif learning:
        status, delta = "completed", Delta()
        summary = f"learned {recipe.skill} from {activity.target_id}"
    else:
        status = "completed"
        delta = Delta(entity_patches=(ComponentPatch(
            PatchOperation.UPSERT_COMPONENT, activity.target_id, entity.version,
            component=ComponentValue("attributes", {**dict(attributes), "condition": recipe.restored_condition}),
        ),))
        summary = f"repaired {activity.target_id}: condition {recipe.restored_condition}"
    started = run.log.activity_start(activity.activity_id)
    commit(
        run, EventType.ACTIVITY_FINISHED, actor_id=activity.actor_id,
        observers=(activity.actor_id,) if learning else present(run, attributes["location_id"]), delta=delta,
        data={"activity_id": activity.activity_id, "status": status, "summary": summary,
              "resource_id": activity.target_id, "location_id": actor.location_id,
              **({"learned_skill": recipe.skill} if learning and status == "completed" else {})},
        commit_id=f"activity:{activity.activity_id}:finish", target_id=activity.target_id,
        sources=(f"event:{started.sequence}",),
    )
