"""Cross-reference validation for compiled package entities."""

from __future__ import annotations

from engine.world.package_spec import (
    PackageCharacter,
    PackageDiagnostic,
    PackageLocation,
    PackagePassage,
    PackageResource,
)

MAX_LOCATIONS = 256
MAX_RESOURCES = 512
MAX_PASSAGES = 1_024


def _validate_entities(
    locations: tuple[PackageLocation, ...],
    characters: list[PackageCharacter],
    resources: tuple[PackageResource, ...],
    passages: tuple[PackagePassage, ...],
    diagnostics: list[PackageDiagnostic],
) -> None:
    for values, limit, path in (
        (locations, MAX_LOCATIONS, "locations.yaml.locations"),
        (resources, MAX_RESOURCES, "resources.yaml.resources"),
        (passages, MAX_PASSAGES, "passages.yaml.passages"),
    ):
        if len(values) > limit:
            diagnostics.append(PackageDiagnostic("LIMIT_EXCEEDED", path, f"at most {limit} entities are allowed"))
    for values, path in (
        (locations, "locations.yaml.locations"),
        (characters, "characters"),
        (resources, "resources.yaml.resources"),
        (passages, "passages.yaml.passages"),
    ):
        _unique_ids([item.id for item in values], path, diagnostics)
    location_ids = {item.id for item in locations}
    location_by_id = {item.id: item for item in locations}
    for item in locations:
        if not item.name:
            diagnostics.append(PackageDiagnostic("MISSING_FIELD", f"locations.{item.id}.name", "name is required"))
        if item.capacity < 1 or not 0 <= item.danger <= 100:
            diagnostics.append(PackageDiagnostic("INVALID_LOCATION", f"locations.{item.id}", "location needs positive capacity and danger from 0 through 100"))
    for item in characters:
        if not item.name or not item.role or not item.location_id:
            diagnostics.append(PackageDiagnostic("INCOMPLETE_CHARACTER", f"characters.{item.id}.profile.yaml", "name, role, and location_id are required"))
        if item.location_id not in location_ids:
            diagnostics.append(PackageDiagnostic("UNKNOWN_LOCATION", f"characters.{item.id}.location_id", item.location_id))
            continue
        location = location_by_id[item.location_id]
        profile = dict(item.profile)
        for field, known in (
            ("responsibilities", {r.id for r in resources}),
            ("stocking_interests", {r.id for r in resources}),
            ("known_routes", {p.id for p in passages}),
            ("routine_locations", location_ids),
        ):
            if not set(profile.get(field, ())) <= known:
                diagnostics.append(PackageDiagnostic(
                    "UNKNOWN_PROFILE_REFERENCE", f"characters.{item.id}.profile.yaml.{field}",
                    "profile references unknown world entities",
                ))
        if profile.get("home_location_id", item.location_id) not in location_ids:
            diagnostics.append(PackageDiagnostic(
                "UNKNOWN_PROFILE_REFERENCE", f"characters.{item.id}.profile.yaml.home_location_id",
                "home must be an existing location",
            ))
        actor_tags = {
            str(tag) for tag in profile.get("access_tags", ())
        } if isinstance(profile.get("access_tags", ()), list) else set()
        if location.allowed_roles and item.role not in location.allowed_roles:
            diagnostics.append(PackageDiagnostic("LOCATION_ACCESS_DENIED", f"characters.{item.id}.location_id", f"role {item.role} is not allowed at {item.location_id}"))
        if not set(location.access_tags).issubset(actor_tags):
            diagnostics.append(PackageDiagnostic("LOCATION_ACCESS_DENIED", f"characters.{item.id}.location_id", f"character lacks access tags for {item.location_id}"))
    occupancy = {
        location.id: sum(item.location_id == location.id for item in characters)
        for location in locations
    }
    for item in locations:
        if occupancy[item.id] > item.capacity:
            diagnostics.append(PackageDiagnostic("LOCATION_OVER_CAPACITY", f"locations.{item.id}.capacity", "initial character occupancy exceeds capacity"))
    for item in resources:
        if (
            not item.name or item.location_id not in location_ids or item.quantity < 0
            or item.owner_id != item.location_id or item.container_id != item.location_id
        ):
            diagnostics.append(PackageDiagnostic("INVALID_RESOURCE", f"resources.{item.id}", "resource needs a name, non-negative quantity, and owner/container equal to location_id"))
    for item in passages:
        if (
            item.origin_id not in location_ids or item.destination_id not in location_ids
            or item.origin_id == item.destination_id or item.travel_time <= 0
        ):
            diagnostics.append(PackageDiagnostic("INVALID_PASSAGE", f"passages.{item.id}", "passage must connect distinct known locations with positive travel time"))
        properties = dict(item.properties)
        allowed = {"required_access_tags", "allowed_roles", "required_skills"}
        unknown = set(properties) - allowed
        if unknown:
            diagnostics.append(PackageDiagnostic("UNKNOWN_PASSAGE_PROPERTY", f"passages.{item.id}.properties", f"unsupported passage properties: {', '.join(sorted(unknown))}"))
        for field in allowed.intersection(properties):
            value = properties[field]
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(entry, str) or not entry.strip() for entry in value
            ):
                diagnostics.append(PackageDiagnostic("INVALID_PASSAGE_PROPERTY", f"passages.{item.id}.properties.{field}", f"{field} must be an array of non-empty strings"))


def _unique_ids(
    ids: list[str], path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    seen: set[str] = set()
    for index, item_id in enumerate(ids):
        if not item_id:
            diagnostics.append(PackageDiagnostic("EMPTY_ID", f"{path}[{index}].id", "id is required"))
        elif item_id in seen:
            diagnostics.append(PackageDiagnostic("DUPLICATE_ID", f"{path}[{index}].id", item_id))
        seen.add(item_id)
