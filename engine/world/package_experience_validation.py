"""Field-level validation helpers for authored experience profiles."""

from __future__ import annotations

from typing import Any

from engine.catalogs import literary_skill_ids, world_voice_ids
from engine.contracts.experience import CharacterVoiceRegisterSpec
from engine.world.package_spec import PackageDiagnostic
from engine.world.package_validation import _reject_unknown_fields


STYLE_FIELDS = {
    "skill_id",
    "voice_id",
    "language",
    "point_of_view",
    "narrative_distance",
    "register",
    "rhythm",
    "dialogue_density",
    "imagery_domains",
    "forbidden_phrases",
    "scene_shape",
    "exposition",
    "revision_level",
}
EPISODE_FIELDS = {
    "max_events",
    "max_world_time_span",
    "min_narrative_events",
    "max_repeated_action",
    "min_arc_events",
}
_STYLE_ENUMS = {
    "language": {"zh-CN"},
    "point_of_view": {"omniscient", "limited", "observer"},
    "narrative_distance": {"intimate", "close", "medium", "distant"},
    "register": {
        "contemporary",
        "literary",
        "vernacular",
        "classical-vernacular",
    },
    "rhythm": {"restrained", "balanced", "brisk"},
    "dialogue_density": {"sparse", "balanced", "rich"},
    "scene_shape": {"turn-centered"},
    "exposition": {"implicit", "direct"},
    "revision_level": {"developmental-and-line"},
}


def typed_overrides(
    value: Any,
    allowed: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EXPERIENCE_PROFILE", path, "overrides must be an object"
            )
        )
        return {}
    _reject_unknown_fields(value, allowed, path, diagnostics)
    return dict(value)


def compile_voice_registers(
    value: Any,
    character_ids: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> tuple[CharacterVoiceRegisterSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_VOICE_REGISTERS",
                path,
                "character voice registers must be an object keyed by character id",
            )
        )
        return ()
    result: list[CharacterVoiceRegisterSpec] = []
    for character_id, raw in sorted(value.items()):
        item_path = f"{path}.{character_id}"
        if character_id not in character_ids:
            diagnostics.append(
                PackageDiagnostic(
                    "UNSAFE_EXPERIENCE_REFERENCE",
                    item_path,
                    f"voice register references unknown character: {character_id}",
                )
            )
        if not isinstance(raw, dict):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_VOICE_REGISTER",
                    item_path,
                    "voice register must be an object",
                )
            )
            continue
        _reject_unknown_fields(
            raw,
            {"first_attentions", "diction", "syntax", "withheld"},
            item_path,
            diagnostics,
        )
        first_attentions = _string_tuple(
            raw.get("first_attentions"), f"{item_path}.first_attentions", diagnostics
        )
        withheld = _string_tuple(
            raw.get("withheld", []), f"{item_path}.withheld", diagnostics
        )
        diction = raw.get("diction")
        syntax = raw.get("syntax")
        if not isinstance(diction, str) or not diction.strip():
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_VOICE_REGISTER",
                    f"{item_path}.diction",
                    "diction must be a non-empty string",
                )
            )
            diction = ""
        if not isinstance(syntax, str) or not syntax.strip():
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_VOICE_REGISTER",
                    f"{item_path}.syntax",
                    "syntax must be a non-empty string",
                )
            )
            syntax = ""
        result.append(
            CharacterVoiceRegisterSpec(
                character_id,
                first_attentions,
                str(diction),
                str(syntax),
                withheld,
            )
        )
    return tuple(result)


def _string_tuple(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_VOICE_REGISTER",
                path,
                "expected an array of non-empty strings",
            )
        )
        return ()
    return tuple(value)


def validate_style(
    style: dict[str, Any], path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    if style.get("skill_id") not in literary_skill_ids():
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_LITERARY_SKILL",
                f"{path}.skill_id",
                f"literary skill is not registered: {style.get('skill_id')}",
            )
        )
    if style.get("voice_id") not in world_voice_ids():
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_WORLD_VOICE",
                f"{path}.voice_id",
                f"world voice is not registered: {style.get('voice_id')}",
            )
        )
    for field, allowed in _STYLE_ENUMS.items():
        if style.get(field) not in allowed:
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_EXPERIENCE_PROFILE",
                    f"{path}.{field}",
                    f"{field} is not a registered typed value",
                )
            )
    for field in ("imagery_domains", "forbidden_phrases"):
        raw = style.get(field)
        if not isinstance(raw, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_EXPERIENCE_PROFILE",
                    f"{path}.{field}",
                    f"{field} must be an array of non-empty strings",
                )
            )
        else:
            style[field] = tuple(raw)


def validate_episode(
    episode: dict[str, Any], path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    for field in EPISODE_FIELDS:
        value = episode.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_EXPERIENCE_PROFILE",
                    f"{path}.{field}",
                    f"{field} must be a positive integer",
                )
            )
