"""Chapter boundaries chosen from committed material, not episode quotas."""

from __future__ import annotations

from collections.abc import Sequence
import json

from engine.contracts import TextModel
from engine.narrative.curation import (
    CurationPolicy,
    CuratedEpisodeWindow,
    is_reader_visible_source,
)
from engine.narrative.source import SourceEventView, adapt_source_event


class ContentChapterDivider:
    """Let the writing module hold or close a chapter from the open material."""

    def __init__(
        self,
        model: TextModel | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    def close_at(self, sources: Sequence[SourceEventView]) -> int | None:
        """Return how many leading sources form one chapter, or hold."""

        if not sources:
            return None
        horizon = _departure_index(sources)
        if self.model is None:
            if horizon is not None:
                return horizon
            return divide_by_content(sources)
        visible = sources[:horizon] if horizon is not None else sources
        if not _worth_asking(visible):
            return None
        preview = (
            sources
            if horizon is None
            else sources[: min(len(sources), horizon + 4)]
        )
        departure_id = (
            sources[horizon].source_event_id if horizon is not None else None
        )
        chosen = self._ask(preview, departure_id=departure_id)
        if isinstance(chosen, int):
            end = chosen if horizon is None else min(chosen, horizon)
            return _through_chain(sources, end)
        if chosen == "hold":
            return None if horizon is None else horizon
        if horizon is not None:
            return horizon
        return divide_by_content(sources)

    def _ask(
        self,
        sources: Sequence[SourceEventView],
        *,
        departure_id: str | None = None,
    ) -> int | str | None:
        lines = [
            {
                "source_event_id": source.source_event_id,
                "kind": source.kind,
                "actor": source.actor_ids[0] if source.actor_ids else "",
                "location_id": source.location_id,
                "chain_id": source.facts.get("chain_id") or "",
                "summary": source.summary[:180],
                "utterance": source.utterance or "",
            }
            for source in sources
        ]
        departure = ""
        if departure_id is not None:
            departure = (
                f"从 {departure_id} 起是下一处的开头，只能当作分界，不能收进这一章。"
                "同一处里的交谈、比对、决定和离开算同一次经历，结束点选在这条分界之前的最后一条，"
                "不要停在中途某一句问答上。这一处已经离开，就不能 hold。"
            )
        prompt = (
            "你是写作模块，只负责把已经发生的材料分成章节。不要改写，不要补充事实。"
            "按阅读来切：一章读完，读者应能感到一次经历已经落地。"
            "同一 chain_id 必须整段留下。不要把后面新开的一处经历也吞进来。"
            "还停在同一处、经历尚未落地时才 hold。场景收束标记本身不是切章理由。"
            + departure
            + '只返回 JSON：{"decision":"hold"} 或 '
            '{"decision":"close","end_source_event_id":"列表中的ID"}。材料：'
            + json.dumps(lines, ensure_ascii=False)
        )
        try:
            value = _decode_json_object(
                self.model.complete(
                    prompt, timeout_seconds=self.timeout_seconds
                )
            )
        except Exception:
            return None
        if not isinstance(value, dict):
            return None
        if value.get("decision") == "hold":
            return "hold"
        if value.get("decision") != "close":
            return None
        source_id = value.get("end_source_event_id")
        if not isinstance(source_id, str):
            return None
        for index, source in enumerate(sources):
            if source.source_event_id == source_id:
                return index + 1
        return None


def _decode_json_object(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        final_fence = text.rfind("```")
        if first_newline >= 0 and final_fence > first_newline:
            text = text[first_newline + 1 : final_fence].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value


def divide_reader_windows(
    events: Sequence[object],
    *,
    cursor: int,
    audience_id: str,
    omniscient: bool,
    policy: CurationPolicy,
    minimum_events: int,
    divider: ContentChapterDivider,
) -> tuple[CuratedEpisodeWindow, ...]:
    """Offer at most one chapter from the open tail."""

    visible = _visible_tail(
        events,
        cursor=cursor,
        audience_id=audience_id,
        omniscient=omniscient,
        policy=policy,
    )
    if len(visible) < minimum_events:
        return ()
    sources = tuple(source for _, source in visible)
    closing = divider.close_at(sources)
    if closing is None or closing <= 0:
        return ()
    closing = min(closing, len(visible))
    selected = visible[:closing]
    return (
        CuratedEpisodeWindow(
            tuple(source for _, source in selected),
            selected[-1][0] + 1,
        ),
    )


def divide_by_content(sources: Sequence[SourceEventView]) -> int | None:
    """Close at the first finished chain that already contains a reader arc."""

    for end in range(len(sources)):
        if not _chain_closed(sources, end):
            continue
        if _reader_arc(sources[: end + 1]):
            return end + 1
    return None


def _visible_tail(
    events: Sequence[object],
    *,
    cursor: int,
    audience_id: str,
    omniscient: bool,
    policy: CurationPolicy,
) -> list[tuple[int, SourceEventView]]:
    visible: list[tuple[int, SourceEventView]] = []
    repeated: dict[tuple[str, str, str | None], int] = {}
    for absolute_index in range(cursor, len(events)):
        source = adapt_source_event(events[absolute_index])
        if not omniscient and audience_id not in source.observer_ids:
            continue
        if not is_reader_visible_source(source):
            continue
        key = (
            source.kind,
            source.actor_ids[0] if source.actor_ids else "system",
            source.target_id or source.location_id,
        )
        if (
            source.kind in {"moved", "observed", "waited", "rested"}
            and repeated.get(key, 0) >= policy.max_repeated_action
        ):
            continue
        visible.append((absolute_index, source))
        repeated[key] = repeated.get(key, 0) + 1
    return visible


def _departure_index(sources: Sequence[SourceEventView]) -> int | None:
    """Index where a later place begins after the opening place has landed."""

    opening = next(
        (_place_id(source.location_id) for source in sources if source.location_id),
        None,
    )
    if opening is None:
        return None
    for index, source in enumerate(sources):
        if (
            not source.location_id
            or _place_id(source.location_id) == opening
            or source.kind
            not in {
                "scene_instantiated",
                "moved",
                "scene_entered",
                "turn_resolved",
                "incident_occurred",
                "user_intervention",
            }
        ):
            continue
        if index < 1 or not _chain_closed(sources, index - 1):
            continue
        if not _reader_arc(sources[:index]):
            continue
        return index
    return None


def _worth_asking(sources: Sequence[SourceEventView]) -> bool:
    speakers = {
        actor
        for source in sources
        if source.utterance
        for actor in source.actor_ids
    }
    return len(speakers) >= 2 or _reader_arc(sources)


def _reader_arc(sources: Sequence[SourceEventView]) -> bool:
    speakers = {
        actor
        for source in sources
        if source.utterance
        for actor in source.actor_ids
    }
    turns = [
        source
        for source in sources
        if source.kind in {"turn_resolved", "dialogue"}
    ]
    if not any(_is_consequence(source) for source in sources):
        return False
    return len(speakers) >= 2 or len(turns) >= 2


def _place_id(location_id: str | None) -> str | None:
    """Sub-scenes of one location stay in the same chapter."""

    if not location_id:
        return None
    text = location_id[len("scene:") :] if location_id.startswith("scene:") else location_id
    return text.split(":", 1)[0]


def _is_consequence(source: SourceEventView) -> bool:
    decision = str(source.facts.get("decision") or "").strip()
    return (
        source.kind == "moved"
        or decision not in {"", "None", "null"}
        or bool(source.facts.get("scene_outcome"))
        or source.facts.get("dramatic_progress") in {"decision", "resolved"}
    )


def _chain_closed(sources: Sequence[SourceEventView], end: int) -> bool:
    chain_id = str(sources[end].facts.get("chain_id") or "")
    if not chain_id:
        return True
    return all(
        str(source.facts.get("chain_id") or "") != chain_id
        for source in sources[end + 1 :]
    )


def _through_chain(sources: Sequence[SourceEventView], exclusive_end: int) -> int:
    end = max(1, min(exclusive_end, len(sources)))
    chain_id = str(sources[end - 1].facts.get("chain_id") or "")
    if not chain_id:
        return end
    while (
        end < len(sources)
        and str(sources[end].facts.get("chain_id") or "") == chain_id
    ):
        end += 1
    return end
