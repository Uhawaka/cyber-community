"""Compile community assets without executing authored text or scripts."""

from __future__ import annotations

from typing import Any

from engine.contracts.ecology import (
    CommunityDefinition, LearningRule, Organization, OrganizationRole, ProcessDefinition, RepairRule,
)
from engine.world.package_spec import AutonomousWorldSpec, PackageDiagnostic


def _fields(value: dict, allowed: set[str]) -> None:
    if set(value) - allowed:
        raise ValueError("unknown community fields: " + ", ".join(sorted(set(value) - allowed)))


def _rows(value: Any) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("community entries must be an array of objects")
    return value


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(s, str) or not s.strip() for s in value):
        raise ValueError("expected an array of non-empty strings")
    return tuple(value)


def _quantities(value: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        raise ValueError("materials must be an object of resource quantities")
    return tuple(sorted(value.items()))


def compile_community(
    document: dict,
    world: AutonomousWorldSpec,
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> CommunityDefinition | None:
    try:
        _fields(document, {"runtime_version", "repairs", "processes", "organizations", "public_knowledge", "learning", "idle_interval_ticks", "need_decay"})
        repairs = []
        for row in _rows(document.get("repairs", [])):
            _fields(row, {"target_id", "inputs", "duration_ticks", "required_skills", "restored_condition"})
            repairs.append(RepairRule(
                row["target_id"], _quantities(row["inputs"]), row["duration_ticks"],
                _strings(row.get("required_skills", [])), row.get("restored_condition", 100),
            ))
        processes = []
        for row in _rows(document.get("processes", [])):
            _fields(row, {"process_id", "kind", "location_id", "interval_ticks", "inputs", "outputs", "device_id", "wear", "capacity", "required_devices"})
            processes.append(ProcessDefinition(
                row["process_id"], row["kind"], row["location_id"], row["interval_ticks"],
                _quantities(row.get("inputs", {})), _quantities(row.get("outputs", {})),
                row.get("device_id", ""), row.get("wear", 0), row.get("capacity", 100),
                _quantities(row.get("required_devices", {})),
            ))
        organizations = []
        for row in _rows(document.get("organizations", [])):
            _fields(row, {"organization_id", "name", "location_id", "member_ids", "norms", "roles"})
            roles = []
            for role in _rows(row.get("roles", [])):
                _fields(role, {"role_id", "name", "required_skills", "permissions", "initial_holder_id"})
                roles.append(OrganizationRole(
                    role["role_id"], role["name"], _strings(role.get("required_skills", [])),
                    _strings(role.get("permissions", [])), role.get("initial_holder_id", ""),
                ))
            organizations.append(Organization(
                row["organization_id"], row["name"], row["location_id"],
                _strings(row["member_ids"]), _strings(row.get("norms", [])), tuple(roles),
            ))
        learning = []
        for row in _rows(document.get("learning", [])):
            _fields(row, {"resource_id", "skill", "duration_ticks", "prerequisite_skills"})
            learning.append(LearningRule(
                row["resource_id"], row["skill"], row["duration_ticks"],
                _strings(row.get("prerequisite_skills", [])),
            ))
        definition = CommunityDefinition(
            document["runtime_version"], tuple(repairs), tuple(processes),
            tuple(organizations), _strings(document.get("public_knowledge", [])), tuple(learning),
            document.get("idle_interval_ticks", 1),
            _quantities(document.get("need_decay", {"fatigue": 1})),
        )
        _validate_references(definition, world)
        return definition
    except (ValueError, TypeError, KeyError) as exc:
        diagnostics.append(PackageDiagnostic("INVALID_COMMUNITY", path, str(exc)))
        return None


def _validate_references(definition: CommunityDefinition, world: AutonomousWorldSpec) -> None:
    resources = {item.id: item for item in world.resources}
    locations = {item.id for item in world.locations}
    characters = {item.id for item in world.characters}
    for resource in world.resources:
        condition = dict(resource.properties).get("condition", 100)
        if isinstance(condition, bool) or not isinstance(condition, int) or not 0 <= condition <= 100:
            raise ValueError("resource condition must be an integer from 0 to 100")
    for repair in definition.repairs:
        if repair.target_id not in resources:
            raise ValueError("repair references an unknown device")
        location = resources[repair.target_id].location_id
        for resource_id, _ in repair.inputs:
            if resource_id not in resources or resources[resource_id].location_id != location:
                raise ValueError("repair materials must exist at the device location")
        if repair.target_id in dict(repair.inputs):
            raise ValueError("repair cannot consume its own device")
    for process in definition.processes:
        if process.location_id not in locations:
            raise ValueError("process references an unknown location")
        for resource_id, _ in (*process.inputs, *process.outputs):
            if resource_id not in resources or resources[resource_id].location_id != process.location_id:
                raise ValueError("process materials must exist at the process location")
        if process.device_id and (
            process.device_id not in resources
            or resources[process.device_id].location_id != process.location_id
        ):
            raise ValueError("process device must exist at the process location")
        for device_id, _ in process.required_devices:
            if device_id not in resources or "condition" not in dict(resources[device_id].properties):
                raise ValueError("service dependency must reference a condition-bearing device")
    for organization in definition.organizations:
        if organization.location_id not in locations or not set(organization.member_ids) <= characters:
            raise ValueError("organization references unknown members or location")
        for role in organization.roles:
            holder = next((c for c in world.characters if c.id == role.initial_holder_id), None)
            if holder and not set(role.required_skills) <= set(dict(holder.profile).get("skills", ())):
                raise ValueError("initial role holder lacks required skills")
    for learning in definition.learning:
        if learning.resource_id not in resources:
            raise ValueError("learning references an unknown knowledge carrier")
