"""The sole composition root for concrete engine adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from engine.adapters import JsonlRunStorage, OpenAICompatibleTextModel
from engine.adapters.community_policy import ModelCommunityPolicy
from engine.contracts import RunStorage, TextModel
from engine.contracts.community import CommunityPolicy
from engine.runtime.kernel.lifecycle import create_run
from engine.runtime.simulation.run import AutonomousRun
from engine.world.package_spec import CompiledWorld


@dataclass
class ApplicationComposition:
    compiled: CompiledWorld
    run_storage: RunStorage | None = None
    community_policy: CommunityPolicy | None = None
    community_config: dict | None = None

    def create_run(self, seed: int) -> AutonomousRun:
        if self.run_storage is not None:
            run = self.run_storage.create(self.compiled, seed)
        else:
            run = create_run(
                self.compiled,
                seed,
                community_config=self.community_config,
            )
        run.community_policy = (
            self.community_policy.for_run() if isinstance(self.community_policy, ModelCommunityPolicy)
            else self.community_policy
        )
        return run

    def run_ticks(self, run: AutonomousRun, ticks: int) -> Any:
        from engine.runtime.simulation.community import run_community_ticks, run_managed_community_ticks
        policy = getattr(run, "community_policy", None)
        if policy is None and self.community_policy is not None:
            policy = (self.community_policy.for_run() if isinstance(self.community_policy, ModelCommunityPolicy)
                      else self.community_policy)
        budgets = ({key: self.community_config[key] for key in ("action_budget", "memory_budget")}
                   if self.community_config else {})
        runner = run_managed_community_ticks if self.community_config else run_community_ticks
        result = runner(run, ticks, decision_policy=policy, **budgets)
        if policy is not None:
            run.community_policy = policy
        return result


def build_application(
    compiled: CompiledWorld,
    *,
    model_config: Mapping[str, object] | None = None,
    text_model: TextModel | None = None,
    run_path: str | Path | None = None,
) -> ApplicationComposition:
    """Build a community application with optional model-backed decisions."""

    if compiled.community is None:
        raise ValueError("application requires a versioned community package")
    model_enabled = model_config is not None or text_model is not None
    settings = dict(model_config or {})
    selected_model = text_model
    if model_enabled:
        if selected_model is None:
            selected_model = OpenAICompatibleTextModel(settings)

    community_policy = (
        ModelCommunityPolicy(
            selected_model,
            timeout_seconds=settings.get("community_timeout_seconds", 10.0),
            max_requests=settings.get("community_max_requests", 1000),
        ) if model_enabled else None
    )
    managed = settings.get("community_managed", False)
    if not isinstance(managed, bool):
        raise ValueError("community_managed must be boolean")
    community_config = None
    if managed:
        if community_policy is None:
            raise ValueError("model-managed configuration requires an explicit model")
        from engine.runtime.simulation.community_model_config import make_model_config
        community_config = make_model_config(
            compiled, community_policy, action_budget=settings.get("community_action_budget"),
            memory_budget=settings.get("community_memory_budget", 1),
        )
    run_storage = (
        JsonlRunStorage(
            run_path,
            community_config=community_config,
        )
        if run_path is not None
        else None
    )
    return ApplicationComposition(
        compiled=compiled,
        run_storage=run_storage,
        community_policy=community_policy,
        community_config=community_config,
    )
