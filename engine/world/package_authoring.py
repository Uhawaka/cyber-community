"""Authoring-policy and source-document schema checks."""

from __future__ import annotations

from typing import Any

from engine.world.package_spec import PackageDiagnostic
from engine.world.package_validation import FORBIDDEN_PREARRANGEMENT_FIELDS, _reject_unknown_fields

def _find_forbidden_fields(value: Any, path: str, diagnostics: list[PackageDiagnostic]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_PREARRANGEMENT_FIELDS:
                diagnostics.append(
                    PackageDiagnostic(
                        "PREARRANGED_FIELD",
                        child_path,
                        f"autonomous packages cannot prescribe {key}",
                    )
                )
            _find_forbidden_fields(child, child_path, diagnostics)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _find_forbidden_fields(child, f"{path}[{index}]", diagnostics)



def _validate_document_schemas(
    documents: dict[str, dict[str, Any]], diagnostics: list[PackageDiagnostic]
) -> None:
    schemas = (
        (
            "locations",
            "locations",
            {
                "id", "name", "description", "tags", "allow_avatar_entry",
                "capacity", "access_tags", "allowed_roles", "affordances",
                "danger", "metadata", "scene_seeds",
            },
        ),
        (
            "resources",
            "resources",
            {
                "id", "name", "location_id", "quantity", "owner_id",
                "container_id", "required_skills", "properties",
            },
        ),
        (
            "passages",
            "passages",
            {"id", "origin_id", "destination_id", "travel_time", "properties"},
        ),
    )
    for document_name, field, allowed in schemas:
        values = documents.get(document_name, {}).get(field)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if isinstance(value, dict):
                _reject_unknown_fields(
                    value, allowed, f"{document_name}.yaml.{field}[{index}]", diagnostics
                )
                if (
                    document_name == "locations"
                    and "allow_avatar_entry" in value
                    and not isinstance(value["allow_avatar_entry"], bool)
                ):
                    diagnostics.append(
                        PackageDiagnostic(
                            "INVALID_FIELD",
                            f"locations.yaml.locations[{index}].allow_avatar_entry",
                            "allow_avatar_entry must be boolean",
                        )
                    )
                if document_name == "locations":
                    _validate_location_shape(value, index, diagnostics)
                elif document_name == "resources":
                    _validate_resource_shape(value, index, diagnostics)
    metadata = documents.get("world", {}).get("metadata")
    if isinstance(metadata, dict):
        _reject_unknown_fields(
            metadata, {"language", "mode"}, "world.yaml.metadata", diagnostics
        )


def _string_array(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _validate_location_shape(
    value: dict[str, Any], index: int, diagnostics: list[PackageDiagnostic]
) -> None:
    path = f"locations.yaml.locations[{index}]"
    capacity = value.get("capacity")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_LOCATION_CAPACITY",
                f"{path}.capacity",
                "capacity must be a positive integer",
            )
        )
    danger = value.get("danger")
    if isinstance(danger, bool) or not isinstance(danger, int) or not 0 <= danger <= 100:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_LOCATION_DANGER",
                f"{path}.danger",
                "danger must be an integer from 0 through 100",
            )
        )
    for field in ("tags", "access_tags", "allowed_roles"):
        if not _string_array(value.get(field)):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_FIELD", f"{path}.{field}", f"{field} must be an array of non-empty strings"
                )
            )
    affordances = value.get("affordances")
    allowed = {"observe", "rest", "gather", "social"}
    if not isinstance(affordances, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_LOCATION_AFFORDANCES",
                f"{path}.affordances",
                "affordances must be an object",
            )
        )
    else:
        _reject_unknown_fields(affordances, allowed, f"{path}.affordances", diagnostics)
        if set(affordances) != allowed or any(
            not isinstance(item, bool) for item in affordances.values()
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_LOCATION_AFFORDANCES",
                    f"{path}.affordances",
                    "observe, rest, gather and social boolean switches are required",
                )
            )
    if not isinstance(value.get("metadata"), dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FIELD", f"{path}.metadata", "metadata must be an object"
            )
        )
    scene_seeds = value.get("scene_seeds", [])
    if not isinstance(scene_seeds, list):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FIELD",
                f"{path}.scene_seeds",
                "scene_seeds must be an array",
            )
        )
    else:
        keys: list[str] = []
        for scene_index, scene in enumerate(scene_seeds):
            scene_path = f"{path}.scene_seeds[{scene_index}]"
            if not isinstance(scene, dict):
                diagnostics.append(
                    PackageDiagnostic(
                        "INVALID_FIELD",
                        scene_path,
                        "scene seed must be an object",
                    )
                )
                continue
            _reject_unknown_fields(
                scene,
                {
                    "key",
                    "name",
                    "premise",
                    "tags",
                    "dramatic_question",
                    "failure_pressure",
                    "closure_signals",
                },
                scene_path,
                diagnostics,
            )
            for field in ("key", "name", "premise"):
                if (
                    not isinstance(scene.get(field), str)
                    or not scene[field].strip()
                ):
                    diagnostics.append(
                        PackageDiagnostic(
                            "INVALID_FIELD",
                            f"{scene_path}.{field}",
                            f"{field} must be non-empty text",
                        )
                    )
            if not _string_array(scene.get("tags")):
                diagnostics.append(
                    PackageDiagnostic(
                        "INVALID_FIELD",
                        f"{scene_path}.tags",
                        "tags must be an array of non-empty strings",
                    )
                )
            for field in ("dramatic_question", "failure_pressure"):
                if field in scene and (
                    not isinstance(scene[field], str)
                    or not scene[field].strip()
                ):
                    diagnostics.append(
                        PackageDiagnostic(
                            "INVALID_FIELD",
                            f"{scene_path}.{field}",
                            f"{field} must be non-empty text",
                        )
                    )
            if "closure_signals" in scene and (
                not _string_array(scene["closure_signals"])
                or not scene["closure_signals"]
            ):
                diagnostics.append(
                    PackageDiagnostic(
                        "INVALID_FIELD",
                        f"{scene_path}.closure_signals",
                        "closure_signals must be non-empty strings",
                    )
                )
            if isinstance(scene.get("key"), str):
                keys.append(scene["key"])
        if len(keys) != len(set(keys)):
            diagnostics.append(
                PackageDiagnostic(
                    "DUPLICATE_ID",
                    f"{path}.scene_seeds",
                    "scene seed keys must be unique within a location",
                )
            )


def _validate_resource_shape(
    value: dict[str, Any], index: int, diagnostics: list[PackageDiagnostic]
) -> None:
    path = f"resources.yaml.resources[{index}]"
    for field in ("owner_id", "container_id"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_RESOURCE_OWNERSHIP",
                    f"{path}.{field}",
                    f"{field} is required",
                )
            )
    if not _string_array(value.get("required_skills")):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FIELD",
                f"{path}.required_skills",
                "required_skills must be an array of non-empty strings",
            )
        )


