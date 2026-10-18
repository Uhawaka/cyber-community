"""Deterministic coordinator for directory-authored world packages."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from engine.world.package_build import _build_world
from engine.world.package_characters import _compile_characters
from engine.world.package_experience import compile_experience_profile
from engine.world.package_source import _read_object, _safe_ref
from engine.world.package_authoring import _find_forbidden_fields, _validate_document_schemas
from engine.world.package_validation import _reject_unknown_fields, _validate_structured_rules
from engine.world.package_spec import (PACKAGE_SCHEMA_VERSION, CapabilityHandshake, CompiledWorld, PackageCharacter, PackageCompileResult, PackageDiagnostic, PackageManifest, WorkflowDefinition, WorkflowIR, canonical_compiled_json)
from engine.world.package_workflows import compile_workflow

SUPPORTED_PACKAGE_CAPABILITIES = frozenset(
    {
        "world.core.v1",
        "world.characters.v1",
        "world.memory-seed.v1",
        "world.resources.v1",
        "world.topology.v1",
        "world.incidents.v1",
        "world.user-gates.v1",
        "world.fate-interventions.v1",
    }
)
REQUIRED_ASSETS = ("world", "locations", "characters", "resources", "passages")
REQUIRED_WORKFLOWS = ("genesis", "evolution", "intervention", "presentation")
ASSET_CAPABILITIES = {
    "world": "world.core.v1",
    "locations": "world.topology.v1",
    "characters": "world.characters.v1",
    "resources": "world.resources.v1",
    "passages": "world.topology.v1",
}


DOCUMENT_FIELDS = {
    "manifest.yaml": {"schema_version", "package_id", "revision", "capabilities", "assets", "workflows"},
    "world.yaml": {
        "world_id",
        "title",
        "premise",
        "rules",
        "metadata",
        "dramatic_horizon",
        "experience_profile",
    },
    "locations.yaml": {"locations"},
    "resources.yaml": {"resources"},
    "passages.yaml": {"passages"},
}

def compile_package(
    package_dir: str | Path,
    *,
    supported_capabilities: frozenset[str] = SUPPORTED_PACKAGE_CAPABILITIES,
) -> PackageCompileResult:
    """Compile a package directory without mutating its authoring files."""

    root = Path(package_dir)
    diagnostics: list[PackageDiagnostic] = []
    manifest_data = _read_object(root / "manifest.yaml", root, diagnostics)
    _reject_unknown_fields(
        manifest_data, DOCUMENT_FIELDS["manifest.yaml"], "manifest.yaml", diagnostics
    )
    requested = _strings(manifest_data.get("capabilities"), "manifest.yaml.capabilities", diagnostics)
    supported = tuple(sorted(supported_capabilities))
    unknown = tuple(sorted(set(requested) - supported_capabilities))
    accepted = tuple(sorted(set(requested) & supported_capabilities))
    handshake = CapabilityHandshake(
        requested=tuple(sorted(set(requested))),
        supported=supported,
        accepted=accepted,
        unknown=unknown,
    )
    for capability in unknown:
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_CAPABILITY",
                "manifest.yaml.capabilities",
                f"host does not support capability: {capability}",
            )
        )

    schema_version = str(manifest_data.get("schema_version") or "")
    package_id = str(manifest_data.get("package_id") or "").strip()
    revision = _integer(
        manifest_data.get("revision"),
        "manifest.yaml.revision",
        diagnostics,
        default=-1,
    )
    raw_assets = manifest_data.get("assets")
    if not isinstance(raw_assets, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_ASSETS",
                "manifest.yaml.assets",
                "assets must be an object of name-to-ref entries",
            )
        )
        raw_assets = {}
    else:
        _reject_unknown_fields(
            raw_assets,
            set(REQUIRED_ASSETS),
            "manifest.yaml.assets",
            diagnostics,
        )
    asset_paths: dict[str, Path] = {}
    asset_refs: dict[str, str] = {}
    for name in REQUIRED_ASSETS:
        raw_ref = raw_assets.get(name)
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_ASSET_REF",
                    f"manifest.yaml.assets.{name}",
                    f"required asset ref is missing: {name}",
                )
            )
            continue
        resolved = _safe_ref(root, raw_ref, diagnostics, f"manifest.yaml.assets.{name}")
        if resolved is not None:
            asset_paths[name] = resolved
            asset_refs[name] = raw_ref

    raw_workflows = manifest_data.get("workflows")
    if not isinstance(raw_workflows, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOWS",
                "manifest.yaml.workflows",
                "workflows must be an object of name-to-ref entries",
            )
        )
        raw_workflows = {}
    else:
        _reject_unknown_fields(
            raw_workflows, set(REQUIRED_WORKFLOWS), "manifest.yaml.workflows", diagnostics
        )
    workflow_paths: dict[str, Path] = {}
    workflow_refs: dict[str, str] = {}
    for kind in REQUIRED_WORKFLOWS:
        raw_ref = raw_workflows.get(kind)
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_WORKFLOW_REF",
                    f"manifest.yaml.workflows.{kind}",
                    f"required workflow ref is missing: {kind}",
                )
            )
            continue
        resolved = _safe_ref(root, raw_ref, diagnostics, f"manifest.yaml.workflows.{kind}")
        if resolved is not None:
            workflow_paths[kind] = resolved
            workflow_refs[kind] = raw_ref

    if schema_version != PACKAGE_SCHEMA_VERSION:
        diagnostics.append(
            PackageDiagnostic(
                "UNSUPPORTED_SCHEMA_VERSION",
                "manifest.yaml.schema_version",
                f"expected {PACKAGE_SCHEMA_VERSION}",
            )
        )
    if not package_id:
        diagnostics.append(
            PackageDiagnostic("EMPTY_PACKAGE_ID", "manifest.yaml.package_id", "package_id is required")
        )
    if revision < 0:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_REVISION",
                "manifest.yaml.revision",
                "revision must be a non-negative integer",
            )
        )
    for name, capability in ASSET_CAPABILITIES.items():
        if name in asset_refs and capability not in requested:
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_CAPABILITY",
                    "manifest.yaml.capabilities",
                    f"asset {name} requires capability: {capability}",
                )
            )

    documents: dict[str, dict[str, Any]] = {}
    for name in ("world", "locations", "resources", "passages"):
        path = asset_paths.get(name)
        if path is None:
            continue
        document = _read_object(path, root, diagnostics)
        _reject_unknown_fields(
            document,
            DOCUMENT_FIELDS[f"{name}.yaml"],
            asset_refs[name],
            diagnostics,
        )
        documents[name] = document

    characters_ref = asset_paths.get("characters")
    characters: list[PackageCharacter] = []
    if characters_ref is not None:
        if not characters_ref.is_dir():
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_DIRECTORY",
                    asset_refs["characters"],
                    "characters asset ref must name a directory",
                )
            )
        else:
            characters = _compile_characters(
                characters_ref, root, diagnostics, asset_refs["characters"]
            )

    authored_values: list[tuple[str, Any]] = [
        (asset_refs.get(name, name), value) for name, value in documents.items()
    ]
    for character in characters:
        authored_values.append((f"characters/{character.id}", asdict(character)))
    for path, value in authored_values:
        _find_forbidden_fields(value, path, diagnostics)
    raw_rules = documents.get("world", {}).get("rules")
    if isinstance(raw_rules, list) and all(isinstance(item, dict) for item in raw_rules):
        raw_resources = documents.get("resources", {}).get("resources")
        resource_ids = {
            str(item.get("id"))
            for item in raw_resources
            if isinstance(item, dict) and item.get("id")
        } if isinstance(raw_resources, list) else set()
        _validate_structured_rules(raw_rules, resource_ids, diagnostics)
    _validate_document_schemas(documents, diagnostics)
    compiled_workflows: dict[str, WorkflowDefinition] = {}
    for kind in REQUIRED_WORKFLOWS:
        path = workflow_paths.get(kind)
        if path is None:
            continue
        document = _read_object(path, root, diagnostics)
        compiled_workflows[kind] = compile_workflow(
            kind, workflow_refs[kind], document, diagnostics
        )

    if any(item.severity == "error" for item in diagnostics):
        return PackageCompileResult(None, tuple(diagnostics), handshake)

    world = _build_world(documents, characters, diagnostics)
    if world is None or diagnostics:
        return PackageCompileResult(None, tuple(diagnostics), handshake)
    for rule_type, capability in (
        ("incident", "world.incidents.v1"),
        ("user_gate", "world.user-gates.v1"),
        ("fate_intervention", "world.fate-interventions.v1"),
    ):
        if any(rule.get("type") == rule_type for rule in world.rules) and capability not in requested:
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_CAPABILITY",
                    "manifest.yaml.capabilities",
                    f"rule type {rule_type} requires capability: {capability}",
                )
            )
    if diagnostics:
        return PackageCompileResult(None, tuple(diagnostics), handshake)

    character_ids = {item.id for item in world.characters}
    location_ids = {item.id for item in world.locations}
    evolution_policy = dict(compiled_workflows["evolution"].policy)
    for index, rule in enumerate(world.rules):
        location_id = rule.get("location_id")
        if location_id and location_id not in location_ids:
            diagnostics.append(
                PackageDiagnostic(
                    "UNSAFE_WORKFLOW_REFERENCE",
                    f"world.yaml.rules[{index}].location_id",
                    f"rule references unknown location: {location_id}",
                )
            )
    for field, known in (
        ("hot_character_ids", character_ids),
        ("hot_location_ids", location_ids),
    ):
        for value in evolution_policy.get(field, ()):
            if value not in known:
                diagnostics.append(
                    PackageDiagnostic(
                        "UNSAFE_WORKFLOW_REFERENCE",
                        f"{workflow_refs['evolution']}.policy.{field}",
                        f"workflow references unknown id: {value}",
                    )
                )
    resource_ids = {item.id for item in world.resources}
    for index, phase in enumerate(evolution_policy.get("phase_predicates", ())):
        for predicate_index, predicate in enumerate(phase.get("predicates", ())):
            kind = predicate.get("type")
            references = (
                (("resource_id", resource_ids),)
                if kind == "resource"
                else (
                    ("source_id", character_ids),
                    ("target_id", character_ids),
                )
                if kind == "relationship"
                else ()
            )
            for field, known in references:
                if predicate.get(field) not in known:
                    diagnostics.append(
                        PackageDiagnostic(
                            "UNSAFE_WORKFLOW_REFERENCE",
                            (
                                f"{workflow_refs['evolution']}.policy.phase_predicates"
                                f"[{index}].predicates[{predicate_index}].{field}"
                            ),
                            f"workflow references unknown id: {predicate.get(field)}",
                        )
                    )
    if diagnostics:
        return PackageCompileResult(None, tuple(diagnostics), handshake)

    manifest = PackageManifest(
        schema_version=schema_version,
        package_id=package_id,
        revision=revision,
        capabilities=tuple(sorted(set(requested))),
        assets=tuple(sorted(asset_refs.items())),
        workflows=tuple(sorted(workflow_refs.items())),
    )
    workflow = WorkflowIR(
        genesis=compiled_workflows["genesis"],
        evolution=compiled_workflows["evolution"],
        intervention=compiled_workflows["intervention"],
        presentation=compiled_workflows["presentation"],
    )
    experience = compile_experience_profile(
        documents.get("world", {}).get("experience_profile"),
        world=world,
        presentation=workflow.presentation,
        diagnostics=diagnostics,
    )
    if diagnostics:
        return PackageCompileResult(None, tuple(diagnostics), handshake)
    provisional = CompiledWorld(manifest, workflow, world, experience, "")
    digest = hashlib.sha256(
        canonical_compiled_json(provisional).encode("utf-8")
    ).hexdigest()
    return PackageCompileResult(
        CompiledWorld(manifest, workflow, world, experience, digest),
        (),
        handshake,
    )


def _object_array(value: Any, path: str, diagnostics: list[PackageDiagnostic]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        diagnostics.append(PackageDiagnostic("INVALID_FIELD", path, "expected an array of objects"))
        return []
    return value


def _strings(value: Any, path: str, diagnostics: list[PackageDiagnostic]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        diagnostics.append(PackageDiagnostic("INVALID_CAPABILITIES", path, "capabilities must be an array of strings"))
        return ()
    return tuple(value)


def _integer(value: Any, path: str, diagnostics: list[PackageDiagnostic], *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        diagnostics.append(PackageDiagnostic("INVALID_INTEGER", path, "expected an integer"))
        return default
    return value



