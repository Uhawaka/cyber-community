"""一局里能开成哪些幕：每类转折一个生产者。

每个生产者只读已提交事实，返回 (本幕的简报, 段落, 地点) 或 None。写不成就不写——
没有回答的问句、没拿到料的交涉、已经说过一遍的秘密，都不算幕。

这里只管"有没有一幕"，怎么写、怎么核对在 community_prose 里。
"""

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


def _reveal_scene(run, facts):
    """Somebody says out loud what they had kept to themselves.

    A line counts as a reveal when it shares a long enough stretch with one of
    the speaker's own unspoken secrets. Facts alone decide; nothing is inferred.
    """
    told = set()
    for spoken in facts:
        if spoken.kind != "dialogue" or not spoken.utterance:
            continue
        secret = _revealed_secret(run, spoken.actor_id, spoken.utterance)
        if secret is None or secret in told:
            continue
        told.add(secret)
        speaker = _name(run, spoken.actor_id)
        return _quoted_exchange(
            run, facts, spoken,
            focus=f"{speaker}说出没公开的事", goal=f"{speaker}把瞒着的事说出口",
            conflict=f"{_name(run, run.events[spoken.sequence].data.get('listener_id'))}怎么接",
            stakes=f"{speaker}从此收不回",
            anchor=secret, touch_reply=True,
        )
    return None


def _leak_scene(run, facts):
    """Someone passes on a secret that belongs to somebody else."""
    owners = {
        character.id: tuple(
            str(item.get("summary") or "") for item in character.memory_seed
            if str(item.get("kind")) == "secret"
        )
        for character in run.compiled.world.characters
    }
    for spoken in facts:
        if spoken.kind != "dialogue" or not spoken.utterance:
            continue
        for owner, texts in owners.items():
            if owner == spoken.actor_id:
                continue
            leaked = next((text for text in texts if shared_phrase(text, spoken.utterance) >= REVEAL_OVERLAP), "")
            if not leaked:
                continue
            return _quoted_exchange(
                run, facts, spoken,
                focus=f"{_name(run, spoken.actor_id)}把{_name(run, owner)}的事说了出去",
                goal=f"{_name(run, spoken.actor_id)}说出别人的私事",
                conflict=f"{_name(run, owner)}并不在场",
                stakes="这话从此不在两个人之间",
                anchor=leaked, touch_reply=True,
            )
    return None


def _question_scene(run, facts):
    """A question that actually gets answered is a turn, not chatter."""
    for spoken in facts:
        if spoken.kind != "dialogue" or not spoken.utterance:
            continue
        event = run.events[spoken.sequence]
        if str(event.data.get("speech_act") or "") != "clarify":
            continue
        listener = event.data.get("listener_id")
        answered = any(
            fact.kind == "dialogue" and fact.sequence > spoken.sequence
            and fact.actor_id == listener and fact.target_id == spoken.actor_id
            and fact.tick - spoken.tick <= 3 and fact.utterance
            for fact in facts
        )
        if not answered:
            continue
        asker, asked = _name(run, spoken.actor_id), _name(run, listener)
        return _quoted_exchange(
            run, facts, spoken,
            focus=f"{asker}问{asked}", goal=f"{asker}把话说到底",
            conflict=f"{asked}怎么答", stakes=f"{asker}的疑问不再是私下的",
        )
    return None


def _bearing_quote(utterance, anchor=""):
    """A verbatim sentence. A secret keeps the clause that overlaps it; otherwise the first sentence."""
    sentences = _sentences(utterance)
    if anchor:
        matched = [span for span in _anchored_spans(sentences) if shared_phrase(anchor, span) >= REVEAL_OVERLAP]
        if matched:
            return min(matched, key=len)
    asked = [sentence for sentence in sentences if "？" in sentence or "?" in sentence]
    return asked[0] if asked else sentences[0]


def _aligned_quote(utterance, other):
    """The sentence that meets the other speech, skipping a short echo tag."""
    sentences = _sentences(utterance)
    scored = [(shared_phrase(sentence, other), len(sentence), sentence) for sentence in sentences]
    best_overlap = max(overlap for overlap, _length, _sentence in scored)
    floor = 2 if best_overlap >= 2 else 0
    substantial = [item for item in scored if item[0] >= floor and item[1] >= 16]
    pool = substantial or scored
    sentence = max(pool, key=lambda item: (item[0], item[1]))[2]
    if "：" in sentence:
        tail = sentence.rsplit("：", 1)[-1].strip()
        if len(tail) >= 12 and shared_phrase(tail, other) >= 4:
            return tail
    return sentence


def _sentences(utterance):
    text = str(utterance or "").strip()
    found = [item.strip() for item in re.findall(r"[^。！？]*[。！？]", text) if item.strip()]
    return found or ([text] if text else [""])


