"""修好一件东西之后，账面数字和眼前的实物对不上——这一型单独的幕。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from engine.contracts.community_text import REVEAL_OVERLAP, shared_phrase
from engine.contracts.literary import EditorialBrief, SourcedDraft, SourcedParagraph
from engine.narrative.community_factcheck import _check_facts, _line_edit
from engine.narrative.community_names import (
    _condition_marks,
    _chinese,
    _event_names,
    _event_numbers,
    _name,
    _patch_values,
    _place_name,
    _ref,
    _repair_value,
    _residual,
    _resource_location,
    _resource_name,
)


@dataclass(frozen=True)
class _Speech:
    sequence: int
    tick: int
    actor_id: str
    listener_id: str
    entity_id: str
    value: int

@dataclass(frozen=True)
class _Scene:
    brief: EditorialBrief
    paragraphs: tuple[SourcedParagraph, ...]
    location: str

SCENES_PER_READING = 2


def compose_reading(run, facts):
    """Develop, write, line-edit, and fact-check up to two scenes in order.

    ``facts`` is the observer projection of this run, passed in by the caller so
    this layer never reaches into the runtime to read history itself. A scene that
    fails the edit or the fact check is dropped, not rewritten: if the first scene
    fails there is no reading, if the second fails the reading keeps the first.
    """
    if run.compiled.community is None:
        raise ValueError("community prose requires a versioned community package")
    scenes = _develop_scenes(run, facts)
    for count in range(len(scenes), 0, -1):
        draft = _compose(run, scenes[:count])
        if draft is not None:
            return draft
    return None


def _develop_scenes(run, facts, limit=SCENES_PER_READING):
    """Later scenes may only use facts that come after the previous scene ended."""
    scenes, horizon, seen = [], -1, set()
    for _ in range(limit * 3):
        if len(scenes) >= limit:
            break
        scene = _develop(run, [fact for fact in facts if fact.sequence > horizon])
        if scene is None:
            break
        horizon = max(int(source.split(":", 1)[1])
                      for paragraph in scene.paragraphs for source in paragraph.source_event_ids)
        if scene.brief.focus in seen:
            continue  # 同一件事说第二遍不成幕，但后面的材料还要接着看
        seen.add(scene.brief.focus)
        scenes.append(scene)
    return scenes


def _compose(run, scenes):
    first = scenes[0]
    paragraphs = tuple(paragraph for scene in scenes for paragraph in scene.paragraphs)
    selected = tuple(source for paragraph in paragraphs for source in paragraph.source_event_ids)
    try:
        draft = _line_edit(run, SourcedDraft(first.brief.focus, paragraphs), first.location)
        _check_facts(run, replace(first.brief, selected_source_ids=selected, resolved_outcome=""), draft)
    except ValueError:
        return None
    return draft


def _stale_number_scene(run, facts):
    visible = {fact.sequence for fact in facts}
    marks = _condition_marks(run, visible)
    repairs = {
        fact.sequence: fact for fact in facts
        if fact.kind == "activity_finished" and fact.action_verb == "repair" and fact.status == "completed"
    }
    speeches = tuple(_device_speeches(run, visible))
    best = None
    for speech in speeches:
        earlier = [mark for mark in marks if mark.entity_id == speech.entity_id and mark.sequence < speech.sequence]
        if not earlier or earlier[-1].value == speech.value:
            continue
        origin = next((mark for mark in reversed(earlier) if mark.value == speech.value), None)
        if origin is None:
            continue
        replaced = next((
            fact for fact in facts
            if fact.sequence in repairs and fact.target_id == speech.entity_id
            and origin.sequence < fact.sequence < speech.sequence
        ), None)
        later = next((
            fact for fact in facts
            if fact.sequence in repairs and fact.target_id == speech.entity_id and fact.sequence > speech.sequence
        ), None)
        if replaced is None and later is None:
            continue
        opening_end = replaced.sequence if replaced is not None else origin.sequence
        companion = next((
            item for item in reversed(speeches)
            if opening_end < item.sequence < speech.sequence and item.actor_id == speech.actor_id
            and item.listener_id == speech.listener_id and item.entity_id == speech.entity_id
            and item.value != speech.value
        ), None)
        before = None
        if later is not None:
            restored = _repair_value(run, later)
            between = [
                mark for mark in marks
                if mark.entity_id == speech.entity_id and speech.sequence < mark.sequence < later.sequence
                and mark.value != restored
            ]
            before = between[-1] if between else None
        groups = [[origin.sequence] if replaced is None else [origin.sequence, replaced.sequence]]
        groups.append([speech.sequence] if companion is None else [companion.sequence, speech.sequence])
        if later is not None:
            groups.append([later.sequence] if before is None else [before.sequence, later.sequence])
        selected = tuple(sequence for group in groups for sequence in group)
        if len(selected) > 8 or len(selected) != len(set(selected)) or selected != tuple(sorted(selected)):
            continue
        gap = abs(earlier[-1].value - speech.value)
        score = gap + (40 if replaced is not None else 0) + (20 if later is not None else 0)
        if best is None or score > best[0]:
            best = (score, speech, origin, replaced, later, companion, before, selected)
    if best is None:
        return None
    _, speech, origin, replaced, later, companion, before, selected = best
    device = _resource_name(run, speech.entity_id)
    place = _place_name(run, _resource_location(run, speech.entity_id))
    paragraphs = (
        _opening_paragraph(run, origin, replaced, device, place),
        _speech_paragraph(run, companion, speech),
    )
    if later is not None:
        paragraphs += (_closing_paragraph(run, before, later, device),)
    brief = EditorialBrief(
        device, f"{_name(run, speech.actor_id)}报出{device}的数字",
        f"报出的{_chinese(speech.value)}已不是当时的结算",
        f"{device}此后仍被维修" if later is not None else f"{device}的数字已经换过",
        _ref(speech.sequence), tuple(_ref(sequence) for sequence in selected), (),
        _ref(selected[-1]), "consequence",
        resolved_outcome=_chinese(_repair_value(run, later)) if later is not None else None,
    )
    return _Scene(brief, paragraphs, place)

def _opening_paragraph(run, origin, replaced, device, place):
    sources = [origin.sequence]
    text = f"{place}里，{device}落到{_chinese(origin.value)}。"
    if replaced is not None:
        sources.append(replaced.sequence)
        text += f"{_name(run, replaced.actor_id)}把它修到{_chinese(_repair_value(run, replaced))}。"
    return SourcedParagraph(tuple(_ref(sequence) for sequence in sources), text)

def _speech_paragraph(run, companion, speech):
    speaker = _name(run, speech.actor_id)
    listener = _name(run, speech.listener_id)
    if companion is None:
        return SourcedParagraph(
            (_ref(speech.sequence),),
            f"{_speech_place(run, speech)}里，{speaker}对{listener}说出{_chinese(speech.value)}。",
        )
    turn = "下一小时，说出" if speech.tick - companion.tick == 1 else "随后说出"
    place = _speech_place(run, companion)
    opened = f"{place}里，" if place and place == _speech_place(run, speech) else ""
    return SourcedParagraph(
        (_ref(companion.sequence), _ref(speech.sequence)),
        f"{opened}{speaker}对{listener}说出{_chinese(companion.value)}。{turn}{_chinese(speech.value)}。",
    )

def _speech_place(run, speech):
    return _place_name(run, run.events[speech.sequence].data.get("location_id") or "")

def _closing_paragraph(run, before, repair, device):
    restored = _chinese(_repair_value(run, repair))
    actor = _name(run, repair.actor_id)
    if before is None:
        return SourcedParagraph((_ref(repair.sequence),), f"{actor}把{device}修到{restored}。")
    return SourcedParagraph(
        (_ref(before.sequence), _ref(repair.sequence)),
        f"{device[-2:]}停在{_chinese(before.value)}，{actor}把它修到{restored}。",
    )


def _device_speeches(run, visible):
    for event in run.events:
        if event.sequence not in visible or event.event_type.value != "dialogue":
            continue
        utterance = str(event.data.get("utterance") or "").strip()
        match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*(\d+)", utterance)
        listener = event.data.get("listener_id")
        if match is None or not isinstance(listener, str) or listener not in run.state.characters:
            continue
        yield _Speech(
            event.sequence, event.tick, event.actor_id, listener, match.group(1), int(match.group(2)),
        )
