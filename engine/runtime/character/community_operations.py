"""Known local operations expose costs, not hidden outcomes or remote state."""

from __future__ import annotations

from engine.contracts.community import ActionVerb, KnownOperation
from engine.runtime.character.community_projection import community_projection


def known_operations(run, actor_id, perception, skills):
    visible = {e.entity_id: e for e in perception.entities if e.kind == "resource"}
    operations = []
    for resource in run.compiled.world.resources:
        if resource.id not in visible:
            continue
        source = visible[resource.id].source_ref
        properties = dict(resource.properties)
        if not set(resource.required_skills) <= set(skills):
            continue
        operations.append(KnownOperation(ActionVerb.INSPECT, resource.id, source))
        # Loose communal stock is countable; private stores remain unavailable.
        shared = properties.get("public_access") is True and resource.owner_id == resource.location_id
        local = resource.location_id == perception.location_id
        if local and properties.get("portable") is True and (shared or resource.owner_id in {"world", actor_id}):
            operations.append(KnownOperation(
                ActionVerb.TAKE, resource.id, source, run.state.resources[resource.id],
            ))
        effects = properties.get("use_effects")
        if properties.get("consumable") is True and isinstance(effects, dict):
            operations.append(KnownOperation(
                ActionVerb.USE, resource.id, source,
                run.state.inventories[actor_id].get(resource.id, 0),
                use_effects=tuple(sorted(effects.items())),
            ))
        repair = next((r for r in run.compiled.community.repairs if r.target_id == resource.id), None)
        if local and repair and set(repair.required_skills) <= set(skills):
            operations.append(KnownOperation(
                ActionVerb.REPAIR, resource.id, source, duration_ticks=repair.duration_ticks,
                inputs=repair.inputs,
                material_stock=tuple((item, run.state.resources[item])
                                     for item, _ in repair.inputs if item in visible),
                restored_condition=repair.restored_condition,
                reserved=any(a.target_id == resource.id
                             for a in community_projection(run).activities.values()),
            ))
        learning = next((r for r in run.compiled.community.learning if r.resource_id == resource.id), None)
        if learning and set(learning.prerequisite_skills) <= set(skills) and learning.skill not in skills:
            operations.append(KnownOperation(
                ActionVerb.LEARN, resource.id, source, duration_ticks=learning.duration_ticks,
                learned_skill=learning.skill,
            ))
    projection = community_projection(run)
    for organization in run.compiled.community.organizations:
        if organization.location_id != perception.location_id:
            continue
        source = f"perception:{actor_id}:{perception.tick}:{perception.location_id}"
        if (organization.organization_id, actor_id) not in projection.memberships:
            sequence = projection.membership_invitations.get((organization.organization_id, actor_id))
            people = {entity.entity_id for entity in perception.entities if entity.kind == "character"}
            invitation = run.log.event_at(sequence) if sequence is not None else None
            if (invitation is not None and invitation.actor_id in people
                    and perception.tick <= invitation.tick + 24):
                operations.append(KnownOperation(ActionVerb.JOIN, organization.organization_id, f"event:{sequence}"))
            continue
        operations.extend((
            KnownOperation(ActionVerb.RECORD, organization.organization_id, source),
            KnownOperation(ActionVerb.READ, organization.organization_id, source),
            KnownOperation(ActionVerb.RESIGN, organization.organization_id, source),
            KnownOperation(ActionVerb.INVITE, organization.organization_id, source),
        ))
        for role in organization.roles:
            holder = projection.role_holders[(organization.organization_id, role.role_id)]
            if not holder and set(role.required_skills) <= set(skills):
                operations.append(KnownOperation(ActionVerb.TAKE_ROLE, organization.organization_id, source))
            elif holder == actor_id:
                operations.append(KnownOperation(ActionVerb.LEAVE_ROLE, organization.organization_id, source))
                if "censure" in role.permissions:
                    operations.append(KnownOperation(ActionVerb.CENSURE, organization.organization_id, source))
    return tuple(operations)