def _anchored_spans(sentences):
    spans = []
    for sentence in sentences:
        spans.append(sentence)
        for separator in ("：", "——"):
            if separator in sentence:
                tail = sentence.rsplit(separator, 1)[-1].strip()
                if len(tail) >= REVEAL_OVERLAP:
                    spans.append(tail)
    return spans


def _reply_touches(anchor, reply):
    if reply.speech_act in {"refuse", "promise", "request"}:
        return True
    return bool(anchor) and shared_phrase(anchor, reply.utterance) >= REVEAL_OVERLAP


def _quoted_exchange(run, facts, spoken, *, focus, goal, conflict, stakes, anchor="", touch_reply=False):
    event = run.events[spoken.sequence]
    listener = event.data.get("listener_id")
    place = _place_name(run, event.data.get("location_id") or "")
    reply = next((
        fact for fact in facts
        if fact.kind == "dialogue" and fact.sequence > spoken.sequence
        and fact.actor_id == listener and fact.target_id == spoken.actor_id
        and fact.tick - spoken.tick <= 3
    ), None)
    if reply is not None and touch_reply and not _reply_touches(anchor, reply):
        reply = None
    speaker = _name(run, spoken.actor_id)
    opener = f"{place}里，" if place else ""
    spoken_quote = (
        _bearing_quote(spoken.utterance, anchor) if anchor
        else _aligned_quote(spoken.utterance, reply.utterance if reply is not None else "")
    )
    paragraphs = [SourcedParagraph(
        (_ref(spoken.sequence),),
        f"{opener}{speaker}对{_name(run, listener)}说：「{spoken_quote}」",
    )]
    if reply is not None:
        reply_quote = (
            _bearing_quote(reply.utterance, anchor) if anchor
            else _aligned_quote(reply.utterance, spoken.utterance)
        )
        paragraphs.append(SourcedParagraph(
            (_ref(reply.sequence),),
            f"{_name(run, listener)}答：「{reply_quote}」",
        ))
    brief = EditorialBrief(
        focus, goal, conflict, stakes, _ref(spoken.sequence),
        tuple(source for paragraph in paragraphs for source in paragraph.source_event_ids),
        (_ref(spoken.sequence),), paragraphs[-1].source_event_ids[-1], "consequence",
    )
    return _Scene(brief, tuple(paragraphs), place)


def _revealed_secret(run, actor_id, utterance):
    for character in run.compiled.world.characters:
        if character.id != actor_id:
            continue
        for item in character.memory_seed:
            if str(item.get("kind")) != "secret":
                continue
            text = str(item.get("summary") or "")
            if shared_phrase(text, utterance) >= REVEAL_OVERLAP:
                return text
    return None


def _latest_mark(run, facts, entity_id, after):
    facts = tuple(facts)
    marks = [
        mark for mark in _condition_marks(run, {fact.sequence for fact in facts})
        if mark.entity_id == entity_id and mark.sequence > after
    ]
    return marks[-1] if marks else None

def _bargain_scene(run, facts):
    """A spoken ask and the answer it gets, or nothing at all.

    An ask counts only when the listener answers it: a later reply back to the
    asker, a refusal, or an act on the same device. Silence stays unwritten.
    """
    for ask in facts:
        if ask.kind != "dialogue" or ask.speech_act not in ("request", "promise"):
            continue
        event = run.events[ask.sequence]
        listener = event.data.get("listener_id")
        if not isinstance(listener, str) or listener not in run.state.characters:
            continue
        if listener == ask.actor_id:
            continue
        place = _place_name(run, event.data.get("location_id") or "")
        device = _resource_name(run, ask.topic_ref) if ask.topic_ref else ""
        reply = next((
            fact for fact in facts
            if fact.kind == "dialogue" and fact.sequence > ask.sequence
            and fact.actor_id == listener and fact.target_id == ask.actor_id
            and fact.tick - ask.tick <= 3 and fact.speech_act
        ), None)
        if reply is not None:
            refused = reply.speech_act == "refuse"
            closing = None if refused is False or not device else _latest_mark(
                run, facts, ask.topic_ref, after=reply.sequence,
            )
            paragraphs = [
                _ask_paragraph(run, ask, device, place, reply.utterance),
                SourcedParagraph(
                    (_ref(reply.sequence),),
                    f"{_name(run, listener)}没有应下：「{_aligned_quote(reply.utterance, ask.utterance)}」" if refused
                    else f"{_name(run, listener)}答：「{_aligned_quote(reply.utterance, ask.utterance)}」",
                ),
            ]
            if refused and closing is not None:
                paragraphs.append(SourcedParagraph(
                    (_ref(closing.sequence),), f"{device}仍停在{_chinese(closing.value)}。",
                ))
            focus = device or f"{_name(run, ask.actor_id)}向{_name(run, listener)}开口"
            brief = EditorialBrief(
                focus, f"{_name(run, ask.actor_id)}请{_name(run, listener)}接",
                f"{_name(run, listener)}没有应下" if refused else f"{_name(run, listener)}怎么答",
                f"{device}要不要人等" if device else f"{_name(run, listener)}要不要接",
                _ref(reply.sequence),
                tuple(source for paragraph in paragraphs for source in paragraph.source_event_ids),
                (_ref(reply.sequence),), paragraphs[-1].source_event_ids[-1], "consequence",
            )
            return _Scene(brief, tuple(paragraphs), place)
        if not device:
            continue
        handled = next((
            fact for fact in facts
            if fact.sequence > ask.sequence and fact.target_id == ask.topic_ref
            and fact.actor_id == listener and fact.kind in ("gathered", "activity_finished")
        ), None)
        if handled is None:
            continue
        paragraphs = [
            _ask_paragraph(run, ask, device, place),
            _answer_paragraph(run, handled, device, listener),
        ]
        value = _chinese(_repair_value(run, handled)) if handled.action_verb == "repair" else None
        brief = EditorialBrief(
            device, f"{_name(run, ask.actor_id)}请{_name(run, listener)}接{device}",
            f"{_name(run, listener)}接不接", f"{device}要等着有人动手",
            _ref(handled.sequence),
            tuple(source for paragraph in paragraphs for source in paragraph.source_event_ids),
            (), _ref(handled.sequence), "consequence", value,
        )
        return _Scene(brief, tuple(paragraphs), place)
    return None

