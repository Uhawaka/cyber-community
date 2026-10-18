"""Minimal, prose-safe views over narrative digest entries."""

from __future__ import annotations

import re


def writing_context(entry: object) -> dict[str, object]:
    kind = getattr(entry, "kind", "")
    facts = dict(getattr(entry, "facts", ()))
    if kind == "scene_instantiated":
        allowed = {
            "scene_description",
            "scene_elements",
            "location_description",
            "entry_anchor_id",
            "scene_id",
        }
    else:
        allowed = {
            "turn_resolved": {
                "public_action",
                "status",
                "goal",
                "scene_id",
                "scene_transition",
                "item_custody_updates",
                "dramatic_progress",
                "scene_outcome",
                "decision",
            },
            "incident_occurred": {"summary", "target_entity_id"},
            "user_intervention": {"observation", "choice_id"},
            "scene_evolved": {"summary", "recent_world_events"},
        }.get(kind, set())
    selected = {
        key: value for key, value in facts.items() if key in allowed
    }
    if kind == "turn_resolved":
        selected.update(
            {
                key: value
                for key, value in facts.items()
                if key.startswith("component:")
                and key.endswith(":attributes")
                and isinstance(value, str)
                and value.startswith("observed_traces=")
            }
        )
    return selected


def quote_excerpt(value: object, limit: int = 35) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    clauses = [
        item.strip(" ，。！？；：—")
        for item in re.split(r"[。！？；]|——", value)
        if item.strip(" ，。！？；：—")
    ]
    fitting = [item for item in clauses if len(item) <= limit]
    return (fitting[-1] if fitting else value[:limit]).strip()


def writing_changes(entry: object) -> list[dict[str, object]]:
    if getattr(entry, "kind", "") != "turn_resolved":
        return []
    return [
        {
            "category": change.category,
            "subject_id": change.subject_id,
            "target_id": change.target_id,
            "value": change.value,
        }
        for change in getattr(entry, "changes", ())
        if change.category in {"inventory", "presence"}
    ]
