"""Line edit and fact continuity: reject summary voice, invented nouns, unnamed numbers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine.contracts.literary import SourcedDraft, SourcedParagraph
from engine.narrative.community_names import (
    _chinese_numbers,
    _event_names,
    _event_numbers,
    _ref,
    _residual,
)


_LEDGER = ("Tick", "event:", "condition", "process_settled", "I can")

_SUMMARY_VOICE = ("由此可知", "这意味着", "然后", "最后", "首先", "因此", "所以", "得以推进", "尚待查明")

def _line_edit(run, draft, location):
    banned = _banned_phrases(run)
    paragraphs = []
    for paragraph in draft.paragraphs:
        text = paragraph.text
        narration = re.sub(r"「[^」]*」", "", text)
        for phrase in (*banned, *_SUMMARY_VOICE):
            if phrase and phrase in narration:
                raise ValueError(f"line edit rejected a banned construction: {phrase}")
        for phrase in _LEDGER:
            if phrase and phrase in text:
                raise ValueError(f"line edit rejected a banned construction: {phrase}")
        if not re.search(r"[。！？]", text):
            raise ValueError("line edit rejected a paragraph without a sentence")
        paragraphs.append(SourcedParagraph(paragraph.source_event_ids, text))
    title = _title(run, draft.title, location)
    for phrase in banned:
        if phrase and phrase in title:
            raise ValueError(f"line edit rejected a banned title construction: {phrase}")
    return SourcedDraft(title, tuple(paragraphs))

def _check_facts(run, brief, draft):
    previous = -1
    seen = []
    for paragraph in draft.paragraphs:
        if not paragraph.source_event_ids or not paragraph.text.strip():
            raise ValueError("fact check rejected an empty paragraph")
        sequences = []
        allowed_numbers = set()
        paragraph_names = set()
        for source in paragraph.source_event_ids:
            if not source.startswith("event:"):
                raise ValueError("fact check rejected an untyped source")
            sequence = int(source.split(":", 1)[1])
            if sequence < 0 or sequence >= len(run.events) or sequence <= previous:
                raise ValueError("fact check rejected a source that is missing or out of order")
            previous = sequence
            sequences.append(sequence)
            event = run.events[sequence]
            paragraph_names.update(_event_names(run, event))
            allowed_numbers.update(_event_numbers(event))
        for number in _chinese_numbers(paragraph.text):
            if number not in allowed_numbers:
                raise ValueError("fact check rejected a number the sources do not contain")
        if "下一小时" in paragraph.text:
            ticks = [
                run.events[sequence].tick for sequence in sequences
                if run.events[sequence].event_type.value == "dialogue"
            ]
            if len(ticks) < 2 or ticks[-1] - ticks[0] != 1:
                raise ValueError("fact check rejected an hour the sources do not span")
        for quote in re.findall(r"[「“\"]([^」”\"]+)[」”\"]", paragraph.text):
            utterances = [str(run.events[sequence].data.get("utterance") or "") for sequence in sequences]
            if not any(quote == utterance or (len(quote) >= 4 and quote in utterance) for utterance in utterances):
                raise ValueError("fact check rejected a quotation that is not the committed utterance")
        seen.extend(sequences)
        leftover = _residual(paragraph.text, paragraph_names)
        if leftover:
            raise ValueError(f"fact check rejected an unauthorized word: {leftover}")
    if tuple(_ref(sequence) for sequence in seen) != brief.selected_source_ids:
        raise ValueError("fact check rejected a draft that left its selected sources")
    prose = "\n".join(item.text for item in draft.paragraphs)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", prose):
        raise ValueError(f"fact check rejected an untranslated identifier: {token}")
    if brief.resolved_outcome and brief.resolved_outcome not in draft.paragraphs[-1].text:
        raise ValueError("fact check rejected an ending that drops the resolved outcome")

def _banned_phrases(run):
    style = dict(run.compiled.experience.editorial.style)
    voice = _voice(style.get("voice_id") or run.compiled.experience.editorial.voice_id)
    phrases = style.get("forbidden_phrases") or ()
    return tuple(dict.fromkeys((*voice.get("banned_constructions", ()), *phrases)))

def _voice(voice_id):
    path = Path(__file__).with_name("voice_library") / f"{voice_id}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def _title(run, focus, location):
    style = dict(run.compiled.experience.editorial.style)
    voice = _voice(style.get("voice_id") or run.compiled.experience.editorial.voice_id)
    pattern = str(voice.get("title_pattern") or "{focus}")
    if not location:
        return focus
    return pattern.format(focus=focus, location=location)