def _ask_paragraph(run, ask, device, place, other=""):
    opened = f"{place}里，" if place else ""
    speaker = _name(run, ask.actor_id)
    listener = _name(run, run.events[ask.sequence].data["listener_id"])
    quote = _aligned_quote(ask.utterance, other) if other else _bearing_quote(ask.utterance)
    if device:
        return SourcedParagraph((_ref(ask.sequence),), f"{opened}{speaker}向{listener}请求{device}：「{quote}」")
    return SourcedParagraph((_ref(ask.sequence),), f"{opened}{speaker}对{listener}说：「{quote}」")

def _answer_paragraph(run, handled, device, listener):
    name = _name(run, listener)
    if handled.action_verb == "repair":
        return SourcedParagraph((_ref(handled.sequence),), f"{name}把{device}修到{_chinese(_repair_value(run, handled))}。")
    return SourcedParagraph((_ref(handled.sequence),), f"{name}取了{device}。")

def _commitment_scene(run, facts):
    repairs = [
        fact for fact in facts
        if fact.kind == "activity_finished" and fact.action_verb == "repair" and fact.status == "completed"
    ]
    for fact in facts:
        if fact.kind != "commitment_updated" or fact.status != "fulfilled":
            continue
        record = run.events[fact.sequence].data.get("commitment") or {}
        promisor = record.get("promisor_id")
        beneficiary = record.get("beneficiary_id")
        target = record.get("target_id") or fact.target_id
        if not isinstance(promisor, str) or not isinstance(beneficiary, str) or not target:
            continue
        proposed = _commitment_fact(facts, fact.object_id, "proposed")
        accepted = _commitment_fact(facts, fact.object_id, "accepted")
        if proposed is None or accepted is None or not proposed.sequence < accepted.sequence < fact.sequence:
            continue
        repair = next((
            item for item in repairs
            if item.actor_id == promisor and item.target_id == target
            and accepted.sequence < item.sequence <= fact.sequence
        ), None)
        if repair is None:
            continue
        device = _resource_name(run, target)
        paragraphs = (
            SourcedParagraph(
                (_ref(proposed.sequence), _ref(accepted.sequence)),
                f"{_name(run, beneficiary)}应下{_name(run, promisor)}维修{device}的提议。",
            ),
            SourcedParagraph(
                (_ref(repair.sequence),),
                f"{_name(run, promisor)}把{device}修到{_chinese(_repair_value(run, repair))}。",
            ),
        )
        brief = EditorialBrief(
            device, f"{_name(run, promisor)}维修{device}",
            f"{_name(run, beneficiary)}是否应下",
            f"{device}是否被修好",
            _ref(accepted.sequence),
            (_ref(proposed.sequence), _ref(accepted.sequence), _ref(repair.sequence)),
            (), _ref(repair.sequence), "consequence", _chinese(_repair_value(run, repair)),
        )
        return _Scene(brief, paragraphs, _place_name(run, _resource_location(run, target)))
    return None

def _commitment_fact(facts, object_id, status):
    return next((
        item for item in facts
        if item.kind == "commitment_updated" and item.object_id == object_id and item.status == status
    ), None)
