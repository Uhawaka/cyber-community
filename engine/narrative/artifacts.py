"""User-facing narrative artifact formats."""

from __future__ import annotations

import json
from pathlib import Path

from engine.narrative.persistence import atomic_write_text
from engine.narrative.store import Presentation


STORY_DOCUMENT_SCHEMA_VERSION = "story-document.v1"


def story_document_name(presentation: Presentation) -> str:
    """Return a stable, filesystem-safe filename for one episode."""

    return f"{presentation.episode_id}.md"


def render_story_markdown(
    presentation: Presentation,
    *,
    package_id: str,
    world_title: str,
    seed: int,
) -> str:
    """Render a Presentation as a standalone reader-facing Markdown document."""

    metadata = {
        "schema_version": STORY_DOCUMENT_SCHEMA_VERSION,
        "package_id": package_id,
        "world_title": world_title,
        "seed": seed,
        "episode_id": presentation.episode_id,
        "presentation_id": presentation.presentation_id,
        "render_version": presentation.render_version,
        "audience_id": presentation.audience_id,
        "world_time_start": presentation.world_time_start,
        "world_time_end": presentation.world_time_end,
        "source_event_count": len(presentation.source_event_ids),
    }
    front_matter = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in metadata.items()
    )
    title = " ".join(presentation.rendered.title.splitlines()).strip()
    body = presentation.rendered.body.strip()
    gate = next(
        (
            entry
            for entry in presentation.digest.entries
            if entry.kind == "gate_opened"
        ),
        None,
    )
    resolved_gate_ids = {
        entry.facts.get("gate_id")
        for entry in presentation.digest.entries
        if entry.kind == "user_intervention"
    }
    prompt = (
        gate.summary
        if gate is not None
        and gate.facts.get("gate_id") not in resolved_gate_ids
        else None
    )
    choice = f"\n\n---\n\n**待选择：** {prompt}" if prompt else ""
    return (
        f"---\n{front_matter}\n---\n\n# {title}\n\n"
        f"{body}{choice}\n"
    )


def write_story_markdown(
    path: str | Path,
    presentation: Presentation,
    *,
    package_id: str,
    world_title: str,
    seed: int,
) -> Path:
    """Atomically write one private, user-readable story document."""

    destination = Path(path)
    atomic_write_text(
        destination,
        render_story_markdown(
            presentation,
            package_id=package_id,
            world_title=world_title,
            seed=seed,
        ),
    )
    return destination
