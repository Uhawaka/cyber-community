"""Build typed compiled-world values from validated documents."""

from __future__ import annotations

from typing import Any

from engine.world.package_spec import (
    AutonomousWorldSpec,
    DramaticHorizon,
    PackageCharacter,
    PackageDiagnostic,
    PackageLocation,
    PackagePassage,
    PackageResource,
    PackageSceneSeed,
)
from engine.world.package_validation import MAX_RULES
from engine.world.package_entities import _validate_entities


def _object_array(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        diagnostics.append(
            PackageDiagnostic("INVALID_FIELD", path, "expected an array of objects")
        )
        return []
    return value


def _integer(
    value: Any,
    path: str,
    diagnostics: list[PackageDiagnostic],
    *,
    default: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        diagnostics.append(PackageDiagnostic("INVALID_INTEGER", path, "expected an integer"))
        return default
    return value


def _pairs(value: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(value.items()))


def _build_world(
    documents: dict[str, dict[str, Any]],
    characters: list[PackageCharacter],
    diagnostics: list[PackageDiagnostic],
) -> AutonomousWorldSpec | None:
    world_data = documents.get("world", {})
    world_id = str(world_data.get("world_id") or "").strip()
    title = str(world_data.get("title") or "").strip()
    premise = str(world_data.get("premise") or "").strip()
    for key, value in (("world_id", world_id), ("title", title), ("premise", premise)):
        if not value:
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_FIELD", f"world.yaml.{key}", f"{key} is required"
                )
            )

    locations = tuple(
        sorted(
            (
                PackageLocation(
                    id=str(item.get("id") or "").strip(),
                    name=str(item.get("name") or "").strip(),
                    description=str(item.get("description") or ""),
                    tags=tuple(str(tag) for tag in item.get("tags", ())),
                    allow_avatar_entry=item.get("allow_avatar_entry", False) is True,
                    capacity=_integer(
                        item.get("capacity"),
                        "locations.yaml.locations.capacity",
                        diagnostics,
                        default=0,
                    ),
                    access_tags=tuple(str(tag) for tag in item.get("access_tags", ())),
                    allowed_roles=tuple(str(role) for role in item.get("allowed_roles", ())),
                    affordances=_pairs(item.get("affordances")),
                    danger=_integer(
                        item.get("danger"),
                        "locations.yaml.locations.danger",
                        diagnostics,
                        default=-1,
                    ),
                    metadata=_pairs(item.get("metadata")),
                    scene_seeds=tuple(
                        PackageSceneSeed(
                            key=str(scene.get("key") or "").strip(),
                            name=str(scene.get("name") or "").strip(),
                            premise=str(
                                scene.get("premise") or ""
                            ).strip(),
                            tags=tuple(
                                str(tag)
                                for tag in scene.get("tags", ())
                            ),
                            dramatic_question=str(
                                scene.get("dramatic_question") or ""
                            ).strip(),
                            failure_pressure=str(
                                scene.get("failure_pressure") or ""
                            ).strip(),
                            closure_signals=tuple(
                                str(item)
                                for item in scene.get(
                                    "closure_signals", ()
                                )
                            ),
                        )
                        for scene in item.get("scene_seeds", ())
                    ),
                )
                for item in _object_array(
                    documents.get("locations", {}).get("locations"),
                    "locations.yaml.locations",
                    diagnostics,
                )
            ),
            key=lambda item: item.id,
        )
    )
    resources = tuple(
        sorted(
            (
                PackageResource(
                    id=str(item.get("id") or "").strip(),
                    name=str(item.get("name") or "").strip(),
                    location_id=str(item.get("location_id") or "").strip(),
                    quantity=_integer(
                        item.get("quantity", 1),
                        "resources.yaml.resources.quantity",
                        diagnostics,
                        default=0,
                    ),
                    owner_id=str(item.get("owner_id") or "").strip(),
                    container_id=str(item.get("container_id") or "").strip(),
                    required_skills=tuple(
                        str(skill) for skill in item.get("required_skills", ())
                    ),
                    properties=_pairs(item.get("properties")),
                )
                for item in _object_array(
                    documents.get("resources", {}).get("resources"),
                    "resources.yaml.resources",
                    diagnostics,
                )
            ),
            key=lambda item: item.id,
        )
    )
    passages = tuple(
        sorted(
            (
                PackagePassage(
                    id=str(item.get("id") or "").strip(),
                    origin_id=str(item.get("origin_id") or "").strip(),
                    destination_id=str(item.get("destination_id") or "").strip(),
                    travel_time=_integer(
                        item.get("travel_time", 1),
                        "passages.yaml.passages.travel_time",
                        diagnostics,
                        default=0,
                    ),
                    properties=_pairs(item.get("properties")),
                )
                for item in _object_array(
                    documents.get("passages", {}).get("passages"),
                    "passages.yaml.passages",
                    diagnostics,
                )
            ),
            key=lambda item: item.id,
        )
    )
    _validate_entities(locations, characters, resources, passages, diagnostics)
    rules = world_data.get("rules", ())
    if not isinstance(rules, list) or any(not isinstance(item, dict) for item in rules):
        diagnostics.append(
            PackageDiagnostic("INVALID_FIELD", "world.yaml.rules", "rules must be an array of objects")
        )
        rules = []
    if len(rules) > MAX_RULES:
        diagnostics.append(
            PackageDiagnostic(
                "LIMIT_EXCEEDED",
                "world.yaml.rules",
                f"at most {MAX_RULES} rules are allowed",
            )
        )
    metadata = world_data.get("metadata")
    horizon = _dramatic_horizon(
        world_data.get("dramatic_horizon"), diagnostics
    )
    if diagnostics:
        return None
    return AutonomousWorldSpec(
        world_id=world_id,
        title=title,
        premise=premise,
        locations=locations,
        characters=tuple(sorted(characters, key=lambda item: item.id)),
        resources=resources,
        passages=passages,
        rules=tuple(rules),
        metadata=_pairs(metadata),
        dramatic_horizon=horizon,
    )


def _dramatic_horizon(
    value: object, diagnostics: list[PackageDiagnostic]
) -> DramaticHorizon | None:
    if value is None:
        return None
    path = "world.yaml.dramatic_horizon"
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_DRAMATIC_HORIZON",
                path,
                "dramatic_horizon must be an object",
            )
        )
        return None
    allowed = {
        "central_question",
        "success_conditions",
        "failure_conditions",
        "invariants",
    }
    if set(value) - allowed:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_DRAMATIC_HORIZON",
                path,
                "dramatic_horizon contains unknown fields",
            )
        )
        return None
    central = str(value.get("central_question") or "").strip()
    success = value.get("success_conditions")
    failure = value.get("failure_conditions")
    invariants = value.get("invariants", ())
    arrays = (success, failure, invariants)
    if (
        not central
        or any(
            not isinstance(items, (list, tuple))
            or not all(
                isinstance(item, str) and item.strip()
                for item in items
            )
            for items in arrays
        )
        or not success
        or not failure
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_DRAMATIC_HORIZON",
                path,
                "horizon requires a question and non-empty success/failure conditions",
            )
        )
        return None
    return DramaticHorizon(
        central,
        tuple(success),
        tuple(failure),
        tuple(invariants),
    )

