"""Resumable, chapter-targeted world simulation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from engine.application import (
    apply_intervention,
    get_pending_user_gate,
    publish_due_episodes,
    rerender_episode,
)
from engine.application.longrun_validation import evaluate_longrun
from engine.bootstrap import build_application
from engine.narrative import story_document_name, write_story_markdown
from engine.narrative.planning import NarrativeStyleProfile
from engine.runtime.kernel.events import EventType
from engine.world import compile_package


def run_longform(
    package: Path,
    *,
    target_episodes: int,
    max_ticks: int,
    chunk_ticks: int,
    seed: int,
    model_config: dict[str, object] | None,
    output: Path,
    run_output: Path,
    presentation_output: Path,
    story_output_dir: Path,
    gate_choice: str | None,
    resume: bool,
) -> dict[str, object]:
    if min(target_episodes, max_ticks, chunk_ticks) < 1:
        raise ValueError("longform targets and tick budgets must be positive")
    result = compile_package(package)
    if not result.ok or result.compiled is None:
        raise ValueError("world package validation failed")
    compiled = result.compiled
    application = build_application(
        compiled,
        model_config=model_config,
        run_path=run_output,
        presentation_path=presentation_output,
    )
    if resume:
        if application.run_storage is None or not run_output.exists():
            raise ValueError("--resume requires an existing run output")
        run = application.run_storage.load(compiled)
        if run.state.seed != seed:
            raise ValueError("resume seed does not match the stored run")
    else:
        run = application.create_run(seed)
    store = application.presentation_storage
    store_view = getattr(store, "core", store)
    story_output_dir.mkdir(parents=True, exist_ok=True)
    requested_from_tick = run.state.tick
    reports: list[dict[str, object]] = []
    run_diagnostics: list[str] = []
    stop_reason = "max_ticks"
    while (
        len(store_view.presentations) < target_episodes
        and run.state.tick < max_ticks
    ):
        pending = get_pending_user_gate(run)
        if pending is not None:
            if gate_choice is None:
                stop_reason = "user_gate"
                break
            if gate_choice not in pending.choice_ids:
                raise ValueError(
                    f"gate choice {gate_choice} is not available for "
                    f"{pending.gate_id}"
                )
            apply_intervention(run, pending.gate_id, gate_choice)
        remaining = max_ticks - run.state.tick
        report = application.run_ticks(
            run, min(chunk_ticks, remaining)
        )
        reports.append(asdict(report))
        try:
            published = publish_due_episodes(
                run,
                store_view,
                renderer=application.renderer,
                render_timeout=application.render_timeout,
                release_tail=False,
            )
        except (ValueError, RuntimeError) as exc:
            published = ()
            stop_reason = "delivery_failure"
            run_diagnostics.append(f"delivery failure: {exc}")
        else:
            stop_reason = "max_ticks"
        for presentation in published:
            write_story_markdown(
                story_output_dir / story_document_name(presentation),
                presentation,
                package_id=compiled.manifest.package_id,
                world_title=compiled.world.title,
                seed=seed,
            )
        _retry_fallback_presentations(
            store_view,
            application,
            compiled,
            story_output_dir,
            seed,
            run_diagnostics,
        )
        payload = _longform_payload(
            run,
            store_view,
            target_episodes=target_episodes,
            max_ticks=max_ticks,
            requested_from_tick=requested_from_tick,
            stop_reason="running",
            reports=reports,
            model_budget=application.model_budget,
            diagnostics=(
                *application.diagnostics,
                *run_diagnostics,
            ),
        )
        _write_report(output, payload)
        if report.executed_ticks == 0:
            stop_reason = (
                "user_gate"
                if get_pending_user_gate(run) is not None
                else "no_progress"
            )
            break
    _retry_fallback_presentations(
        store_view,
        application,
        compiled,
        story_output_dir,
        seed,
        run_diagnostics,
    )
    if len(store_view.presentations) >= target_episodes:
        stop_reason = "target_episodes_reached"
    payload = _longform_payload(
        run,
        store_view,
        target_episodes=target_episodes,
        max_ticks=max_ticks,
        requested_from_tick=requested_from_tick,
        stop_reason=stop_reason,
        reports=reports,
        model_budget=application.model_budget,
        diagnostics=(*application.diagnostics, *run_diagnostics),
    )
    _write_report(output, payload)
    return payload


def _longform_payload(
    run: Any,
    store: Any,
    *,
    target_episodes: int,
    max_ticks: int,
    requested_from_tick: int,
    stop_reason: str,
    reports: list[dict[str, object]],
    model_budget: dict[str, int],
    diagnostics: tuple[str, ...],
) -> dict[str, object]:
    events = tuple(run.events)
    visited: dict[str, set[str]] = defaultdict(set)
    scene_ids: set[str] = set()
    movement_count = 0
    for event in events:
        if event.event_type is EventType.MOVED and event.actor_id:
            movement_count += 1
            visited[event.actor_id].update(
                {
                    str(event.data.get("origin_id", "")),
                    str(event.data.get("destination_id", "")),
                }
            )
        if event.event_type is EventType.SCENE_INSTANTIATED:
            scene_ids.add(str(event.data.get("scene_id", "")))
    for actor_id, state in run.state.characters.items():
        visited[actor_id].add(state.location_id)
    presentations = tuple(store.presentations)
    fallback_count = sum(
        bool(value.render_diagnostics)
        and value.render_diagnostics[-1].status == "fallback"
        for value in presentations
    )
    sync_violations = [
        actor_id
        for actor_id, state in run.state.characters.items()
        if actor_id in run.state.entities
        and run.state.entities[actor_id]
        .components.get("presence", {})
        .get("location_id")
        != state.location_id
    ]
    pending = get_pending_user_gate(run)
    fallback_rate = (
        fallback_count / len(presentations) if presentations else 0.0
    )
    longrun_validation = evaluate_longrun(
        run,
        presentations,
        fallback_rate=fallback_rate,
        position_sync_violations=sync_violations,
    )
    return {
        "schema_version": "longform-run-report.v1",
        "ok": not sync_violations and stop_reason != "delivery_failure",
        "package_id": run.compiled.manifest.package_id,
        "seed": run.state.seed,
        "target_episodes": target_episodes,
        "episode_count": len(presentations),
        "requested_from_tick": requested_from_tick,
        "max_ticks": max_ticks,
        "executed_to_tick": run.state.tick,
        "stop_reason": stop_reason,
        "pending_user_gate": (
            None
            if pending is None
            else {
                "gate_id": pending.gate_id,
                "choice_ids": list(pending.choice_ids),
            }
        ),
        "event_count": len(events),
        "event_counts": dict(
            sorted(Counter(item.event_type.value for item in events).items())
        ),
        "movement_count": movement_count,
        "visited_locations": {
            key: sorted(item for item in value if item)
            for key, value in sorted(visited.items())
        },
        "scene_ids": sorted(item for item in scene_ids if item),
        "position_sync_violations": sync_violations,
        "presentation_cursor": store.cursor_for("omniscient"),
        "unpublished_event_count": max(
            0, len(events) - store.cursor_for("omniscient")
        ),
        "fallback_count": fallback_count,
        "fallback_rate": fallback_rate,
        "longrun_validation": longrun_validation,
        "history_hash": run.history_hash(),
        "model_call_budget": model_budget,
        "diagnostics": list(diagnostics),
        "tick_reports": reports,
        "episodes": [
            {
                "episode_id": item.episode_id,
                "presentation_id": item.presentation_id,
                "title": item.rendered.title,
                "source_event_count": len(item.source_event_ids),
                "render_diagnostics": [
                    asdict(value) for value in item.render_diagnostics
                ],
            }
            for item in presentations
        ],
    }


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _retry_fallback_presentations(
    store: Any,
    application: Any,
    compiled: Any,
    story_output_dir: Path,
    seed: int,
    diagnostics: list[str],
) -> None:
    presentation_policy = dict(compiled.workflow.presentation.policy)
    style = NarrativeStyleProfile.from_mapping(
        presentation_policy.get("style")
    )
    labels = {
        compiled.world.world_id: compiled.world.title,
        **{item.id: item.name for item in compiled.world.characters},
        **{item.id: item.name for item in compiled.world.locations},
        **{item.id: item.name for item in compiled.world.resources},
    }
    for current in tuple(store.presentations):
        if (
            not current.render_diagnostics
            or current.render_diagnostics[-1].status != "fallback"
        ):
            continue
        try:
            rendered = rerender_episode(
                store,
                current.presentation_id,
                renderer=application.renderer,
                style_profile=style,
                render_timeout=application.render_timeout,
                labels=labels,
            )
        except (ValueError, RuntimeError) as exc:
            diagnostics.append(
                f"rerender failure for {current.episode_id}: {exc}"
            )
            continue
        write_story_markdown(
            story_output_dir / story_document_name(rendered),
            rendered,
            package_id=compiled.manifest.package_id,
            world_title=compiled.world.title,
            seed=seed,
        )
