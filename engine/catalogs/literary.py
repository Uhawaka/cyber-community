"""Read-only metadata catalogs sourced from literary resource manifests."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_NARRATIVE_ROOT = Path(__file__).parents[1] / "narrative"


@lru_cache(maxsize=1)
def _skill_stages() -> dict[str, str]:
    path = _NARRATIVE_ROOT / "skill_library" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "literary-skill-library/v1":
        raise RuntimeError("unsupported literary skill library")
    result = {
        str(item["id"]): str(item["stage"])
        for item in manifest.get("skills", ())
        if isinstance(item, dict)
    }
    result["scene-craft-v2"] = "editorial_pipeline"
    return result


@lru_cache(maxsize=1)
def world_voice_ids() -> tuple[str, ...]:
    path = _NARRATIVE_ROOT / "voice_library" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "world-voice-library/v1":
        raise RuntimeError("unsupported world voice library")
    return tuple(
        str(item["id"])
        for item in manifest.get("voices", ())
        if isinstance(item, dict)
    )


def literary_skill_ids() -> tuple[str, ...]:
    return tuple(_skill_stages())


def literary_skill_stage(skill_id: str) -> str:
    try:
        return _skill_stages()[skill_id]
    except KeyError as exc:
        raise ValueError(f"unknown literary skill: {skill_id}") from exc
