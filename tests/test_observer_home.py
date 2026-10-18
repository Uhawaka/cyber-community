from pathlib import Path

from engine.application import create_run, get_observer_home, run_ticks
from engine.narrative import DeliveryPolicy, PresentationStore
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]


def test_observer_home_is_complete_and_does_not_advance_run():
    compiled = compile_package(ROOT / "worlds" / "echo-quay")
    assert compiled.ok and compiled.compiled is not None
    run = create_run(compiled.compiled, seed=17)
    run_ticks(run, 3)
    events_before = run.events
    state_before = run.state
    hash_before = run.history_hash()

    home = get_observer_home(
        run,
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=2),
    )

    assert home.world.world_id == run.state.world_id
    assert home.world.title
    assert home.recent_key_changes
    assert 0 < home.due_episode.unpresented_event_count < len(run.events)
    assert run.events == events_before
    assert run.state == state_before
    assert run.history_hash() == hash_before
