"""Compile character package directories into typed character values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.contracts.personhood import personhood_from_soul
from engine.world.package_source import _read_array, _read_object
from engine.world.package_spec import PackageCharacter, PackageDiagnostic
from engine.world.package_validation import MAX_CHARACTERS, MAX_MEMORY_SEEDS, MAX_MEMORY_SUMMARY_LENGTH, _reject_unknown_fields, _validate_memory_seed


def _pairs(value: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(value.items()))


def _compile_characters(
    directory: Path,
    root: Path,
    diagnostics: list[PackageDiagnostic],
    ref: str,
) -> list[PackageCharacter]:
    characters: list[PackageCharacter] = []
    character_dirs = sorted(path for path in directory.iterdir() if path.is_dir())
    if len(character_dirs) > MAX_CHARACTERS:
        diagnostics.append(
            PackageDiagnostic(
                "LIMIT_EXCEEDED",
                ref,
                f"at most {MAX_CHARACTERS} characters are allowed",
            )
        )
        character_dirs = character_dirs[:MAX_CHARACTERS]
    for character_dir in character_dirs:
        character_id = character_dir.name
        profile = _read_object(character_dir / "profile.yaml", root, diagnostics)
        soul = _read_object(character_dir / "soul.yaml", root, diagnostics)
        memory = _read_array(character_dir / "memory.seed.json", root, diagnostics)
        _reject_unknown_fields(
            profile,
            {
                "name",
                "role",
                "location_id",
                "identity",
                "skills",
                "goals",
                "errands",
                "needs",
                "motivation",
                "responsibilities",
                "learning_interests",
                "known_routes",
                "home_location_id",
                "routine_locations",
                "access_tags",
                "stocking_interests",
            },
            f"characters.{character_id}.profile.yaml",
            diagnostics,
        )
        _reject_unknown_fields(
            soul,
            {
                "identity",
                "self_view",
                "values",
                "taboos",
                "protective_style",
                "drives",
                "voice",
                "relationship_stance",
                "secrets",
                "beliefs",
                "version",
                "long_term_desire",
                "inner_conflict",
                "interests",
                "vulnerabilities",
                "capability_limits",
            },
            f"characters.{character_id}.soul.yaml",
            diagnostics,
        )
        _validate_character_profile(profile, character_id, diagnostics)
        _validate_character_soul(soul, character_id, diagnostics)
        _validate_memory_seed(memory, character_id, diagnostics)
        private_memory = _compile_private_seed_memory(soul, character_id, diagnostics)
        if len(memory) + len(private_memory) > MAX_MEMORY_SEEDS:
            diagnostics.append(
                PackageDiagnostic(
                    "LIMIT_EXCEEDED",
                    f"characters.{character_id}.memory",
                    f"authored and private memory combined may contain at most {MAX_MEMORY_SEEDS} entries",
                )
            )
        characters.append(
            PackageCharacter(
                id=character_id,
                name=str(profile.get("name") or "").strip(),
                role=str(profile.get("role") or "").strip(),
                location_id=str(profile.get("location_id") or "").strip(),
                profile=_pairs(
                    {
                        key: value
                        for key, value in profile.items()
                        if key not in {"name", "role", "location_id"}
                    }
                ),
                soul=_pairs(
                    {
                        key: value
                        for key, value in soul.items()
                        if key not in {"secrets", "beliefs"}
                    }
                ),
                memory_seed=tuple(memory + private_memory),
            )
        )
    if not characters:
        diagnostics.append(
            PackageDiagnostic("NO_CHARACTERS", ref, "characters directory must contain character packages")
        )
    return characters


def _compile_private_seed_memory(
    soul: dict[str, Any],
    character_id: str,
    diagnostics: list[PackageDiagnostic],
) -> list[dict[str, Any]]:
    """Lower private character knowledge into character-scoped seed memory."""

    result: list[dict[str, Any]] = []
    for field, kind, confidence in (
        ("secrets", "secret", 1.0),
        ("beliefs", "belief", 0.75),
    ):
        if field not in soul:
            continue
        values = soul[field]
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_PRIVATE_MEMORY",
                    f"characters.{character_id}.soul.yaml.{field}",
                    f"{field} must be an array of non-empty strings",
                )
            )
            continue
        if len(values) > MAX_MEMORY_SEEDS:
            diagnostics.append(
                PackageDiagnostic(
                    "LIMIT_EXCEEDED",
                    f"characters.{character_id}.soul.yaml.{field}",
                    f"at most {MAX_MEMORY_SEEDS} private memory entries are allowed",
                )
            )
        if any(len(item) > MAX_MEMORY_SUMMARY_LENGTH for item in values):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_PRIVATE_MEMORY",
                    f"characters.{character_id}.soul.yaml.{field}",
                    f"private memory text may contain at most {MAX_MEMORY_SUMMARY_LENGTH} characters",
                )
            )
        result.extend(
            {
                "kind": kind,
                "summary": item.strip(),
                "confidence": confidence,
                "visibility": "private",
            }
            for item in values
        )
    return result


def _validate_character_profile(
    profile: dict[str, Any],
    character_id: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    for field in ("skills", "responsibilities", "learning_interests", "known_routes", "routine_locations", "access_tags", "stocking_interests"):
        value = profile.get(field)
        if value is not None and (
            not isinstance(value, list) or len(value) > 128
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            diagnostics.append(PackageDiagnostic(
                "INVALID_CHARACTER_PROFILE", f"characters.{character_id}.profile.yaml.{field}",
                "profile collections must be bounded arrays of non-empty strings",
            ))
    goals = profile.get("goals")
    if goals is not None and (
        not isinstance(goals, list)
        or any(not isinstance(item, str) or not item.strip() for item in goals)
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_GOALS",
                f"characters.{character_id}.profile.yaml.goals",
                "goals must be an array of non-empty strings",
            )
        )
    needs = profile.get("needs")
    if needs is not None and (
        not isinstance(needs, dict)
        or any(
            not isinstance(key, str)
            or not key
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
            or value > 100
            for key, value in (needs.items() if isinstance(needs, dict) else ())
        )
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_NEEDS",
                f"characters.{character_id}.profile.yaml.needs",
                "needs must map names to numbers from 0 through 100",
            )
        )
    motivation = profile.get("motivation")
    if motivation is not None:
        _validate_motivation(
            motivation,
            f"characters.{character_id}.profile.yaml.motivation",
            diagnostics,
        )


def _validate_motivation(
    value: object,
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    fields = {
        "terminal_desire",
        "fear",
        "sacrifice_boundary",
        "active_commitment",
        "completion_signals",
    }
    if not isinstance(value, dict) or set(value) - fields:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_MOTIVATION",
                path,
                "motivation contains unknown fields or is not an object",
            )
        )
        return
    for field in fields - {"completion_signals"}:
        if (
            not isinstance(value.get(field), str)
            or not value[field].strip()
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_CHARACTER_MOTIVATION",
                    f"{path}.{field}",
                    f"{field} must be non-empty text",
                )
            )
    signals = value.get("completion_signals")
    if (
        not isinstance(signals, list)
        or not signals
        or any(
            not isinstance(item, str) or not item.strip()
            for item in signals
        )
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_CHARACTER_MOTIVATION",
                f"{path}.completion_signals",
                "completion_signals must be a non-empty string array",
            )
        )


def _validate_character_soul(
    soul: dict[str, Any],
    character_id: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    path = f"characters.{character_id}.soul.yaml"
    v2_fields = {"long_term_desire", "inner_conflict", "interests", "vulnerabilities", "capability_limits"}
    if "version" in soul or v2_fields & set(soul):
        try:
            if any(not isinstance(soul.get(key), list) for key in
                   ("interests", "vulnerabilities", "capability_limits")):
                raise ValueError("personhood collections must be arrays")
            personhood_from_soul(soul)
        except (ValueError, TypeError, KeyError) as exc:
            diagnostics.append(PackageDiagnostic("INVALID_PERSONHOOD", path, str(exc)))
    for required in ("values", "voice", "drives"):
        if required not in soul:
            diagnostics.append(
                PackageDiagnostic(
                    "MISSING_SOUL_FIELD",
                    f"{path}.{required}",
                    f"soul requires {required}",
                )
            )
    for field in ("values", "taboos", "drives"):
        value = soul.get(field)
        if value is not None and (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_SOUL_FIELD",
                    f"{path}.{field}",
                    f"{field} must be a non-empty array of strings",
                )
            )
    for field in ("identity", "self_view", "protective_style"):
        value = soul.get(field)
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_SOUL_FIELD",
                    f"{path}.{field}",
                    f"{field} must be a non-empty string",
                )
            )
    for field in ("voice", "relationship_stance"):
        value = soul.get(field)
        if value is not None and not isinstance(value, (str, dict)):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_SOUL_FIELD",
                    f"{path}.{field}",
                    f"{field} must be a string or object",
                )
            )
