"""Compile a character-authored relationship graph.

Edges record one person's stance and interest. They do not schedule a
conflict, a dialogue, or an outcome.
"""

from __future__ import annotations

from typing import Any

from engine.world.package_spec import PackageDiagnostic, RelationshipEdge
from engine.world.package_validation import _reject_unknown_fields


def compile_relationships(
    document: dict[str, Any],
    character_ids: set[str],
    ref: str,
    diagnostics: list[PackageDiagnostic],
) -> tuple[RelationshipEdge, ...]:
    _reject_unknown_fields(document, {"edges"}, ref, diagnostics)
    raw_edges = document.get("edges", [])
    if not isinstance(raw_edges, list) or any(not isinstance(item, dict) for item in raw_edges):
        diagnostics.append(
            PackageDiagnostic("INVALID_RELATIONSHIPS", f"{ref}.edges", "edges must be an array of objects")
        )
        return ()
    edges: list[RelationshipEdge] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_edges):
        path = f"{ref}.edges[{index}]"
        _reject_unknown_fields(
            item, {"source_id", "target_id", "stance", "interest"}, path, diagnostics
        )
        source_id = str(item.get("source_id") or "").strip()
        target_id = str(item.get("target_id") or "").strip()
        stance = item.get("stance")
        interest = item.get("interest")
        if source_id not in character_ids or target_id not in character_ids:
            diagnostics.append(
                PackageDiagnostic(
                    "UNKNOWN_CHARACTER",
                    path,
                    "relationship edge must name two characters in this package",
                )
            )
            continue
        if source_id == target_id:
            diagnostics.append(
                PackageDiagnostic("INVALID_RELATIONSHIP", path, "an edge must address someone else")
            )
            continue
        if not isinstance(stance, str) or not stance.strip():
            diagnostics.append(
                PackageDiagnostic("INVALID_RELATIONSHIP", f"{path}.stance", "stance must be a non-empty string")
            )
            continue
        if not isinstance(interest, str) or not interest.strip():
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_RELATIONSHIP", f"{path}.interest", "interest must be a non-empty string"
                )
            )
            continue
        key = (source_id, target_id)
        if key in seen:
            diagnostics.append(
                PackageDiagnostic("DUPLICATE_RELATIONSHIP", path, "each directed pair may appear once")
            )
            continue
        seen.add(key)
        edges.append(RelationshipEdge(source_id, target_id, stance.strip(), interest.strip()))
    return tuple(edges)
