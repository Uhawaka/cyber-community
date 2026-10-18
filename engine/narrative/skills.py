"""Load host-owned literary skill resources and registered world voices."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from engine.contracts import CharacterVoiceRegisterSpec, LiterarySkill, WorldVoice


@dataclass(frozen=True)
class LoadedLiterarySkill:
    skill_id: str
    version: int
    stage: str
    input_schema: str
    output_schema: str
    instruction: str


@dataclass(frozen=True)
class RegisteredWorldVoice:
    voice_id: str
    instruction: str
    pov_rules: tuple[str, ...]
    first_attentions: tuple[str, ...]
    voice_exemplars: tuple[str, ...]
    banned_constructions: tuple[str, ...]
    title_pattern: str
    lexicon: tuple[tuple[str, str], ...] = ()
    quality_gates: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def model_instruction(
        self,
        focus_character_id: str | None = None,
        character_registers: tuple[CharacterVoiceRegisterSpec, ...] = (),
    ) -> str:
        ordered_registers = tuple(
            sorted(
                character_registers,
                key=lambda item: (
                    item.character_id != focus_character_id,
                    item.character_id,
                ),
            )
        )
        register_instruction = (
            "没有额外角色声音档案。"
            if not ordered_registers
            else "角色声音档案="
            + "；".join(
                (
                    f"{item.character_id}"
                    + (
                        "（焦点）"
                        if item.character_id == focus_character_id
                        else ""
                    )
                    + f"[先注意={'、'.join(item.first_attentions)}；"
                    f"词汇={item.diction}；句法={item.syntax}；"
                    f"保留={'、'.join(item.withheld) or '无'}]"
                )
                for item in ordered_registers
            )
            + "。"
        )
        return (
            f"{self.instruction}"
            f"视角规则={'；'.join(self.pov_rules)}。"
            f"优先注意={'、'.join(self.first_attentions)}。"
            f"{register_instruction}"
            "声音范例只用于学习句长、节奏和观察顺序，禁止复制其中事实："
            f"{'；'.join(self.voice_exemplars)}。"
            f"禁用句式={'；'.join(self.banned_constructions)}。"
        )

    def title(self, focus: str, location: str | None) -> str:
        return self.title_pattern.format(
            focus=focus,
            location=location or "",
        ).rstrip("：·在")

    def surface_term(self, key: str, default: str) -> str:
        return dict(self.lexicon).get(key, default)

    def quality_gate(self, key: str) -> tuple[str, ...]:
        return dict(self.quality_gates).get(key, ())


def _load_skills() -> MappingProxyType[str, LiterarySkill]:
    root = Path(__file__).with_name("skill_library")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "literary-skill-library/v1":
        raise RuntimeError("unsupported literary skill library")
    loaded: dict[str, LiterarySkill] = {}
    for item in manifest.get("skills", ()):
        if not isinstance(item, dict):
            raise RuntimeError("invalid literary skill manifest entry")
        skill_id = str(item.get("id", ""))
        resource = root / str(item.get("resource", ""))
        if (
            not skill_id
            or skill_id in loaded
            or not resource.is_file()
            or resource.parent.parent != root
        ):
            raise RuntimeError(f"invalid literary skill resource: {skill_id}")
        instruction = resource.read_text(encoding="utf-8").strip()
        if not instruction:
            raise RuntimeError(f"empty literary skill resource: {skill_id}")
        loaded[skill_id] = LoadedLiterarySkill(
            skill_id=skill_id,
            version=int(item["version"]),
            stage=str(item["stage"]),
            input_schema=str(item["input_schema"]),
            output_schema=str(item["output_schema"]),
            instruction=instruction,
        )
    loaded["scene-craft-v2"] = LoadedLiterarySkill(
        skill_id="scene-craft-v2",
        version=2,
        stage="editorial_pipeline",
        input_schema="narrative-material/v1",
        output_schema="sourced-draft/v1",
        instruction="\n\n".join(
            loaded[skill_id].instruction
            for skill_id in (
                "developmental-editor-v1",
                "scene-writer-v1",
                "line-editor-v1",
                "fact-continuity-editor-v1",
            )
        ),
    )
    return MappingProxyType(loaded)


_SKILLS = _load_skills()


def _load_voices() -> Mapping[str, WorldVoice]:
    root = Path(__file__).with_name("voice_library")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "world-voice-library/v1":
        raise RuntimeError("unsupported world voice library")
    loaded: dict[str, WorldVoice] = {}
    for item in manifest.get("voices", ()):
        if not isinstance(item, dict):
            raise RuntimeError("invalid world voice manifest entry")
        voice_id = str(item.get("id") or "")
        resource = root / str(item.get("resource") or "")
        if (
            not voice_id
            or voice_id in loaded
            or not resource.is_file()
            or resource.parent != root
        ):
            raise RuntimeError(f"invalid world voice resource: {voice_id}")
        value = json.loads(resource.read_text(encoding="utf-8"))
        if value.get("id") != voice_id:
            raise RuntimeError(f"world voice id mismatch: {voice_id}")
        quality_gates = value.get("quality_gates", {})
        loaded[voice_id] = RegisteredWorldVoice(
            voice_id=voice_id,
            instruction=str(value["instruction"]),
            pov_rules=_strings(value, "pov_rules", voice_id),
            first_attentions=_strings(value, "first_attentions", voice_id),
            voice_exemplars=_strings(value, "voice_exemplars", voice_id),
            banned_constructions=_strings(
                value, "banned_constructions", voice_id
            ),
            title_pattern=str(value["title_pattern"]),
            lexicon=tuple(
                sorted(
                    (str(key), str(term))
                    for key, term in value.get("lexicon", {}).items()
                )
            ),
            quality_gates=tuple(
                sorted(
                    (
                        str(key),
                        tuple(str(entry) for entry in entries),
                    )
                    for key, entries in quality_gates.items()
                    if isinstance(entries, list)
                )
            ),
        )
    return MappingProxyType(loaded)


def _strings(
    value: dict[str, object], field: str, voice_id: str
) -> tuple[str, ...]:
    raw = value.get(field)
    if not isinstance(raw, list) or any(
        not isinstance(item, str) or not item for item in raw
    ):
        raise RuntimeError(f"invalid {field} in world voice: {voice_id}")
    return tuple(raw)


_VOICES = _load_voices()


def get_literary_skill(skill_id: str) -> LiterarySkill:
    try:
        return _SKILLS[skill_id]
    except KeyError as exc:
        raise ValueError(f"unknown literary skill: {skill_id}") from exc


def literary_skill_ids() -> tuple[str, ...]:
    return tuple(_SKILLS)


def get_world_voice(voice_id: str) -> WorldVoice:
    try:
        return _VOICES[voice_id]
    except KeyError as exc:
        raise ValueError(f"unknown world voice: {voice_id}") from exc


def world_voice_ids() -> tuple[str, ...]:
    return tuple(_VOICES)
