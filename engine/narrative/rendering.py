"""Narrative rendering and fact-grounding validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.contracts import NarrativeRenderer, WorldVoice
from engine.narrative.curation import is_reader_visible_source
from engine.narrative.digest import NarrativeDigest, NarrativeDigestEntry
from engine.narrative.planning import (
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    build_narrative_plan,
)
from engine.narrative.skills import get_literary_skill, get_world_voice
from engine.narrative.source import NarrativeChange


@dataclass(frozen=True)
class RenderedParagraph:
    source_event_ids: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class RenderedNarrative:
    title: str
    body: str
    non_factual_atmosphere: str | None = None
    paragraphs: tuple[RenderedParagraph, ...] = ()


@dataclass(frozen=True)
class RenderDiagnostic:
    renderer: str
    status: str
    elapsed_ms: int
    detail: str = ""


class AudienceMode(str, Enum):
    AVATAR = "avatar"
    OMNISCIENT = "omniscient"


class DeterministicNarrativeRenderer:
    """Render exact summaries and dialogue without narrative continuation."""

    def render(
        self, value: NarrativeRenderRequest | NarrativeDigest
    ) -> RenderedNarrative:
        request = _render_request(value)
        digest = request.digest
        lines: list[str] = []
        paragraphs: list[RenderedParagraph] = []
        for entry in digest.entries:
            entry_lines = [f"[{entry.source_event_id}] {entry.summary}"]
            if entry.dialogue is not None:
                entry_lines.append(f"{entry.actor_id}：“{entry.dialogue}”")
            text = "\n".join(entry_lines)
            lines.append(text)
            paragraphs.append(
                RenderedParagraph((entry.source_event_id,), text)
            )
        return RenderedNarrative(
            title=(
                f"事件 {digest.source_event_ids[0]}"
                f"—{digest.source_event_ids[-1]}"
            ),
            body="\n\n".join(lines),
            paragraphs=tuple(paragraphs),
        )


class StructuredLiteraryRenderer:
    """Build scene-shaped fallback prose from committed facts."""

    _ROUTINE_KINDS = frozenset(
        {
            "action_rejected",
            "action_replanned",
            "environment_decayed",
            "run_created",
            "scene_evolved",
            "incident_rested",
            "gate_waited",
            "scheme_created",
            "scheme_advanced",
            "scheme_completed",
            "scheme_invalidated",
            "memory_consolidated",
            "soul_evolution_proposed",
            "soul_evolution_approved",
            "soul_evolution_rejected",
            "phase_snapshot",
        }
    )

    def __init__(self, labels: dict[str, str] | None = None) -> None:
        self._labels = dict(labels or {})

    def render(
        self, value: NarrativeRenderRequest | NarrativeDigest
    ) -> RenderedNarrative:
        request = _render_request(value)
        digest = request.digest
        get_literary_skill(request.style.skill_id)
        voice = get_world_voice(request.style.voice_id)
        entries = self._select_entries(
            tuple(
            entry
            for entry in digest.entries
            if entry.kind not in self._ROUTINE_KINDS
            and is_reader_visible_source(entry)
            )
        )
        if not entries:
            return RenderedNarrative(title="片段", body="")

        paragraphs: list[str] = []
        sourced_paragraphs: list[RenderedParagraph] = []
        by_source_id = {entry.source_event_id: entry for entry in entries}
        for beat in request.plan.beats:
            beat_entries = tuple(
                by_source_id[source_id]
                for source_id in beat.source_event_ids
                if source_id in by_source_id
                and by_source_id[source_id].kind != "gate_opened"
            )
            if not beat_entries:
                continue
            paragraph = self._render_beat(
                beat_entries,
                voice=voice,
                function=beat.function,
            )
            if not paragraph:
                continue
            paragraphs.append(paragraph)
            sourced_paragraphs.append(
                RenderedParagraph(
                    tuple(entry.source_event_id for entry in beat_entries),
                    paragraph,
                )
            )
        narrative_count = sum(
            entry.kind not in self._ROUTINE_KINDS
            for entry in digest.entries
        )
        if narrative_count >= 4:
            sourced_paragraphs = list(
                _compress_paragraphs(
                    tuple(sourced_paragraphs),
                    max(1, narrative_count - 2),
                )
            )
        sourced_paragraphs = _drop_duplicate_paragraphs(sourced_paragraphs)
        paragraphs = [item.text for item in sourced_paragraphs]
        title = voice.title(
            self._label(request.plan.focus_character_id or "片段"),
            (
                self._label(request.plan.focus_location_id)
                if request.plan.focus_location_id
                else None
            ),
        )
        return RenderedNarrative(
            title=title or self._focus(entries),
            body="\n\n".join(paragraphs),
            paragraphs=tuple(sourced_paragraphs),
        )

    def _focus(self, entries: tuple[NarrativeDigestEntry, ...]) -> str:
        actors = [
            actor_id
            for entry in entries
            for actor_id in entry.actor_ids
            if actor_id != "system"
        ]
        if not actors:
            return "片段"
        counts = {
            actor_id: actors.count(actor_id)
            for actor_id in dict.fromkeys(actors)
        }
        focus = self._label(max(counts, key=counts.__getitem__))
        locations = [entry.location_id for entry in entries if entry.location_id]
        return (
            f"{focus}在{self._label(max(set(locations), key=locations.count))}"
            if locations
            else focus
        )

    def _render_beat(
        self,
        entries: tuple[NarrativeDigestEntry, ...],
        *,
        voice: WorldVoice,
        function: str,
    ) -> str:
        sentences = [
            self._fact(
                entry,
                voice=voice,
                previous=entries[index - 1] if index else None,
            )
            for index, entry in enumerate(entries)
        ]
        sentences = [sentence for sentence in sentences if sentence]
        if function == "opening":
            description = next(
                (
                    entry.facts.get("location_description")
                    or entry.facts.get("destination_description")
                    for entry in entries
                    if entry.facts.get("location_description")
                    or entry.facts.get("destination_description")
                ),
                None,
            )
            if description:
                sentences.insert(0, str(description))
        if not sentences and all(
            entry.kind == "gate_opened" for entry in entries
        ):
            return ""
        if not sentences:
            sentences = [entries[-1].summary]
        return "".join(_sentence(sentence) for sentence in sentences)

    def _fact(
        self,
        entry: NarrativeDigestEntry,
        *,
        voice: WorldVoice,
        previous: NarrativeDigestEntry | None = None,
    ) -> str:
        actor = self._label(entry.actor_id)
        if entry.kind == "scene_instantiated":
            return entry.facts.get("scene_description") or entry.summary
        if entry.kind == "gathered" and entry.target_id:
            verb = voice.surface_term("gathered", "取得了")
            return f"{actor}{verb}{self._label(entry.target_id)}"
        if entry.kind == "inspected":
            finding = entry.facts.get("finding")
            if finding:
                return f"{actor}查验后看清：{finding}"
        if entry.kind == "turn_resolved":
            if entry.dialogue:
                return f"{entry.summary}{actor}说：“{entry.dialogue}”"
            return entry.summary
        if entry.kind == "moved":
            move = next(
                (change for change in entry.changes if change.category == "move"),
                None,
            )
            if move is not None and "→" in move.value:
                origin, destination = move.value.split("→", 1)
                return (
                    f"{actor}{voice.surface_term('movement_origin', '从')}"
                    f"{self._label(origin)}"
                    f"{voice.surface_term('movement_destination', '来到')}"
                    f"{self._label(destination)}"
                )
        if entry.kind == "observed" and entry.location_id:
            verb = voice.surface_term("observed", "查看了")
            return f"{actor}{verb}{self._label(entry.location_id)}"
        if entry.kind == "dialogue" and entry.target_id:
            if entry.dialogue is None:
                return f"{actor}对{self._label(entry.target_id)}说了几句"
            act = entry.facts.get("dialogue_act")
            target = self._label(entry.target_id)
            is_reply = (
                previous is not None
                and previous.kind == "dialogue"
                and previous.actor_id == entry.target_id
                and previous.target_id == entry.actor_id
            )
            lead = (
                f"{actor}答道"
                if is_reply
                else {
                "inquire": f"{actor}问{target}",
                "disclose": f"{actor}道",
                "propose": f"{actor}向{target}提议",
                "challenge": f"{actor}反问{target}",
                "reassure": f"{actor}宽慰{target}",
                }.get(str(act), f"{actor}对{target}说")
            )
            return (
                f"{lead}：“{entry.dialogue}”"
            )
        if entry.kind == "rested":
            location = (
                f"在{self._label(entry.location_id)}"
                if entry.location_id
                else ""
            )
            return f"{actor}{location}歇下"
        if entry.kind == "waited":
            return f"{actor}暂且等候"
        if entry.kind == "gate_opened":
            return ""
        if entry.kind == "user_intervention":
            return entry.facts.get("observation") or entry.summary
        if entry.kind == "soul_evolution_approved":
            return f"{actor}的长期倾向出现了有历史依据的变化"
        if entry.kind == "soul_evolution_rejected":
            return f"{actor}仍保持原有的长期倾向"
        return entry.summary

    def _label(self, value: str) -> str:
        return self._labels.get(value, value)

    @staticmethod
    def _select_entries(
        entries: tuple[NarrativeDigestEntry, ...],
    ) -> tuple[NarrativeDigestEntry, ...]:
        """Compress repeated routine actions while retaining turning points."""

        selected: list[NarrativeDigestEntry] = []
        substantive_count = sum(
            entry.kind not in {"rested", "waited"} for entry in entries
        )
        high_signal_count = sum(
            entry.kind
            in {
                "dialogue",
                "gathered",
                "inspected",
                "incident_occurred",
                "gate_opened",
                "user_intervention",
                "turn_resolved",
            }
            for entry in entries
        )
        seen: set[tuple[str, ...]] = set()
        for entry in entries:
            if (
                substantive_count >= 2
                and entry.kind in {"rested", "waited"}
            ):
                continue
            if (
                high_signal_count >= 3
                and entry.kind in {"moved", "observed"}
            ):
                continue
            if entry.kind in {
                "incident_occurred",
                "gate_opened",
                "user_intervention",
            }:
                selected.append(entry)
                continue
            if entry.kind == "dialogue" and entry.dialogue is not None:
                # Mirrored stock exchanges are one dramatic fact, not two
                # paragraphs of repeated wording.
                key = (entry.kind, entry.dialogue)
            elif entry.kind in {"moved", "observed"}:
                # Movement and looking are connective tissue. One occurrence
                # per actor and kind is enough unless a later high-signal
                # event makes the detail relevant in another Episode.
                key = (entry.kind, entry.actor_id)
            else:
                key = (
                    entry.kind,
                    entry.actor_id,
                    entry.target_id or "",
                    entry.dialogue or "",
                    entry.summary,
                )
            if key in seen:
                continue
            seen.add(key)
            selected.append(entry)
        return tuple(selected)


def _sentence(text: str) -> str:
    return (
        text
        if text.endswith(("。", "！", "？", ".", "!", "?", "。”", "！”", "？”"))
        else f"{text}。"
    )


def _compress_paragraphs(
    paragraphs: tuple[RenderedParagraph, ...], limit: int
) -> tuple[RenderedParagraph, ...]:
    """Merge adjacent fallback beats so prose cannot mirror event cardinality."""

    result = list(paragraphs)
    while len(result) > limit:
        index = min(
            range(len(result) - 1),
            key=lambda item: len(result[item].text) + len(result[item + 1].text),
        )
        left, right = result[index : index + 2]
        result[index : index + 2] = [
            RenderedParagraph(
                tuple(dict.fromkeys((*left.source_event_ids, *right.source_event_ids))),
                f"{left.text}{right.text}",
            )
        ]
    return tuple(result)


def _drop_duplicate_paragraphs(
    paragraphs: list[RenderedParagraph],
) -> list[RenderedParagraph]:
    seen: set[str] = set()
    unique: list[RenderedParagraph] = []
    for paragraph in paragraphs:
        if paragraph.text in seen:
            continue
        seen.add(paragraph.text)
        unique.append(paragraph)
    return unique


def compress_event_log_shape(
    rendered: RenderedNarrative,
    request: NarrativeRenderRequest,
) -> RenderedNarrative:
    """Merge adjacent sourced paragraphs without changing prose or facts."""

    narrative_count = sum(
        entry.kind not in StructuredLiteraryRenderer._ROUTINE_KINDS
        for entry in request.digest.entries
    )
    if narrative_count < 4:
        return rendered
    paragraphs = _compress_paragraphs(
        rendered.paragraphs, max(1, narrative_count - 2)
    )
    return RenderedNarrative(
        title=rendered.title,
        body="\n\n".join(item.text for item in paragraphs),
        non_factual_atmosphere=rendered.non_factual_atmosphere,
        paragraphs=paragraphs,
    )


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

