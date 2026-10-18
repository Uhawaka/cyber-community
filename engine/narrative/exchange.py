"""Assemble a chapter from committed speech instead of drafting a new one."""

from __future__ import annotations

from engine.narrative.planning import NarrativeRenderRequest
from engine.narrative.rendering import (
    RenderedNarrative,
    RenderedParagraph,
    StructuredLiteraryRenderer,
)


def assemble_committed_exchange(
    request: NarrativeRenderRequest,
) -> RenderedNarrative | None:
    """Return reader text when a chapter already contains a real exchange."""

    entries = tuple(
        entry
        for entry in request.digest.entries
        if entry.kind not in StructuredLiteraryRenderer._ROUTINE_KINDS
        and entry.kind not in {"gate_opened", "scene_instantiated"}
        and _reader_line(entry)
    )
    spoken = tuple(entry for entry in entries if entry.utterance)
    speakers = {entry.actor_id for entry in spoken}
    if len(spoken) < 2 or len(speakers) < 2:
        return None
    paragraphs: list[RenderedParagraph] = []
    group: list[object] = []
    chain_id = None
    for entry in entries:
        current = str(entry.facts.get("chain_id") or "")
        if group and current != chain_id:
            _append_group(paragraphs, group)
            group = []
        chain_id = current
        group.append(entry)
    _append_group(paragraphs, group)
    if not paragraphs:
        return None
    body = "\n\n".join(item.text for item in paragraphs)
    title = _title(spoken[0].utterance or spoken[0].summary)
    return RenderedNarrative(title, body, paragraphs=tuple(paragraphs))


def _append_group(paragraphs: list[RenderedParagraph], group: list[object]) -> None:
    lines = [_reader_line(entry) for entry in group]
    text = "".join(_sentence(line) for line in lines if line)
    if not text or any(item.text == text for item in paragraphs):
        return
    paragraphs.append(
        RenderedParagraph(
            tuple(entry.source_event_id for entry in group),
            text,
        )
    )


def _reader_line(entry: object) -> str:
    utterance = str(getattr(entry, "utterance", None) or "")
    summary = str(getattr(entry, "summary", "") or "").strip()
    if utterance and utterance not in summary:
        if "回应了" in summary:
            name = summary.split("回应了", 1)[0].strip("。 ")
            if name:
                return f"{name}说：“{utterance}”"
        return utterance
    return summary


def _sentence(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    if text[-1] not in "。！？…”\"」』":
        text += "。"
    return text


def _title(value: str) -> str:
    text = value.strip()
    for mark in "。！？":
        if mark in text:
            text = text.split(mark, 1)[0].strip()
            break
    if len(text) <= 18:
        return text or "现场"
    shortened = text[:18]
    for mark in ("，", "、", "；"):
        if mark in shortened:
            head = shortened.rsplit(mark, 1)[0].strip()
            if head:
                return head
    return shortened.strip() or "现场"
