"""Authored, bounded material processes for the community runtime."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts.community import COMMUNITY_RUNTIME_VERSION, require_int, require_text


def validate_quantities(values: tuple[tuple[str, int], ...]) -> None:
    if len(values) > 16 or len({key for key, _ in values}) != len(values):
        raise ValueError("material entries must be unique and bounded")
    for key, amount in values:
        require_text(key, "resource_id", 200)
        require_int(amount, "material amount", 1)
        if amount > 1000:
            raise ValueError("material amount exceeds process capacity")


@dataclass(frozen=True)
class RepairRule:
    target_id: str
    inputs: tuple[tuple[str, int], ...]
    duration_ticks: int
    required_skills: tuple[str, ...] = ()
    restored_condition: int = 100

    def __post_init__(self) -> None:
        require_text(self.target_id, "target_id")
        require_int(self.duration_ticks, "duration_ticks", 1)
        require_int(self.restored_condition, "restored_condition", 1)
        if self.duration_ticks > 24 or self.restored_condition > 100:
            raise ValueError("repair exceeds duration or condition bounds")
        validate_quantities(self.inputs)
        if not self.inputs:
            raise ValueError("repair must consume materials")


@dataclass(frozen=True)
class ProcessDefinition:
    process_id: str
    kind: str
    location_id: str
    interval_ticks: int
    inputs: tuple[tuple[str, int], ...] = ()
    outputs: tuple[tuple[str, int], ...] = ()
    device_id: str = ""
    wear: int = 0
    capacity: int = 100
    required_devices: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        for field in ("process_id", "location_id"):
            require_text(getattr(self, field), field)
        if self.kind not in {"supply", "production", "wear"}:
            raise ValueError("process kind is not registered")
        require_int(self.interval_ticks, "interval_ticks", 1)
        require_int(self.capacity, "capacity", 1)
        require_int(self.wear, "wear")
        if self.interval_ticks > 720 or self.capacity > 10000 or self.wear > 100:
            raise ValueError("process exceeds budget")
        validate_quantities(self.inputs)
        validate_quantities(self.outputs)
        if self.kind == "production" and (not self.inputs or not self.outputs):
            raise ValueError("production requires inputs and outputs")
        if self.kind == "supply" and (self.inputs or not self.outputs):
            raise ValueError("supply requires external outputs only")
        if self.kind == "wear" and (not self.device_id or self.wear == 0):
            raise ValueError("wear requires a device and nonzero wear")
        if self.kind == "wear" and (self.inputs or self.outputs):
            raise ValueError("wear cannot produce or consume material")
        if self.wear and not self.device_id:
            raise ValueError("wear requires a registered device")
        if self.device_id in dict(self.inputs):
            raise ValueError("a process cannot consume its own device")
        if len(self.required_devices) > 8 or len(dict(self.required_devices)) != len(self.required_devices):
            raise ValueError("service dependencies must be unique and bounded")
        for device_id, minimum_condition in self.required_devices:
            require_text(device_id, "required device")
            require_int(minimum_condition, "minimum service condition", 1)
            if minimum_condition > 100:
                raise ValueError("minimum service condition exceeds device bounds")
            if device_id in dict(self.inputs) or device_id in dict(self.outputs):
                raise ValueError("a process cannot consume or produce its service device")


@dataclass(frozen=True)
class OrganizationRole:
    role_id: str
    name: str
    required_skills: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    initial_holder_id: str = ""

    def __post_init__(self):
        require_text(self.role_id, "role_id", 200)
        require_text(self.name, "role name", 200)
        if not isinstance(self.initial_holder_id, str):
            raise ValueError("initial role holder must be text")
        if len(self.required_skills) > 16 or len(set(self.required_skills)) != len(self.required_skills):
            raise ValueError("role skills must be unique and bounded")
        for skill in self.required_skills:
            require_text(skill, "role skill", 200)
        if len(set(self.permissions)) != len(self.permissions) or set(self.permissions) - {"censure"}:
            raise ValueError("unregistered or duplicate role permission")


@dataclass(frozen=True)
class Organization:
    organization_id: str
    name: str
    location_id: str
    member_ids: tuple[str, ...]
    norms: tuple[str, ...]
    roles: tuple[OrganizationRole, ...] = ()

    def __post_init__(self) -> None:
        for field in ("organization_id", "name", "location_id"):
            require_text(getattr(self, field), field)
        if not self.member_ids or len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("organization requires unique members")
        if len(self.norms) > 16:
            raise ValueError("organization norms exceed budget")
        for norm in self.norms:
            require_text(norm, "norm")
        if len(self.roles) > 16 or len({role.role_id for role in self.roles}) != len(self.roles):
            raise ValueError("organization roles must be unique and bounded")
        if any(role.initial_holder_id and role.initial_holder_id not in self.member_ids for role in self.roles):
            raise ValueError("initial role holder must belong to the organization")


@dataclass(frozen=True)
class LearningRule:
    resource_id: str
    skill: str
    duration_ticks: int
    prerequisite_skills: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.resource_id, "resource_id", 200)
        require_text(self.skill, "skill", 200)
        require_int(self.duration_ticks, "duration_ticks", 1)
        if self.duration_ticks > 72 or len(self.prerequisite_skills) > 16:
            raise ValueError("learning exceeds duration or prerequisite budget")
        if self.skill in self.prerequisite_skills:
            raise ValueError("learning cannot require its own result")
        for skill in self.prerequisite_skills:
            require_text(skill, "prerequisite skill", 200)


@dataclass(frozen=True)
class CommunityDefinition:
    runtime_version: str
    repairs: tuple[RepairRule, ...] = ()
    processes: tuple[ProcessDefinition, ...] = ()
    organizations: tuple[Organization, ...] = ()
    public_knowledge: tuple[str, ...] = ()
    learning: tuple[LearningRule, ...] = ()
    idle_interval_ticks: int = 1
    need_decay: tuple[tuple[str, int], ...] = (("fatigue", 1),)

    def __post_init__(self) -> None:
        if self.runtime_version != COMMUNITY_RUNTIME_VERSION:
            raise ValueError("unsupported community runtime version")
        require_int(self.idle_interval_ticks, "idle_interval_ticks", 1)
        if self.idle_interval_ticks > 24:
            raise ValueError("idle decision interval exceeds one simulated day")
        if len(dict(self.need_decay)) != len(self.need_decay) or len(self.need_decay) > 5:
            raise ValueError("need decay must have unique bounded entries")
        for need, amount in self.need_decay:
            if need not in {"fatigue", "resources", "social", "knowledge", "exploration"}:
                raise ValueError("unregistered community need")
            require_int(amount, "need decay")
            if amount > 5:
                raise ValueError("need decay exceeds hourly bounds")
        for items, key, maximum in (
            (self.repairs, "target_id", 64),
            (self.processes, "process_id", 32),
            (self.organizations, "organization_id", 16),
            (self.learning, "resource_id", 64),
        ):
            if len(items) > maximum or len({getattr(item, key) for item in items}) != len(items):
                raise ValueError("community definitions must be unique and bounded")
        if len(self.public_knowledge) > 32:
            raise ValueError("public knowledge exceeds budget")
        for text in self.public_knowledge:
            require_text(text, "public knowledge")
