"""Compile-first package validation with isolated deterministic probe runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from engine.runtime.character import MemoryTier
from engine.runtime.autonomous_director import (
    apply_gate_intervention,
    get_pending_user_gate,
)
from engine.runtime.kernel.events import EventType
from engine.runtime.simulation import create_run, run_ticks
from engine.world import PackageCompileResult, PackageDiagnostic, compile_package


PROBE_SCHEMA_VERSION = "world-package-tests/v1"
MAX_PROBE_SEEDS = 64
MAX_PROBE_TICKS = 256


@dataclass(frozen=True)
class ProbeSeedResult:
    seed: int
    ok: bool
    ticks: int
    history_hash: str
    event_counts: tuple[tuple[str, int], ...]
    checks: tuple[tuple[str, bool], ...]
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageValidationReport:
    compile_result: PackageCompileResult
    seed_results: tuple[ProbeSeedResult, ...] = ()
    probe_diagnostics: tuple[PackageDiagnostic, ...] = ()
    diversity_ok: bool = False
    minimum_unique_histories: int = 0
    unique_history_count: int = 0

    @property
    def compiled(self):
        return self.compile_result.compiled

    @property
    def handshake(self):
        return self.compile_result.handshake

    @property
    def diagnostics(self) -> tuple[PackageDiagnostic, ...]:
        return self.compile_result.diagnostics + self.probe_diagnostics

    @property
    def ok(self) -> bool:
        return (
            self.compile_result.ok
            and bool(self.seed_results)
            and all(item.ok for item in self.seed_results)
            and self.diversity_ok
            and not self.probe_diagnostics
        )


def validate_package(package_dir: str | Path) -> PackageValidationReport:
    """Compile a package, then run non-persistent probes from authored tests."""

    root = Path(package_dir)
    compile_result = compile_package(root)
    if not compile_result.ok or compile_result.compiled is None:
        return PackageValidationReport(compile_result)

    diagnostics: list[PackageDiagnostic] = []
    invariants = _read_test_object(root, "tests/invariants.yaml", diagnostics)
    probes = _read_test_object(root, "tests/probes.yaml", diagnostics)
    config = _parse_probe_config(invariants, probes, diagnostics)
    if config is None or diagnostics:
        return PackageValidationReport(
            compile_result, probe_diagnostics=tuple(diagnostics)
        )

    seeds, tick_budget, required, forbidden, minimum_unique = config
    results = tuple(
        _run_probe(
            compile_result.compiled,
            seed,
            tick_budget,
            required,
            forbidden,
        )
        for seed in seeds
    )
    unique_count = len({item.history_hash for item in results})
    diversity_ok = unique_count >= minimum_unique
    if not diversity_ok:
        diagnostics.append(
            PackageDiagnostic(
                "INSUFFICIENT_PROBE_DIVERSITY",
                "tests/invariants.yaml.minimum_unique_history_hashes",
                f"expected at least {minimum_unique} unique histories, got {unique_count}",
            )
        )
    return PackageValidationReport(
        compile_result=compile_result,
        seed_results=results,
        probe_diagnostics=tuple(diagnostics),
        diversity_ok=diversity_ok,
        minimum_unique_histories=minimum_unique,
        unique_history_count=unique_count,
    )


def _read_test_object(
    root: Path, relative: str, diagnostics: list[PackageDiagnostic]
) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        diagnostics.append(
            PackageDiagnostic("MISSING_PROBE_DEFINITION", relative, "required probe definition is missing")
        )
        return {}
    try:
        if path.stat().st_size > 64 * 1024:
            raise ValueError("probe definition exceeds 65536 bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        diagnostics.append(PackageDiagnostic("INVALID_PROBE_DEFINITION", relative, str(exc)))
        return {}
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic("INVALID_PROBE_DEFINITION", relative, "definition must be an object")
        )
        return {}
    return value


def _parse_probe_config(
    invariants: dict[str, Any],
    probes: dict[str, Any],
    diagnostics: list[PackageDiagnostic],
) -> tuple[tuple[int, ...], int, tuple[str, ...], tuple[str, ...], int] | None:
    _check_fields(
        invariants,
        {
            "schema_version",
            "seeds",
            "tick_budget",
            "minimum_unique_history_hashes",
            "checks",
        },
        "tests/invariants.yaml",
        diagnostics,
    )
    _check_fields(
        probes,
        {"schema_version", "required_event_types", "forbidden_event_types"},
        "tests/probes.yaml",
        diagnostics,
    )
    for path, value in (
        ("tests/invariants.yaml", invariants),
        ("tests/probes.yaml", probes),
    ):
        if value.get("schema_version") != PROBE_SCHEMA_VERSION:
            diagnostics.append(
                PackageDiagnostic(
                    "UNSUPPORTED_PROBE_SCHEMA",
                    f"{path}.schema_version",
                    f"expected {PROBE_SCHEMA_VERSION}",
                )
            )
    raw_seeds = invariants.get("seeds")
    if (
        not isinstance(raw_seeds, list)
        or len(raw_seeds) < 8
        or len(raw_seeds) > MAX_PROBE_SEEDS
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in raw_seeds)
        or len(set(raw_seeds)) != len(raw_seeds)
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_PROBE_SEEDS",
                "tests/invariants.yaml.seeds",
                f"provide 8 to {MAX_PROBE_SEEDS} unique integer seeds",
            )
        )
        raw_seeds = []
    tick_budget = invariants.get("tick_budget")
    if (
        isinstance(tick_budget, bool)
        or not isinstance(tick_budget, int)
        or not 1 <= tick_budget <= MAX_PROBE_TICKS
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_TICK_BUDGET",
                "tests/invariants.yaml.tick_budget",
                f"tick_budget must be from 1 through {MAX_PROBE_TICKS}",
            )
        )
        tick_budget = 0
    checks = invariants.get("checks")
    required_checks = {
        "replay",
        "knowledge_sources",
        "map_integrity",
        "resources_non_negative",
        "dialogue_colocated",
    }
    if (
        not isinstance(checks, dict)
        or set(checks) != required_checks
        or any(value is not True for value in checks.values())
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_INVARIANT_CHECKS",
                "tests/invariants.yaml.checks",
                "all supported invariant checks must be explicitly true",
            )
        )
    minimum_unique = invariants.get("minimum_unique_history_hashes")
    if (
        isinstance(minimum_unique, bool)
        or not isinstance(minimum_unique, int)
        or minimum_unique < 2
        or (raw_seeds and minimum_unique > len(raw_seeds))
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_DIVERSITY_THRESHOLD",
                "tests/invariants.yaml.minimum_unique_history_hashes",
                "minimum must be at least 2 and no greater than seed count",
            )
        )
        minimum_unique = 0
    required = _event_names(
        probes.get("required_event_types"),
        "tests/probes.yaml.required_event_types",
        diagnostics,
    )
    forbidden = _event_names(
        probes.get("forbidden_event_types"),
        "tests/probes.yaml.forbidden_event_types",
        diagnostics,
    )
    if set(required) & set(forbidden):
        diagnostics.append(
            PackageDiagnostic(
                "CONTRADICTORY_PROBE_EVENTS",
                "tests/probes.yaml",
                "an event type cannot be both required and forbidden",
            )
        )
    if diagnostics:
        return None
    return tuple(raw_seeds), tick_budget, required, forbidden, minimum_unique


def _run_probe(
    compiled,
    seed: int,
    tick_budget: int,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> ProbeSeedResult:
    run = create_run(compiled, seed=seed)
    while run.state.tick < tick_budget:
        pending = get_pending_user_gate(run)
        if pending is not None:
            apply_gate_intervention(run, pending.gate_id)
            continue
        before = run.state.tick
        run_ticks(run, 1)
        if run.state.tick == before and get_pending_user_gate(run) is None:
            break
    names = [event.event_type.value for event in run.events]
    known_locations = {item.id for item in compiled.world.locations}
    replay_ok = run.replay() == run.state
    map_ok = (
        all(item.location_id in known_locations for item in run.state.characters.values())
        and all(
            move.origin_id in known_locations and move.destination_id in known_locations
            for event in run.events
            for move in event.delta.moves
        )
    )
    resources_ok = all(quantity >= 0 for quantity in run.state.resources.values()) and all(
        quantity >= 0
        for inventory in run.state.inventories.values()
        for quantity in inventory.values()
    )
    state = run.initial_state
    dialogue_ok = True
    for event in run.events:
        if event.event_type is EventType.DIALOGUE:
            speaker = event.data.get("speaker_id")
            listener = event.data.get("listener_id")
            location = event.data.get("location_id")
            dialogue_ok = dialogue_ok and (
                isinstance(speaker, str)
                and isinstance(listener, str)
                and speaker in state.characters
                and listener in state.characters
                and state.characters[speaker].location_id == location
                and state.characters[listener].location_id == location
            )
        state = state.apply(event.delta)
    knowledge_ok = True
    for character_id in run.state.characters:
        memories = run.memory.for_character(character_id, run.events)
        for tier, items in memories.items():
            for item in items:
                if item.seeded:
                    knowledge_ok = knowledge_ok and tier is MemoryTier.CORE and item.source_sequence is None
                else:
                    knowledge_ok = knowledge_ok and (
                        item.source_sequence is not None
                        and 0 <= item.source_sequence < len(run.events)
                        and character_id in run.events[item.source_sequence].observers
                    )
    required_ok = all(name in names for name in required)
    forbidden_ok = all(name not in names for name in forbidden)
    checks = (
        ("replay", replay_ok),
        ("knowledge_sources", knowledge_ok),
        ("map_integrity", map_ok),
        ("resources_non_negative", resources_ok),
        ("dialogue_colocated", dialogue_ok),
        ("required_events", required_ok),
        ("forbidden_events", forbidden_ok),
    )
    failures = tuple(name for name, passed in checks if not passed)
    return ProbeSeedResult(
        seed=seed,
        ok=not failures,
        ticks=run.state.tick,
        history_hash=run.history_hash(),
        event_counts=tuple(sorted(Counter(names).items())),
        checks=checks,
        failures=failures,
    )


def _event_names(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> tuple[str, ...]:
    allowed = {item.value for item in EventType}
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or item not in allowed for item in value)
        or len(set(value)) != len(value)
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_PROBE_EVENT_TYPES",
                path,
                "event types must be a unique array of known event names",
            )
        )
        return ()
    return tuple(value)


def _check_fields(
    value: dict[str, Any],
    allowed: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    for key in sorted(set(value) - allowed):
        diagnostics.append(
            PackageDiagnostic("UNKNOWN_PROBE_FIELD", f"{path}.{key}", f"field is not allowed: {key}")
        )
