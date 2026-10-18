"""Fact and prose-quality gates for rendered narrative."""

from __future__ import annotations

import json
import re

from engine.narrative.digest import NarrativeDigest
from engine.narrative.planning import (
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    build_narrative_plan,
    validate_narrative_plan,
)
from engine.narrative.rendering import (
    RenderedNarrative,
    StructuredLiteraryRenderer,
)
from engine.narrative.skills import get_literary_skill, get_world_voice


_QUOTED_TEXT = re.compile(
    r"“([^”]+)”|\"([^\"]+)\"|「([^」]+)」|『([^』]+)』"
)
_BRACKETED_SOURCE_ID = re.compile(r"\[([^\]\n]+)\]")
_ENTITY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])"
)
_INTERIORITY_MARKERS = ("心想", "想：", "意识到", "觉得", "暗自")


def validate_rendered_facts(
    rendered: RenderedNarrative,
    value: NarrativeRenderRequest | NarrativeDigest,
) -> bool:
    """Reject invented direct quotes, provenance, or key entity identifiers."""

    request = _render_request(value)
    digest = request.digest
    if not validate_narrative_plan(request.plan, digest):
        return False
    if rendered.non_factual_atmosphere:
        return False
    if any(
        phrase and phrase in f"{rendered.title}\n{rendered.body}"
        for phrase in request.style.forbidden_phrases
    ):
        return False
    source_positions = {
        source_id: index
        for index, source_id in enumerate(digest.source_event_ids)
    }
    for entry in digest.entries:
        entry_position = source_positions[entry.source_event_id]
        if any(
            source_positions.get(source_id, -1) >= entry_position
            for source_id in entry.causal_source_ids
            if source_id in source_positions
        ):
            return False
    text = f"{rendered.title}\n{rendered.body}"
    quotes = {
        next(group for group in match if group)
        for match in _QUOTED_TEXT.findall(text)
    }
    if any(not _authorized_quote(quote, digest) for quote in quotes):
        return False
    authorized_text = "\n".join(
        "\n".join(
            (
                entry.summary,
                entry.utterance or "",
                json.dumps(
                    dict(entry.facts), ensure_ascii=False, sort_keys=True
                ),
            )
        )
        for entry in digest.entries
    )
    if any(
        marker in text and marker not in authorized_text
        for marker in _INTERIORITY_MARKERS
    ):
        return False
    source_ids = set(digest.source_event_ids)
    cited_ids = set(_BRACKETED_SOURCE_ID.findall(text))
    if not cited_ids.issubset(source_ids):
        return False
    ordered_citations = [
        source_positions[source_id]
        for source_id in _BRACKETED_SOURCE_ID.findall(text)
    ]
    if ordered_citations != sorted(ordered_citations):
        return False
    if rendered.paragraphs:
        last_position = -1
        for paragraph in rendered.paragraphs:
            if not paragraph.source_event_ids or not paragraph.text.strip():
                return False
            positions: list[int] = []
            for source_id in paragraph.source_event_ids:
                if source_id not in source_positions:
                    return False
                positions.append(source_positions[source_id])
            if positions != sorted(positions) or positions[0] < last_position:
                return False
            last_position = positions[-1]
        if "\n\n".join(
            paragraph.text for paragraph in rendered.paragraphs
        ) != rendered.body:
            return False
    rendered_entity_tokens = set(_ENTITY_TOKEN.findall(text))
    return rendered_entity_tokens.issubset(_digest_entity_tokens(digest))


def rendered_fact_issues(
    rendered: RenderedNarrative,
    value: NarrativeRenderRequest | NarrativeDigest,
) -> tuple[str, ...]:
    """Return actionable diagnostics without weakening the fact gate."""

    request = _render_request(value)
    digest = request.digest
    issues: list[str] = []
    if not validate_narrative_plan(request.plan, digest):
        issues.append("invalid_narrative_plan")
    if rendered.non_factual_atmosphere:
        issues.append("non_factual_atmosphere")
    text = f"{rendered.title}\n{rendered.body}"
    for phrase in request.style.forbidden_phrases:
        if phrase and phrase in text:
            issues.append(f"forbidden_phrase:{phrase}")
    source_positions = {
        source_id: index
        for index, source_id in enumerate(digest.source_event_ids)
    }
    if any(
        source_positions.get(source_id, -1)
        >= source_positions[entry.source_event_id]
        for entry in digest.entries
        for source_id in entry.causal_source_ids
        if source_id in source_positions
    ):
        issues.append("invalid_causal_order")
    for quote in {
        next(group for group in match if group)
        for match in _QUOTED_TEXT.findall(text)
    }:
        if not _authorized_quote(quote, digest):
            issues.append(f"unauthorized_quote:{quote[:80]}")
    authorized_text = "\n".join(
        entry.summary
        + "\n"
        + (entry.utterance or "")
        + "\n"
        + json.dumps(dict(entry.facts), ensure_ascii=False, sort_keys=True)
        for entry in digest.entries
    )
    for marker in _INTERIORITY_MARKERS:
        if marker in text and marker not in authorized_text:
            issues.append(f"unauthorized_interiority:{marker}")
    citations = _BRACKETED_SOURCE_ID.findall(text)
    if any(source_id not in source_positions for source_id in citations):
        issues.append("unknown_inline_source")
    elif [source_positions[item] for item in citations] != sorted(
        source_positions[item] for item in citations
    ):
        issues.append("unordered_inline_sources")
    if rendered.paragraphs:
        last_position = -1
        for paragraph in rendered.paragraphs:
            positions = [
                source_positions[source_id]
                for source_id in paragraph.source_event_ids
                if source_id in source_positions
            ]
            if (
                not paragraph.source_event_ids
                or len(positions) != len(paragraph.source_event_ids)
                or positions != sorted(positions)
                or (positions and positions[0] < last_position)
            ):
                issues.append("invalid_paragraph_provenance")
                break
            if positions:
                last_position = positions[-1]
        if "\n\n".join(
            paragraph.text for paragraph in rendered.paragraphs
        ) != rendered.body:
            issues.append("paragraph_body_mismatch")
    unknown_entities = set(_ENTITY_TOKEN.findall(text)) - _digest_entity_tokens(
        digest
    )
    if unknown_entities:
        issues.append(
            "unknown_entity_tokens:" + ",".join(sorted(unknown_entities)[:8])
        )
    return tuple(dict.fromkeys(issues))


