"""Typed execution for the four closed world-package workflows."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from engine.runtime.kernel.events import reset_workflow_provenance, set_workflow_provenance
from engine.runtime.kernel.state import CharacterState, WorldState
from engine.world.package_spec import CompiledWorld, WorkflowDefinition, WorkflowStep


@dataclass(frozen=True)
class StepResult:
    value: Any = None
    stop: bool = False


@dataclass
class TickContext:
    operations: dict[str, Callable[[], StepResult]]


@dataclass
class GenesisContext:
    compiled: CompiledWorld
    seed: int
    parts: dict[str, Any] = field(default_factory=dict)


@dataclass
class InterventionContext:
    operations: dict[str, Callable[[], Any]]


@dataclass
class PresentationContext:
    operations: dict[str, Callable[[], Any]]


StepHandler = Callable[[Any, WorkflowStep], StepResult]


def _operation_handler(context: Any, step: WorkflowStep) -> StepResult:
    operation = context.operations.get(step.op)
    if operation is None:
        raise ValueError(f"no runtime operation for workflow step: {step.op}")
    result = operation()
    return result if isinstance(result, StepResult) else StepResult(result)


def _load_world(context: GenesisContext, _step: WorkflowStep) -> StepResult:
    world = context.compiled.world
    context.parts.update(
        world_id=world.world_id,
        world_hash=context.compiled.content_hash,
        seed=int(context.seed),
        tick=0,
        world_time=0,
    )
    return StepResult()


def _load_locations(context: GenesisContext, _step: WorkflowStep) -> StepResult:
    context.parts["location_ids"] = tuple(
        location.id for location in context.compiled.world.locations
    )
    return StepResult()


def _load_characters(context: GenesisContext, _step: WorkflowStep) -> StepResult:
    characters: dict[str, CharacterState] = {}
    for character in context.compiled.world.characters:
        profile = dict(character.profile)
        needs = {
            "fatigue": 8,
            "social": 16,
            "resources": 28,
            "knowledge": 18,
            "exploration": 12,
        }
        authored = profile.get("needs", {})
        if isinstance(authored, dict):
            needs.update(
                {
                    str(key): min(100, max(0, int(value)))
                    for key, value in authored.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            )
        goals = profile.get("goals", ())
        plan = tuple(str(item) for item in goals[:3]) if isinstance(goals, list) else ()
        characters[character.id] = CharacterState(
            location_id=character.location_id,
            needs=needs,
            short_plan=(),
            goals=plan,
        )
    context.parts["characters"] = characters
    context.parts["inventories"] = {key: {} for key in characters}
    context.parts["knowledge"] = {
        character.id: tuple(
            f"{character.id}:memory:{index}"
            for index, item in enumerate(character.memory_seed)
            if item.get("kind") in {"observation", "experience"}
            and item.get("visibility", "public") == "public"
        )
        for character in context.compiled.world.characters
    }
    context.parts["facts"] = {
        **{
            f"{character.id}:memory:{index}": str(item["summary"])
            for character in context.compiled.world.characters
            for index, item in enumerate(character.memory_seed)
            if isinstance(item.get("summary"), str)
        },
        **{
            f"resource:{resource.id}:inspection": str(
                dict(resource.properties)["inspection"]
            )
            for resource in context.compiled.world.resources
            if isinstance(dict(resource.properties).get("inspection"), str)
        },
        **{
            f"incident:{rule['id']}": str(rule["summary"])
            for rule in context.compiled.world.rules
            if rule.get("type") == "incident"
            and isinstance(rule.get("id"), str)
            and isinstance(rule.get("summary"), str)
        },
    }
    context.parts["disclosures"] = {key: {} for key in characters}
    context.parts["relationships"] = {
        key: {other: 0 for other in characters if other != key} for key in characters
    }
    return StepResult()


def _load_resources(context: GenesisContext, _step: WorkflowStep) -> StepResult:
    context.parts["resources"] = {
        item.id: item.quantity for item in context.compiled.world.resources
    }
    return StepResult()


def _load_passages(context: GenesisContext, _step: WorkflowStep) -> StepResult:
    # Passage validity is compiled; touching it here makes genesis composition explicit.
    tuple(context.compiled.world.passages)
    return StepResult()


STEP_HANDLERS: dict[tuple[str, str], StepHandler] = {
    **{
        ("genesis", op): handler
        for op, handler in {
            "load_world": _load_world,
            "load_locations": _load_locations,
            "load_characters": _load_characters,
            "load_resources": _load_resources,
            "load_passages": _load_passages,
        }.items()
    },
    **{
        (kind, op): _operation_handler
        for kind, operations in {
            "evolution": (
                "environment_update",
                "incident_scheduler",
                "actor_windows",
                "scene_turns",
                "scheme_progress",
                "memory_consolidation",
                "phase_check",
            ),
            "intervention": ("incident", "user_gate", "fate"),
            "presentation": (
                "source_filter",
                "curate",
                "plan",
                "render",
                "validate",
                "publish",
            ),
        }.items()
        for op in operations
    },
}


@contextmanager
def workflow_step_scope(kind: str, step: str) -> Iterator[None]:
    token = set_workflow_provenance(kind, step)
    try:
        yield
    finally:
        reset_workflow_provenance(token)


def execute_workflow(
    definition: WorkflowDefinition, context: Any
) -> tuple[str, ...]:
    executed: list[str] = []
    for step in definition.steps:
        handler = STEP_HANDLERS.get((definition.kind, step.op))
        if handler is None:
            raise ValueError(
                f"unknown runtime workflow handler: {definition.kind}.{step.op}"
            )
        with workflow_step_scope(definition.kind, step.op):
            result = handler(context, step)
        executed.append(step.op)
        if result.stop:
            break
    return tuple(executed)


def dispatch_workflow_step(
    definition: WorkflowDefinition, step_name: str, context: Any
) -> Any:
    step = next((item for item in definition.steps if item.op == step_name), None)
    if step is None:
        raise ValueError(f"workflow step is not compiled: {definition.kind}.{step_name}")
    handler = STEP_HANDLERS.get((definition.kind, step.op))
    if handler is None:
        raise ValueError(f"unknown runtime workflow handler: {definition.kind}.{step.op}")
    with workflow_step_scope(definition.kind, step.op):
        return handler(context, step).value


def build_initial_state(compiled: CompiledWorld, seed: int) -> WorldState:
    context = GenesisContext(compiled, seed)
    execute_workflow(compiled.workflow.genesis, context)
    try:
        return WorldState(**context.parts)
    except TypeError as exc:
        raise ValueError("genesis workflow did not construct a complete state") from exc
