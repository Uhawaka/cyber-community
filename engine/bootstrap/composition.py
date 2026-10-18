"""The sole composition root for concrete engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from engine.adapters import (
    JsonPresentationStorage,
    JsonlRunStorage,
    ModelActorPolicy,
    ModelIntentPolicy,
    ModelNarrativeRenderer,
    ModelSceneGenerator,
    ModelWorldAdjudicator,
    OpenAICompatibleTextModel,
)
from engine.contracts import (
    ActorPolicy,
    IntentPolicy,
    NarrativeRenderer,
    PresentationStorage,
    RunStorage,
    SceneGenerator,
    TextModel,
    WorldAdjudicator,
)
from engine.narrative.rendering import StructuredLiteraryRenderer
from engine.narrative.store import PresentationStore
from engine.runtime.character.policy import (
    DeterministicActorPolicy,
    ModelDialogueActorPolicy,
)
from engine.runtime.kernel.lifecycle import create_run
from engine.runtime.scene import (
    DeterministicIntentPolicy,
    DeterministicSceneGenerator,
    DeterministicWorldAdjudicator,
)
from engine.runtime.simulation.executor import run_ticks
from engine.runtime.simulation.run import AutonomousRun
from engine.world.package_spec import CompiledWorld


@dataclass
class ApplicationComposition:
    compiled: CompiledWorld
    actor_policy: ActorPolicy
    renderer: NarrativeRenderer
    presentation_storage: PresentationStorage
    run_storage: RunStorage | None = None
    text_model: TextModel | None = None
    scene_generator: SceneGenerator | None = None
    intent_policy: IntentPolicy | None = None
    world_adjudicator: WorldAdjudicator | None = None
    render_timeout: float = 2.0

    def create_run(self, seed: int) -> AutonomousRun:
        if self.run_storage is not None:
            return self.run_storage.create(self.compiled, seed)
        return create_run(
            self.compiled,
            seed,
            actor_policy=self.actor_policy,
            scene_generator=self.scene_generator,
            intent_policy=self.intent_policy,
            world_adjudicator=self.world_adjudicator,
        )

    def run_ticks(self, run: AutonomousRun, ticks: int) -> Any:
        return run_ticks(run, ticks)

    @property
    def model_budget(self) -> dict[str, int]:
        budget = getattr(self.text_model, "budget", None)
        return dict(budget) if isinstance(budget, Mapping) else {
            "requests": 0,
            "successful_calls": 0,
            "errors": 0,
        }

    @property
    def diagnostics(self) -> tuple[str, ...]:
        values = getattr(self.actor_policy, "diagnostics", ())
        return tuple(str(value) for value in values)


def build_application(
    compiled: CompiledWorld,
    *,
    deterministic: bool | None = None,
    model_config: Mapping[str, object] | None = None,
    text_model: TextModel | None = None,
    run_path: str | Path | None = None,
    presentation_path: str | Path | None = None,
) -> ApplicationComposition:
    """Build deterministic services unless model use is explicitly configured."""

    model_enabled = (
        (model_config is not None or text_model is not None)
        and deterministic is not True
    )
    selected_model = text_model
    actor_policy: ActorPolicy = DeterministicActorPolicy()
    scene_generator: SceneGenerator = DeterministicSceneGenerator()
    intent_policy: IntentPolicy = DeterministicIntentPolicy()
    world_adjudicator: WorldAdjudicator = (
        DeterministicWorldAdjudicator()
    )
    renderer: NarrativeRenderer = StructuredLiteraryRenderer(_labels(compiled))
    if model_enabled:
        settings = dict(model_config or {})
        selected_model = selected_model or OpenAICompatibleTextModel(
            settings
        )
        actor_mode = settings.get("actor_model", True)
        if actor_mode == "dialogue_only":
            actor_policy = ModelDialogueActorPolicy(
                selected_model,
                timeout_seconds=float(
                    settings.get("actor_timeout_seconds", 20.0)
                ),
            )
        elif bool(actor_mode):
            actor_policy = ModelActorPolicy(
                selected_model,
                timeout_seconds=float(
                    settings.get("actor_timeout_seconds", 5.0)
                ),
            )
        renderer = ModelNarrativeRenderer(
            selected_model,
            timeout_seconds=float(
                settings.get("renderer_timeout_seconds", 8.0)
            ),
            labels=_labels(compiled),
        )
        scene_generator = ModelSceneGenerator(
            selected_model,
            timeout_seconds=float(
                settings.get("scene_timeout_seconds", 45.0)
            ),
        )
        intent_policy = ModelIntentPolicy(
            selected_model,
            timeout_seconds=float(
                settings.get("intent_timeout_seconds", 45.0)
            ),
        )
        world_adjudicator = ModelWorldAdjudicator(
            selected_model,
            timeout_seconds=float(
                settings.get("adjudicator_timeout_seconds", 45.0)
            ),
        )
        render_timeout = float(
            settings.get("delivery_timeout_seconds", 10.0)
        )
    else:
        render_timeout = 2.0

    run_storage = (
        JsonlRunStorage(
            run_path,
            actor_policy=actor_policy,
            scene_generator=scene_generator,
            intent_policy=intent_policy,
            world_adjudicator=world_adjudicator,
        )
        if run_path is not None
        else None
    )
    presentation_storage: PresentationStorage
    if presentation_path is None:
        presentation_storage = PresentationStore()
    else:
        presentation_storage = JsonPresentationStorage(presentation_path)
    return ApplicationComposition(
        compiled=compiled,
        actor_policy=actor_policy,
        renderer=renderer,
        presentation_storage=presentation_storage,
        run_storage=run_storage,
        text_model=selected_model,
        scene_generator=scene_generator,
        intent_policy=intent_policy,
        world_adjudicator=world_adjudicator,
        render_timeout=render_timeout,
    )


def _labels(compiled: CompiledWorld) -> dict[str, str]:
    return {
        "world": "世界",
        compiled.world.world_id: compiled.world.title,
        **{item.id: item.name for item in compiled.world.characters},
        **{item.id: item.name for item in compiled.world.locations},
        **{
            f"scene:{item.id}": item.name
            for item in compiled.world.locations
        },
        **{item.id: item.name for item in compiled.world.resources},
    }
