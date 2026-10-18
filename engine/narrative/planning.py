"""Typed narrative plans derived exclusively from committed digest sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from engine.contracts import (
    DEFAULT_EDITORIAL_PIPELINE,
    CharacterVoiceRegisterSpec,
    EditorialExperienceContract,
)
from engine.narrative.curation import is_reader_visible_source
from engine.narrative.digest import NarrativeDigest, NarrativeDigestEntry


@dataclass(frozen=True)
class NarrativeStyleProfile:
    skill_id: str = "scene-craft-v2"
    editorial_pipeline: tuple[str, ...] = DEFAULT_EDITORIAL_PIPELINE
    voice_id: str = "clear-observer-v1"
    language: str = "zh-CN"
    point_of_view: str = "omniscient"
    narrative_distance: str = "medium"
    register: str = "literary"
    rhythm: str = "balanced"
    dialogue_density: str = "balanced"
    imagery_domains: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()
    scene_shape: str = "turn-centered"
    exposition: str = "implicit"
    revision_level: str = "developmental-and-line"
    character_voice_registers: tuple[CharacterVoiceRegisterSpec, ...] = ()
    narrative_functions: tuple[str, ...] = ()
    quality_dimensions: tuple[str, ...] = ()

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object] | None
    ) -> "NarrativeStyleProfile":
        selected = dict(value or {})
        return cls(
            skill_id=str(selected.get("skill_id", "scene-craft-v2")),
            editorial_pipeline=tuple(
                str(item)
                for item in selected.get(
                    "editorial_pipeline", DEFAULT_EDITORIAL_PIPELINE
                )
            ),
            voice_id=str(selected.get("voice_id", "clear-observer-v1")),
            language=str(selected.get("language", "zh-CN")),
            point_of_view=str(selected.get("point_of_view", "omniscient")),
            narrative_distance=str(
                selected.get("narrative_distance", "medium")
            ),
            register=str(selected.get("register", "literary")),
            rhythm=str(selected.get("rhythm", "balanced")),
            dialogue_density=str(
                selected.get("dialogue_density", "balanced")
            ),
            imagery_domains=tuple(
                str(item) for item in selected.get("imagery_domains", ())
            ),
            forbidden_phrases=tuple(
                str(item) for item in selected.get("forbidden_phrases", ())
            ),
            scene_shape=str(selected.get("scene_shape", "turn-centered")),
            exposition=str(selected.get("exposition", "implicit")),
            revision_level=str(
                selected.get("revision_level", "developmental-and-line")
            ),
            character_voice_registers=tuple(
                item
                for item in selected.get("character_voice_registers", ())
                if isinstance(item, CharacterVoiceRegisterSpec)
            ),
            narrative_functions=tuple(
                str(item)
                for item in selected.get("narrative_functions", ())
            ),
            quality_dimensions=tuple(
                str(item)
                for item in selected.get("quality_dimensions", ())
            ),
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "editorial_pipeline": self.editorial_pipeline,
            "voice_id": self.voice_id,
            "language": self.language,
            "point_of_view": self.point_of_view,
            "narrative_distance": self.narrative_distance,
            "register": self.register,
            "rhythm": self.rhythm,
            "dialogue_density": self.dialogue_density,
            "imagery_domains": self.imagery_domains,
            "forbidden_phrases": self.forbidden_phrases,
            "scene_shape": self.scene_shape,
            "exposition": self.exposition,
            "revision_level": self.revision_level,
            "character_voice_registers": self.character_voice_registers,
            "narrative_functions": self.narrative_functions,
            "quality_dimensions": self.quality_dimensions,
        }


@dataclass(frozen=True)
class NarrativeBeat:
    source_event_ids: tuple[str, ...]
    relation: str
    function: str
    summary: str
    actor_id: str
    location_id: str | None


@dataclass(frozen=True)
class NarrativePlan:
    source_event_ids: tuple[str, ...]
    focus_character_id: str | None
    focus_location_id: str | None
    theme: str
    beats: tuple[NarrativeBeat, ...]
    turning_point_source_id: str
    scene_goal: str | None = None
    opposition_source_ids: tuple[str, ...] = ()
    outcome_source_ids: tuple[str, ...] = ()
    unresolved_hook: str | None = None


@dataclass(frozen=True)
class NarrativeRenderRequest:
    digest: NarrativeDigest
    plan: NarrativePlan
    style: NarrativeStyleProfile


def style_profile_from_contract(
    contract: EditorialExperienceContract,
) -> NarrativeStyleProfile:
    """Build the sole narrative style projection from a compiled contract."""

    value = dict(contract.style)
    value["editorial_pipeline"] = contract.pipeline
    value["character_voice_registers"] = contract.character_voice_registers
    value["narrative_functions"] = contract.narrative_functions
    value["quality_dimensions"] = contract.quality_dimensions
    return NarrativeStyleProfile.from_mapping(value)


def build_narrative_plan(digest: NarrativeDigest) -> NarrativePlan:
    """Create an auditable dramatic order without inventing facts."""

    entries = tuple(
        entry
        for entry in digest.entries
        if is_reader_visible_source(entry)
    )
    if not entries:
        entries = digest.entries
    actors = [
        actor_id
        for entry in entries
        for actor_id in entry.actor_ids
        if actor_id != "system"
    ]
    focus_character = _most_common(actors)
    focus_entries = tuple(
        entry
        for entry in entries
        if focus_character is None or focus_character in entry.actor_ids
    )
    locations = [
        entry.location_id
        for entry in focus_entries or entries
        if entry.location_id is not None
    ]
    turning_point = _turning_point(entries)
    turning_index = next(
        index
        for index, entry in enumerate(entries)
        if entry.source_event_id == turning_point
    )
    beats = _build_scene_beats(entries, turning_index)
    unresolved = next(
        (
            point
            for entry in reversed(entries)
            for point in entry.unresolved_points
        ),
        None,
    )
    return NarrativePlan(
        source_event_ids=digest.source_event_ids,
        focus_character_id=focus_character,
        focus_location_id=_most_common(locations),
        theme=_theme(entries),
        beats=tuple(beats),
        turning_point_source_id=turning_point,
        scene_goal=_scene_goal(entries),
        opposition_source_ids=tuple(
            entry.source_event_id
            for entry in entries
            if entry.kind
            in {
                "action_rejected",
                "incident_occurred",
                "gate_opened",
                "scheme_invalidated",
            }
            or (
                entry.kind == "turn_resolved"
                and entry.facts.get("status") in {"partial", "rejected"}
            )
            or any(change.is_cost for change in entry.changes)
        ),
        outcome_source_ids=tuple(
            entry.source_event_id
            for entry in entries[turning_index:]
            if entry.changes
            or entry.dialogue is not None
            or entry.unresolved_points
            or entry.kind == "inspected"
            or entry.kind == "turn_resolved"
        ),
        unresolved_hook=unresolved,
    )


def _build_scene_beats(
    entries: tuple[NarrativeDigestEntry, ...], turning_index: int
) -> tuple[NarrativeBeat, ...]:
    """Group event facts into dramatic units instead of one beat per event."""

    turning_entry = entries[turning_index]
    signal_kinds = {
        "dialogue",
        "gathered",
        "inspected",
        "incident_occurred",
        "moved",
        "scene_instantiated",
        "scene_entered",
        "turn_resolved",
        "user_intervention",
        "gate_opened",
    }
    selected = [
        entry
        for entry in entries
        if entry.kind in signal_kinds
        and not (
            entry.kind == "dialogue"
            and entry.facts.get("dialogue_act")
            in {"disclose", "propose"}
            and not entry.facts.get("conversation_progress_ids")
        )
    ]
    if turning_entry not in selected:
        selected.append(turning_entry)
        selected.sort(key=entries.index)
    if len(selected) < 2:
        selected = list(entries)
    entries = tuple(selected)
    turning_index = entries.index(turning_entry)

    functions = [
        _dramatic_function(entry, index, turning_index)
        for index, entry in enumerate(entries)
    ]
    groups: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, len(entries) + 1):
        boundary = (
            index == len(entries)
            or functions[index] != functions[start]
            or index - start >= 4
        )
        if boundary:
            groups.append((start, index, functions[start]))
            start = index

    beats: list[NarrativeBeat] = []
    seen: set[str] = set()
    previous: NarrativeDigestEntry | None = None
    for start, end, function in groups:
        group = entries[start:end]
        relation = "opening"
        first = group[0]
        if previous is not None:
            if set(first.causal_source_ids).intersection(seen):
                relation = "cause"
            elif first.world_time == previous.world_time:
                relation = "simultaneous"
            else:
                relation = "sequence"
        beats.append(
            NarrativeBeat(
                source_event_ids=tuple(item.source_event_id for item in group),
                relation=relation,
                function=function,
                summary="；".join(item.summary for item in group),
                actor_id=_most_common(
                    [
                        actor_id
                        for item in group
                        for actor_id in item.actor_ids
                        if actor_id != "system"
                    ]
                )
                or "system",
                location_id=_most_common(
                    [
                        item.location_id
                        for item in group
                        if item.location_id is not None
                    ]
                ),
            )
        )
        seen.update(item.source_event_id for item in group)
        previous = group[-1]
    return tuple(beats)


def _dramatic_function(
    entry: NarrativeDigestEntry,
    index: int,
    turning_index: int,
) -> str:
    if index == turning_index:
        return "turn"
    if index > turning_index:
        return "aftermath"
    if index == 0 or entry.kind in {"scene_instantiated", "scene_entered"}:
        return "opening"
    if (
        entry.kind in {"incident_occurred", "gate_opened"}
        or entry.facts.get("status") == "partial"
        or any(change.is_cost for change in entry.changes)
    ):
        return "pressure"
    return "development"


def _turning_point(
    entries: tuple[NarrativeDigestEntry, ...],
) -> str:
    """Prefer a committed reversal over a delivery hook or routine change."""

    resolved = next(
        (
            entry
            for entry in reversed(entries)
            if entry.kind == "turn_resolved"
            and entry.facts.get("dramatic_progress") == "resolved"
            and entry.facts.get("scene_outcome")
        ),
        None,
    )
    if resolved is not None:
        return resolved.source_event_id
    priorities = (
        {"user_intervention", "incident_occurred"},
        {"turn_resolved"},
        {"dialogue"},
        {"inspected", "gathered", "gate_opened"},
    )
    for kinds in priorities:
        candidate = next(
            (
                entry
                for entry in reversed(entries)
                if entry.kind in kinds
                and (
                    entry.kind != "dialogue"
                    or entry.facts.get("dialogue_act")
                    in {"disclose", "challenge", "propose"}
                )
            ),
            None,
        )
        if candidate is not None:
            return candidate.source_event_id
    return next(
        (
            entry.source_event_id
            for entry in reversed(entries)
            if entry.changes or entry.unresolved_points
        ),
        entries[-1].source_event_id,
    )


def _scene_goal(
    entries: tuple[NarrativeDigestEntry, ...],
) -> str | None:
    """Prefer an in-world committed intention over scheduler utility labels."""

    proposed = next(
        (
            entry.utterance
            for entry in reversed(entries)
            if entry.utterance
            and entry.facts.get("dialogue_act") == "propose"
        ),
        None,
    )
    if proposed:
        return proposed
    return next((entry.goal for entry in entries if entry.goal), None)


def validate_narrative_plan(
    plan: NarrativePlan, digest: NarrativeDigest
) -> bool:
    """Ensure a plan is only an ordering of the supplied digest."""

    if (
        plan.source_event_ids != digest.source_event_ids
        or plan.turning_point_source_id not in digest.source_event_ids
        or any(
            source_id not in digest.source_event_ids
            for source_id in (
                *plan.opposition_source_ids,
                *plan.outcome_source_ids,
            )
        )
        or (
            plan.scene_goal is not None
            and plan.scene_goal
            not in {
                value
                for entry in digest.entries
                for value in (entry.goal, entry.utterance)
                if value is not None
            }
        )
        or (
            plan.unresolved_hook is not None
            and plan.unresolved_hook not in digest.unresolved_points
        )
    ):
        return False
    positions = {
        source_id: index
        for index, source_id in enumerate(digest.source_event_ids)
    }
    planned: list[str] = []
    for beat in plan.beats:
        if not beat.source_event_ids:
            return False
        if any(source_id not in positions for source_id in beat.source_event_ids):
            return False
        planned.extend(beat.source_event_ids)
    planned_positions = [positions[source_id] for source_id in planned]
    return (
        bool(planned)
        and len(planned) == len(set(planned))
        and planned_positions == sorted(planned_positions)
    )


def _most_common(values: list[str]) -> str | None:
    if not values:
        return None
    order = tuple(dict.fromkeys(values))
    return max(order, key=values.count)


def _theme(entries: tuple[NarrativeDigestEntry, ...]) -> str:
    kinds = {entry.kind for entry in entries}
    if "gate_opened" in kinds:
        return "抉择"
    if "incident_occurred" in kinds:
        return "变故"
    if "turn_resolved" in kinds:
        return "行动与回应"
    if "dialogue" in kinds:
        return "关系"
    if "gathered" in kinds:
        return "匮乏与取得"
    if "moved" in kinds:
        return "行路与相遇"
    return "变化"
