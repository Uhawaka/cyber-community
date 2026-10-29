"""Read-only naming and event vocabulary shared by scene writing and fact checking."""

from __future__ import annotations

import re
from dataclasses import dataclass


_DIGITS = dict(zip("零一二三四五六七八九", range(10), strict=True))

_GLUE = (
    "下一小时", "随后说出", "随后", "落到", "修到", "说出", "停在", "仍停在",
    "应下", "没有应下", "没有", "请求", "拒绝了", "拒绝", "取了", "请", "接", "向", "仍",
    "要不要", "怎么答", "要等", "人等", "问过", "问", "答", "说", "开口", "维修", "提议", "里", "把", "它", "对", "的",
)

@dataclass(frozen=True)
class _Mark:
    sequence: int
    entity_id: str
    value: int

def _condition_marks(run, visible):
    marks = []
    for event in run.events:
        if event.sequence not in visible:
            continue
        for entity_id, value in _patch_values(event):
            marks.append(_Mark(event.sequence, entity_id, value))
    return marks

def _repair_value(run, fact):
    event = run.events[fact.sequence]
    for _entity, value in _patch_values(event):
        return value
    match = re.search(r"condition\s+(\d+)", str(event.data.get("summary") or ""))
    if match is None:
        raise ValueError("repair source has no committed condition")
    return int(match.group(1))

def _patch_values(event):
    for patch in event.delta.entity_patches:
        component = patch.component
        data = component.data if component is not None else None
        value = data.get("condition") if isinstance(data, dict) or hasattr(data, "get") else None
        if not isinstance(value, bool) and isinstance(value, int):
            yield patch.entity_id, value

def _event_numbers(event):
    numbers = {value for _entity, value in _patch_values(event)}
    for field in ("utterance", "summary"):
        numbers.update(int(item) for item in re.findall(r"\d+", str(event.data.get(field) or "")))
    return numbers

def _event_names(run, event):
    names = set()
    for actor_id in (event.actor_id, event.data.get("listener_id")):
        if isinstance(actor_id, str):
            names.add(_name(run, actor_id))
    if isinstance(event.data.get("location_id"), str):
        names.add(_place_name(run, event.data["location_id"]))
    commitment = event.data.get("commitment") or {}
    for key in ("promisor_id", "beneficiary_id"):
        if isinstance(commitment.get(key), str):
            names.add(_name(run, commitment[key]))
    entities = {entity_id for entity_id, _value in _patch_values(event)}
    utterance = str(event.data.get("utterance") or "").strip()
    match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*\d+", utterance)
    if match is not None:
        entities.add(match.group(1))
    if event.target_entity_id:
        entities.add(event.target_entity_id)
    if isinstance(commitment.get("target_id"), str):
        entities.add(commitment["target_id"])
    topic = event.data.get("topic_ref")
    if isinstance(topic, str) and topic:
        entities.add(topic)
        names.add(_name(run, topic))
    for entity_id in entities:
        names.add(_resource_name(run, entity_id))
        names.add(_place_name(run, _resource_location(run, entity_id)))
    return {name for name in names if name}

def _residual(text, names):
    cleaned = re.sub(r"「[^」]*」", "", text)
    for number in sorted(set(_chinese_numbers(text)), key=lambda item: len(_chinese(item)), reverse=True):
        cleaned = cleaned.replace(_chinese(number), "")
    fragments = sorted(
        {
            name[start:end]
            for name in names if name
            for start in range(len(name))
            for end in range(start + 2, len(name) + 1)
        },
        key=len, reverse=True,
    )
    for fragment in fragments:
        cleaned = cleaned.replace(fragment, "")
    for glue in sorted(_GLUE, key=len, reverse=True):
        cleaned = cleaned.replace(glue, "")
    return re.sub(r"[，。、：\s]", "", cleaned)

def _name(run, actor_id):
    for character in run.compiled.world.characters:
        if character.id == actor_id:
            return character.name
    return ""

def _resource_name(run, resource_id):
    for resource in run.compiled.world.resources:
        if resource.id == resource_id:
            return resource.name
    return ""

def _resource_location(run, resource_id):
    for resource in run.compiled.world.resources:
        if resource.id == resource_id:
            return resource.location_id
    return ""

def _place_name(run, location_id):
    for location in run.compiled.world.locations:
        if location.id == location_id:
            return location.name
    return ""

def _chinese(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError("prose numbers must be committed conditions from 0 to 100")
    digits = "零一二三四五六七八九"
    if value < 10:
        return digits[value]
    if value == 100:
        return "一百"
    tens, ones = divmod(value, 10)
    head = "十" if tens == 1 else digits[tens] + "十"
    return head if ones == 0 else head + digits[ones]

def _chinese_numbers(text):
    numbers = []
    index = 0
    while index < len(text):
        if text.startswith("一百", index):
            numbers.append(100)
            index += 2
            continue
        match = re.match(r"([二三四五六七八九])?十([一二三四五六七八九])?", text[index:])
        if match and "十" in match.group(0):
            tens = _DIGITS[match.group(1)] if match.group(1) else 1
            ones = _DIGITS[match.group(2)] if match.group(2) else 0
            numbers.append(tens * 10 + ones)
            index += match.end()
            continue
        index += 1
    return numbers

def _ref(sequence):
    return f"event:{int(sequence)}"