def _authorized_quote(quote: str, digest: NarrativeDigest) -> bool:
    spoken_words = _spoken_normal_form(quote)
    if spoken_words and any(
        spoken_words in _spoken_normal_form(utterance)
        for utterance in digest.utterances
    ):
        return True
    is_short_term = (
        len(quote) <= 12
        and not re.search(r"[，。！？；：—…\n]", quote)
    )
    if not is_short_term:
        return False
    factual_text = "\n".join(
        entry.summary
        + "\n"
        + json.dumps(dict(entry.facts), ensure_ascii=False, sort_keys=True)
        for entry in digest.entries
    )
    return quote in factual_text


def _spoken_normal_form(value: str) -> str:
    return value.translate(
        str.maketrans("", "", "“”「」『』‘’\"'")
    ).rstrip("。！？；")


def validate_literary_quality(
    rendered: RenderedNarrative,
    value: NarrativeRenderRequest | NarrativeDigest,
) -> bool:
    """Reject known event-log prose patterns before publication."""

    return not literary_quality_issues(rendered, value)


def literary_quality_issues(
    rendered: RenderedNarrative,
    value: NarrativeRenderRequest | NarrativeDigest,
) -> tuple[str, ...]:
    """Return stable structural quality diagnostics for renderer observability."""

    request = _render_request(value)
    text = f"{rendered.title}\n{rendered.body}"
    skill = get_literary_skill(request.style.skill_id)
    voice = get_world_voice(request.style.voice_id)
    if not skill.skill_id or not voice.voice_id:
        return ("unknown_skill_or_voice",)
    banned = {
        *request.style.forbidden_phrases,
        *voice.banned_constructions,
    }
    if any(item and item in text for item in banned):
        return ("forbidden_phrase",)
    if any(
        entry.kind == "gate_opened" and entry.summary in text
        for entry in request.digest.entries
    ):
        return ("gate_prompt_in_prose",)
    gate_source_ids = {
        entry.source_event_id
        for entry in request.digest.entries
        if entry.kind == "gate_opened"
    }
    if any(
        gate_source_ids.intersection(paragraph.source_event_ids)
        for paragraph in rendered.paragraphs
    ):
        return ("gate_source_in_prose",)
    if len(set(paragraph.text for paragraph in rendered.paragraphs)) != len(
        rendered.paragraphs
    ):
        return ("duplicate_paragraph",)
    narrative_entries = tuple(
        entry
        for entry in request.digest.entries
        if entry.kind not in StructuredLiteraryRenderer._ROUTINE_KINDS
    )
    if (
        len(narrative_entries) >= 4
        and len(rendered.paragraphs) >= len(narrative_entries) - 1
        and not _is_committed_exchange(rendered, request)
    ):
        return ("event_log_paragraph_shape",)
    mechanical_openings = voice.quality_gate("mechanical_openings")
    if (
        mechanical_openings
        and
        sum(
            paragraph.text.startswith(mechanical_openings)
            for paragraph in rendered.paragraphs
        )
        >= 2
    ):
        return ("repeated_mechanical_opening",)
    return ()


def _is_committed_exchange(
    rendered: RenderedNarrative, request: NarrativeRenderRequest
) -> bool:
    """Dialogue taken from committed lines is not an event-log paraphrase."""

    utterances = tuple(
        entry.dialogue
        for entry in request.digest.entries
        if entry.dialogue
    )
    if len(utterances) < 2 or not rendered.paragraphs:
        return False
    quoted = sum(
        1
        for paragraph in rendered.paragraphs
        if any(utterance in paragraph.text for utterance in utterances)
    )
    return quoted >= len(rendered.paragraphs) - 1


def _render_request(
    value: NarrativeRenderRequest | NarrativeDigest,
) -> NarrativeRenderRequest:
    if isinstance(value, NarrativeRenderRequest):
        return value
    return NarrativeRenderRequest(
        value,
        build_narrative_plan(value),
        NarrativeStyleProfile(),
    )


def _digest_entity_tokens(digest: NarrativeDigest) -> set[str]:
    values: list[str] = [
        *digest.source_event_ids,
        *digest.character_ids,
        *digest.location_ids,
        *digest.target_ids,
        *digest.utterances,
        *digest.unresolved_points,
    ]
    for entry in digest.entries:
        values.extend(
            (entry.kind, entry.summary, entry.actor_id, entry.goal or "")
        )
        for change in entry.changes:
            values.extend(
                (
                    change.category,
                    change.subject_id,
                    change.target_id or "",
                    change.value,
                )
            )
        values.extend(
            str(item)
            for key, item in entry.facts.items()
            if key
            in {
                "location_description",
                "destination_description",
                "resource_name",
                "resource_properties",
                "dialogue_act",
                "dialogue_topic",
                "relationship_reason",
            }
        )
    return {
        token
        for value in values
        for token in _ENTITY_TOKEN.findall(value)
    }
