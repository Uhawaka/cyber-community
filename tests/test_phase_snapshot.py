from pathlib import Path

from engine.runtime.kernel.events import EventType
from engine.runtime.simulation import create_run, run_ticks
from engine.world import compile_package


ROOT = Path(__file__).parents[1]


def test_phase_snapshot_records_state_without_injecting_plot():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    run = create_run(result.compiled, seed=23)

    run_ticks(run, 6)
    snapshots = [
        event for event in run.events
        if event.event_type is EventType.PHASE_SNAPSHOT
    ]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.data["current_state"]["tick"] == 6
    assert snapshot.data["result"]["satisfied"] is True
    assert snapshot.data["unresolved_items"]
    assert not {
        "plot", "script", "dialogue", "next_events", "outcome"
    }.intersection(snapshot.data)

    prior_state = run.state
    run_ticks(run, 1)
    assert run.state.tick == prior_state.tick + 1
    assert len(
        [
            event for event in run.events
            if event.event_type is EventType.PHASE_SNAPSHOT
        ]
    ) == 1
