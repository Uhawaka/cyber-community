"""Thin JSONL run-storage adapter over the runtime persistence implementation."""

from __future__ import annotations

from pathlib import Path

from engine.runtime.kernel.lifecycle import create_run, export_run, load_run
from engine.runtime.simulation.run import AutonomousRun
from engine.world.package_spec import CompiledWorld


class JsonlRunStorage:
    def __init__(
        self,
        path: str | Path,
        *,
        recover_tail: bool = False,
        community_config: dict | None = None,
    ) -> None:
        self.path = Path(path)
        self.recover_tail = recover_tail
        self.community_config = community_config

    def create(self, compiled: CompiledWorld, seed: int) -> AutonomousRun:
        return create_run(
            compiled,
            seed,
            self.path,
            community_config=self.community_config,
        )

    def load(self, compiled: CompiledWorld) -> AutonomousRun:
        return load_run(
            compiled,
            self.path,
            recover_tail=self.recover_tail,
        )

    def save(
        self,
        run: AutonomousRun,
        destination: str | Path | None = None,
    ) -> Path:
        return export_run(run, destination or self.path)
