"""Turn one public turn into a sourced scene. A missing turn stays unwritten."""

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


def _spoken(text):
    """只比说话的部分：地点与说话人的固定说法不算重复。"""
    index = text.find("「")
    return text[index:] if index >= 0 else text


def _develop_scenes(run, facts, limit=SCENES_PER_READING):
    """Later scenes may only use facts that come after the previous scene ended."""
    scenes, horizon, seen, used = [], -1, set(), set()
    for _ in range(limit * 3):
        if len(scenes) >= limit:
            break
        found = _develop(run, [fact for fact in facts if fact.sequence > horizon], skip=used)
        if found is None:
            break
        kind, scene = found
        used.add(kind)
        horizon = max(int(source.split(":", 1)[1])
                      for paragraph in scene.paragraphs for source in paragraph.source_event_ids)
        if scene.brief.focus in seen:
            continue  # 同一件事说第二遍不成幕，但后面的材料还要接着看
        seen.add(scene.brief.focus)
        if any(shared_phrase(_spoken(paragraph.text), _spoken(earlier.text)) >= REVEAL_OVERLAP * 2
               for paragraph in scene.paragraphs
               for earlier_scene in scenes for earlier in earlier_scene.paragraphs):
            continue  # 与已写的幕大段重合：同一段话换个说法再说一遍，不成新的一幕
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

from engine.narrative.community_scenes import (
    _bargain_scene, _commitment_scene, _leak_scene, _question_scene, _reveal_scene,
)
from engine.narrative.community_repair_scene import _stale_number_scene


def _develop(run, facts, skip=()):
    """One kind of turn once. A second confession is not a second scene."""
    for kind, produce in (
        ("reveal", _reveal_scene),
        ("leak", _leak_scene),
        ("stale", _stale_number_scene),
        ("bargain", _bargain_scene),
        ("question", _question_scene),
        ("commitment", _commitment_scene),
    ):
        if kind in skip:
            continue
        scene = produce(run, facts)
        if scene is not None:
            return kind, scene
    return None
