"""Thin JSONL run-storage adapter over the runtime persistence implementation."""

from __future__ import annotations

from pathlib import Path

from engine.contracts import (
    ActorPolicy,
    IntentPolicy,
    SceneGenerator,
    WorldAdjudicator,
)
from engine.runtime.kernel.lifecycle import create_run, export_run, load_run
from engine.runtime.simulation.run import AutonomousRun
from engine.world.package_spec import CompiledWorld


class JsonlRunStorage:
    def __init__(
        self,
        path: str | Path,
        *,
        actor_policy: ActorPolicy | None = None,
        scene_generator: SceneGenerator | None = None,
        intent_policy: IntentPolicy | None = None,
        world_adjudicator: WorldAdjudicator | None = None,
        recover_tail: bool = False,
    ) -> None:
        self.path = Path(path)
        self.actor_policy = actor_policy
        self.scene_generator = scene_generator
        self.intent_policy = intent_policy
        self.world_adjudicator = world_adjudicator
        self.recover_tail = recover_tail

    def create(self, compiled: CompiledWorld, seed: int) -> AutonomousRun:
        return create_run(
            compiled,
            seed,
            self.path,
            actor_policy=self.actor_policy,
            scene_generator=self.scene_generator,
            intent_policy=self.intent_policy,
            world_adjudicator=self.world_adjudicator,
        )

    def load(self, compiled: CompiledWorld) -> AutonomousRun:
        return load_run(
            compiled,
            self.path,
            recover_tail=self.recover_tail,
            actor_policy=self.actor_policy,
            scene_generator=self.scene_generator,
            intent_policy=self.intent_policy,
            world_adjudicator=self.world_adjudicator,
        )

    def save(
        self,
        run: AutonomousRun,
        destination: str | Path | None = None,
    ) -> Path:
        return export_run(run, destination or self.path)
