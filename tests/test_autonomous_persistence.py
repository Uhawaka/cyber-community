import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from engine.application import create_run, export_run, fork_run, load_run, run_ticks
from engine.runtime import Delta, EventPersistenceError, EventType, WorldEvent
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]


def _compiled():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.compiled is not None
    return result.compiled


def test_jsonl_round_trip_continues_same_deterministic_history(tmp_path):
    path = tmp_path / "run.jsonl"
    original = create_run(_compiled(), 17, path)
    run_ticks(original, 6)

    loaded = load_run(original.compiled, path)
    assert loaded.events == original.events
    assert loaded.state == original.state
    run_ticks(original, 4)
    run_ticks(loaded, 4)
    assert loaded.history_hash() == original.history_hash()


def test_partial_tail_can_be_quarantined_and_recovered(tmp_path):
    path = tmp_path / "run.jsonl"
    run = create_run(_compiled(), 17, path)
    run_ticks(run, 3)
    expected = run.state
    with path.open("ab") as stream:
        stream.write(b'{"schema_version":"autonomous-event')

    with pytest.raises(EventPersistenceError):
        load_run(run.compiled, path)
    recovered = load_run(run.compiled, path, recover_tail=True)
    assert recovered.state == expected
    assert path.with_name(path.name + ".corrupt-tail").read_bytes()
    assert path.read_bytes().endswith(b"\n")


def test_valid_json_without_newline_is_quarantined_before_continuing(tmp_path):
    path = tmp_path / "run.jsonl"
    run = create_run(_compiled(), 17, path)
    run_ticks(run, 1)
    raw = path.read_bytes()
    path.write_bytes(raw.rstrip(b"\n"))

    with pytest.raises(EventPersistenceError, match="unterminated"):
        load_run(run.compiled, path)
    recovered = load_run(run.compiled, path, recover_tail=True)
    assert recovered.events == run.events[:-1]
    assert path.read_bytes().endswith(b"\n")
    assert path.with_name(path.name + ".corrupt-tail").read_bytes()


def test_two_writers_reject_divergent_same_sequence(tmp_path):
    path = tmp_path / "run.jsonl"
    first = create_run(_compiled(), 17, path)
    second = load_run(first.compiled, path)
    run_ticks(first, 1)
    state = second.state

    with pytest.raises(EventPersistenceError, match="divergent"):
        second.log.append(
            WorldEvent(
                sequence=len(second.events),
                tick=state.tick,
                event_type=EventType.WAITED,
                actor_id=None,
                observers=tuple(state.characters),
                delta=Delta(advance_tick=1, advance_time=1),
                data={"writer": "second"},
                pre_state_hash=state.state_hash(),
                world_hash=state.world_hash,
            )
        )
    assert second.state == state
    assert len(second.events) == 1


def test_middle_corruption_and_world_hash_mismatch_fail_closed(tmp_path):
    path = tmp_path / "run.jsonl"
    run = create_run(_compiled(), 17, path)
    run_ticks(run, 3)
    lines = path.read_bytes().splitlines(keepends=True)
    lines[1] = b"{broken-json}\n"
    path.write_bytes(b"".join(lines))
    with pytest.raises(EventPersistenceError, match="line 2"):
        load_run(run.compiled, path, recover_tail=True)

    export_run(run, path)
    records = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(records[0])
    first["world_hash"] = "wrong-world"
    records[0] = json.dumps(first)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")
    with pytest.raises(EventPersistenceError, match="world hash"):
        load_run(run.compiled, path)


def test_export_is_private_and_preserves_fork_metadata(tmp_path):
    source = create_run(_compiled(), 11)
    run_ticks(source, 2)
    branch = fork_run(source, event_count=len(source.events) - 1)
    path = export_run(branch, tmp_path / "branch.jsonl")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = load_run(source.compiled, path)
    assert loaded.parent_history_hash == branch.history_hash()
    assert loaded.fork_sequence == len(branch.events) - 1
    assert loaded.events == branch.events


def test_compiled_world_hash_mismatch_is_rejected(tmp_path):
    path = tmp_path / "run.jsonl"
    compiled = _compiled()
    create_run(compiled, 7, path)
    changed = replace(compiled, content_hash="0" * 64)
    with pytest.raises(EventPersistenceError, match="world hash"):
        load_run(changed, path)
