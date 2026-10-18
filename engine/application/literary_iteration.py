"""Read-only literary iteration over frozen presentation material."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil

from engine.application.story_delivery import rerender_episode
from engine.contracts import NarrativeRenderer
from engine.narrative.artifacts import write_story_markdown
from engine.narrative.persistence import atomic_write_text
from engine.narrative.planning import NarrativeStyleProfile
from engine.narrative.store import Presentation, PresentationStore


def rerender_frozen_presentations(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    renderer: NarrativeRenderer,
    style_profile: NarrativeStyleProfile,
    package_id: str,
    world_title: str,
    seed: int,
    render_timeout: float = 180.0,
    labels: dict[str, str] | None = None,
) -> dict[str, object]:
    """Rerender copied digests without loading or advancing a world run."""

    source = Path(source_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source_hash = _file_hash(source)
    presentation_path = destination / "presentations.json"
    shutil.copy2(source, presentation_path)
    store = PresentationStore.load(presentation_path)
    originals = _latest_per_episode(store.presentations)
    stories = destination / "stories"
    stories.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for original in originals:
        rendered = rerender_episode(
            store,
            original.presentation_id,
            renderer=renderer,
            style_profile=style_profile,
            render_timeout=render_timeout,
            labels=labels,
        )
        diagnostics = rendered.render_diagnostics[
            len(original.render_diagnostics) :
        ]
        story_path = stories / f"{rendered.episode_id}.md"
        write_story_markdown(
            story_path,
            rendered,
            package_id=package_id,
            world_title=world_title,
            seed=seed,
        )
        trace = {
            "episode_id": rendered.episode_id,
            "presentation_id": rendered.presentation_id,
            "source_event_ids": list(rendered.source_event_ids),
            "render_diagnostics": [
                asdict(item) for item in diagnostics
            ],
            "editorial_artifacts": getattr(
                renderer, "last_artifacts", {}
            ),
        }
        trace_path = destination / f"{rendered.episode_id}-trace.json"
        atomic_write_text(
            trace_path,
            json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
        )
        results.append(
            {
                "episode_id": rendered.episode_id,
                "presentation_id": rendered.presentation_id,
                "story": str(story_path),
                "trace": str(trace_path),
                "source_event_count": len(rendered.source_event_ids),
                "status": diagnostics[0].status,
            }
        )
    if _file_hash(source) != source_hash:
        raise RuntimeError("literary iteration mutated frozen source material")
    report = {
        "schema_version": "literary-iteration-report.v1",
        "source": str(source),
        "source_sha256": source_hash,
        "world_advanced": False,
        "editorial_pipeline": list(style_profile.editorial_pipeline),
        "results": results,
    }
    atomic_write_text(
        destination / "summary.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return report


def _latest_per_episode(
    presentations: tuple[Presentation, ...],
) -> tuple[Presentation, ...]:
    selected: dict[str, Presentation] = {}
    for item in presentations:
        current = selected.get(item.episode_id)
        if current is None or item.render_version > current.render_version:
            selected[item.episode_id] = item
    return tuple(
        sorted(selected.values(), key=lambda item: item.episode_id)
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
