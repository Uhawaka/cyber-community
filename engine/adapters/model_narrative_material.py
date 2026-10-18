"""Serialize fact-bounded narrative material for literary skill stages."""

from __future__ import annotations

from engine.adapters.model_narrative_facts import (
    writing_changes,
    writing_context,
)
from engine.narrative.curation import is_reader_visible_source
from engine.narrative.planning import NarrativeRenderRequest


def narrative_material(
    request: NarrativeRenderRequest,
) -> tuple[list[dict[str, object]], dict[str, object], list[str]]:
    curated_ids = {
        source_id
        for beat in request.plan.beats
        for source_id in beat.source_event_ids
    }
    facts = [
        {
            "source_event_id": entry.source_event_id,
            "kind": entry.kind,
            "summary": entry.summary,
            "dialogue": entry.dialogue,
            "actor_id": entry.actor_id,
            "location_id": entry.location_id,
            "target_id": entry.target_id,
            "goal": entry.goal,
            "causal_source_ids": list(entry.causal_source_ids),
            "changes": writing_changes(entry),
            "authorized_context": writing_context(entry),
        }
        for entry in request.digest.entries
        if (
            entry.source_event_id in curated_ids
            or entry.kind in {"scene_instantiated", "scene_evolved"}
        )
        and is_reader_visible_source(entry)
        and entry.kind != "gate_opened"
    ]
    available = {str(item["source_event_id"]) for item in facts}
    plan = {
        "focus_character_id": request.plan.focus_character_id,
        "focus_location_id": request.plan.focus_location_id,
        "theme": request.plan.theme,
        "scene_goal": request.plan.scene_goal,
        "turning_point_source_id": _available(
            request.plan.turning_point_source_id, available
        ),
        "opposition_source_ids": _available_many(
            request.plan.opposition_source_ids, available
        ),
        "outcome_source_ids": _available_many(
            request.plan.outcome_source_ids, available
        ),
        "beats": [
            {
                "source_event_ids": _available_many(
                    beat.source_event_ids, available
                ),
                "relation": beat.relation,
                "function": beat.function,
                "summary": beat.summary,
            }
            for beat in request.plan.beats
            if set(beat.source_event_ids).intersection(available)
        ],
    }
    lore = sorted(
        {
            description
            for entry in request.digest.entries
            if (
                entry.source_event_id in curated_ids
                and entry.location_id == request.plan.focus_location_id
            )
            for key, description in entry.facts.items()
            if key
            in {
                "location_description",
                "scene_description",
                "scene_elements",
            }
            and isinstance(description, str)
            and description
        }
    )
    return facts, plan, lore


def _available(value: str, available: set[str]) -> str | None:
    return value if value in available else None


def _available_many(
    values: tuple[str, ...], available: set[str]
) -> list[str]:
    return [value for value in values if value in available]
