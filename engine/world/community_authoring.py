"""Closed, data-only author sources for reproducible community packages."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from engine.world.package_compiler import compile_package
from engine.world.package_publish import publish_directory
from engine.world.package_source import MAX_DOCUMENT_BYTES, _validate_value_limits

AUTHOR_SCHEMA_VERSION = "community-authoring/v1"
WORKFLOW_KINDS = ("genesis", "evolution", "intervention", "presentation")
ASSETS = {name: f"{name}.yaml" for name in (
    "world", "locations", "resources", "passages", "relationships", "community",
)}
ASSETS["characters"] = "characters"
CAPABILITIES = (
    "world.core.v1", "world.characters.v1", "world.memory-seed.v1",
    "world.resources.v1", "world.topology.v1", "world.relationships.v1", "world.community.v1",
)
SOURCE_FIELDS = {
    "schema_version", "package_id", "revision", "world", "locations", "resources",
    "passages", "relationships", "characters", "community", "workflows",
}


def _identifier(value, field):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value) is None:
        raise ValueError(f"{field} must be a safe directory identifier")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate author field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"non-finite author number: {value}")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        _reject_constant(value)
    return number


def load_community_source(path):
    path = Path(path)
    with path.open("rb") as stream:
        payload = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError("author source exceeds document byte limit")
    try:
        source = json.loads(payload, object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant, parse_float=_finite_float)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid author JSON: {exc}") from exc
    diagnostics = []
    _validate_value_limits(source, str(path), diagnostics)
    if diagnostics:
        raise ValueError(diagnostics)
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
        raise ValueError("author source has missing or unknown fields")
    if source["schema_version"] != AUTHOR_SCHEMA_VERSION:
        raise ValueError("unsupported community author schema")
    _identifier(source["package_id"], "package_id")
    revision = source["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    for field in ("world", "community", "workflows", "characters"):
        if not isinstance(source[field], dict):
            raise ValueError(f"{field} must be an object")
    for field in ("locations", "resources", "passages", "relationships"):
        if not isinstance(source[field], list) or any(not isinstance(row, dict) for row in source[field]):
            raise ValueError(f"{field} must be an array of objects")
    if set(source["workflows"]) != set(WORKFLOW_KINDS):
        raise ValueError("all four registered workflows must be provided")
    if not source["characters"]:
        raise ValueError("community author source requires characters")
    for actor_id, person in source["characters"].items():
        _identifier(actor_id, "character id")
        if not isinstance(person, dict) or set(person) != {"profile", "soul", "memory"}:
            raise ValueError("character requires exactly profile, soul and memory")
        if not isinstance(person["profile"], dict) or not isinstance(person["soul"], dict):
            raise ValueError("character profile and soul must be objects")
        if not isinstance(person["memory"], list):
            raise ValueError("character memory must be an array")
    return source


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _author(directory, source):
    _write(directory / "manifest.yaml", {
        "schema_version": "world-package/v1alpha3",
        "package_id": source["package_id"], "revision": source["revision"],
        "capabilities": CAPABILITIES, "assets": ASSETS,
        "workflows": {kind: f"workflows/{kind}.yaml" for kind in WORKFLOW_KINDS},
    })
    for field in ("world", "community"):
        _write(directory / ASSETS[field], source[field])
    for field in ("locations", "resources", "passages"):
        _write(directory / ASSETS[field], {field: source[field]})
    _write(directory / ASSETS["relationships"], {"edges": source["relationships"]})
    for actor_id, person in source["characters"].items():
        actor = directory / "characters" / actor_id
        for field, filename in (("profile", "profile.yaml"), ("soul", "soul.yaml"), ("memory", "memory.seed.json")):
            _write(actor / filename, person[field])
    for kind in WORKFLOW_KINDS:
        _write(directory / "workflows" / f"{kind}.yaml", source["workflows"][kind])


def build_community_package(source_path, destination):
    """Validate in private staging, then publish without replacing any path."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination already exists; existing worlds are never overwritten")
    if not destination.parent.is_dir():
        raise ValueError("destination parent must already exist")
    source = load_community_source(source_path)
    with TemporaryDirectory(prefix=".community-author-", dir=destination.parent) as scratch:
        stage = Path(scratch) / "package"
        _author(stage, source)
        result = compile_package(stage)
        if not result.ok:
            raise ValueError(result.diagnostics)
        if result.compiled.community is None:
            raise ValueError("author source must compile as a community package")
        publish_directory(stage, destination)
    return destination
