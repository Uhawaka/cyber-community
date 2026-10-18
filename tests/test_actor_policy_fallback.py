import json
from pathlib import Path

from engine.application import create_run, run_ticks
from engine.runtime.character.policy import ModelActorPolicy
from engine.runtime.kernel.events import EventType
from engine.world.package_compiler import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


def _compiled():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return result.compiled


class FakeModel:
    def __init__(self, replies):
        self.replies = tuple(replies)
        self.calls = 0

    def complete(self, prompt, timeout_seconds):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def test_invalid_model_output_repairs_once_then_falls_back_through_resolver():
    model = FakeModel(("not-json", json.dumps({"opportunity_id": "unknown"})))
    policy = ModelActorPolicy(model)
    run = create_run(_compiled(), seed=7, actor_policy=policy)

    run_ticks(run, 1)

    assert model.calls >= 2
    assert policy.diagnostics
    action_events = [event for event in run.events if event.delta.actions]
    assert action_events
    assert any(
        event.data["actor_policy_diagnostics"] for event in action_events
    )
    assert all(event.pre_state_hash for event in action_events)


def test_timeout_also_has_one_repair_and_deterministic_fallback():
    class TimeoutModel:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt, timeout_seconds):
            self.calls += 1
            raise TimeoutError("fake timeout")

    model = TimeoutModel()
    run = create_run(_compiled(), seed=9)
    policy = ModelActorPolicy(model, timeout_seconds=0.01)
    run_ticks(run, 1, actor_policy=policy)

    assert model.calls >= 2
    assert policy.diagnostics
    assert any(
        event.event_type is EventType.DIALOGUE
        for event in run.events
    ) or any(event.delta.actions for event in run.events)
