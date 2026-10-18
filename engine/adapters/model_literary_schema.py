"""Schema decoding and prose-safe fact selection for literary stages."""

from __future__ import annotations

from engine.adapters.model_narrative_facts import quote_excerpt
from engine.contracts import SourcedDraft, SourcedParagraph


def decode_draft(
    value: dict[str, object], available_ids: tuple[str, ...]
) -> SourcedDraft:
    title = value.get("title")
    paragraphs = value.get("paragraphs")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("sourced draft requires title")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("sourced draft requires paragraphs")
    available = set(available_ids)
    positions = {
        source_id: index for index, source_id in enumerate(available_ids)
    }
    result: list[SourcedParagraph] = []
    last_position = -1
    for item in paragraphs:
        if not isinstance(item, dict) or set(item) != {
            "source_event_ids",
            "text",
        }:
            raise ValueError("invalid sourced paragraph")
        source_ids = item["source_event_ids"]
        text = item["text"]
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or any(
                not isinstance(source_id, str)
                or source_id not in available
                for source_id in source_ids
            )
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("invalid sourced paragraph content")
        source_positions = [positions[source_id] for source_id in source_ids]
        if (
            source_positions != sorted(source_positions)
            or source_positions[0] < last_position
        ):
            raise ValueError("sourced draft provenance is not globally ordered")
        last_position = source_positions[-1]
        result.append(SourcedParagraph(tuple(source_ids), text.strip()))
    return SourcedDraft(title.strip(), tuple(result))


def writing_facts(
    facts: list[dict[str, object]],
    *,
    selected_source_ids: set[str],
    direct_quote_source_ids: set[str],
) -> list[dict[str, object]]:
    return [
        {
            **item,
            "dialogue": (
                quote_excerpt(str(item["dialogue"]))
                if item["source_event_id"] in direct_quote_source_ids
                and item["dialogue"]
                else None
            ),
        }
        for item in facts
        if item["source_event_id"] in selected_source_ids
        or item["kind"] == "scene_instantiated"
    ]
