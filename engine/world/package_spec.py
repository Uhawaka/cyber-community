"""Immutable contracts for directory-authored autonomous world packages."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from engine.contracts.experience import CompiledExperienceContract


PACKAGE_SCHEMA_VERSION = "world-package/v1alpha2"


@dataclass(frozen=True)
class PackageDiagnostic:
    code: str
    path: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class CapabilityHandshake:
    requested: tuple[str, ...]
    supported: tuple[str, ...]
    accepted: tuple[str, ...]
    unknown: tuple[str, ...]


@dataclass(frozen=True)
class PackageRef:
    name: str
    ref: str
    content_hash: str


@dataclass(frozen=True)
class WorkflowStep:
    op: str
    arguments: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class WorkflowDefinition:
    schema_version: str
    kind: str
    steps: tuple[WorkflowStep, ...]
    policy: tuple[tuple[str, Any], ...]
    content_hash: str
    ref: str


@dataclass(frozen=True)
class WorkflowIR:
    genesis: WorkflowDefinition
    evolution: WorkflowDefinition
    intervention: WorkflowDefinition
    presentation: WorkflowDefinition

    def for_kind(self, kind: str) -> WorkflowDefinition:
        if kind not in {"genesis", "evolution", "intervention", "presentation"}:
            raise ValueError(f"unknown workflow kind: {kind}")
        return getattr(self, kind)


@dataclass(frozen=True)
class PackageManifest:
    schema_version: str
    package_id: str
    revision: int
    capabilities: tuple[str, ...]
    assets: tuple[tuple[str, str], ...]
    workflows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PackageSceneSeed:
    key: str
    name: str
    premise: str
    tags: tuple[str, ...] = ()
    dramatic_question: str = ""
    failure_pressure: str = ""
    closure_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageLocation:
    id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    allow_avatar_entry: bool = False
    capacity: int = 1
    access_tags: tuple[str, ...] = ()
    allowed_roles: tuple[str, ...] = ()
    affordances: tuple[tuple[str, bool], ...] = ()
    danger: int = 0
    metadata: tuple[tuple[str, Any], ...] = ()
    scene_seeds: tuple[PackageSceneSeed, ...] = ()

    def allows(self, kind: str) -> bool:
        return bool(dict(self.affordances).get(kind, False))


@dataclass(frozen=True)
class PackageResource:
    id: str
    name: str
    location_id: str
    quantity: int = 1
    owner_id: str = ""
    container_id: str = ""
    required_skills: tuple[str, ...] = ()
    properties: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class PackagePassage:
    id: str
    origin_id: str
    destination_id: str
    travel_time: int = 1
    properties: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class PackageCharacter:
    id: str
    name: str
    role: str
    location_id: str
    profile: tuple[tuple[str, Any], ...]
    soul: tuple[tuple[str, Any], ...]
    memory_seed: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DramaticHorizon:
    central_question: str
    success_conditions: tuple[str, ...]
    failure_conditions: tuple[str, ...]
    invariants: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutonomousWorldSpec:
    world_id: str
    title: str
    premise: str
    locations: tuple[PackageLocation, ...]
    characters: tuple[PackageCharacter, ...]
    resources: tuple[PackageResource, ...]
    passages: tuple[PackagePassage, ...]
    rules: tuple[dict[str, Any], ...] = ()
    metadata: tuple[tuple[str, Any], ...] = ()
    dramatic_horizon: DramaticHorizon | None = None


@dataclass(frozen=True)
class CompiledWorld:
    manifest: PackageManifest
    workflow: WorkflowIR
    world: AutonomousWorldSpec
    experience: CompiledExperienceContract
    content_hash: str


@dataclass(frozen=True)
class PackageCompileResult:
    compiled: CompiledWorld | None
    diagnostics: tuple[PackageDiagnostic, ...]
    handshake: CapabilityHandshake

    @property
    def ok(self) -> bool:
        return self.compiled is not None and not any(
            item.severity == "error" for item in self.diagnostics
        )


def canonical_compiled_json(compiled: CompiledWorld) -> str:
    """Return a stable serialization, excluding the derived hash itself."""

    value = asdict(compiled)
    value.pop("content_hash", None)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
