"""Entity-oriented scene generation, perception, and adjudication."""

from engine.runtime.scene.capabilities import (
    BUILTIN_CAPABILITIES,
    CapabilityPack,
    capabilities_for_intent,
)
from engine.runtime.scene.generation import (
    DeterministicSceneGenerator,
    ensure_scene,
    scene_generation_context,
)
from engine.runtime.scene.lifecycle import (
    enter_scene,
    evolve_scene_time,
    travel_to_scene,
)
from engine.runtime.scene.executor import SceneTurnUsage, run_scene_turns
from engine.runtime.scene.perception import project_perception
from engine.runtime.scene.npc import resolve_ambient_npc_requests
from engine.runtime.scene.policies import (
    DeterministicIntentPolicy,
    DeterministicWorldAdjudicator,
)
from engine.runtime.scene.turns import commit_turn
from engine.runtime.scene.validation import (
    SceneValidationError,
    validate_adjudicated_turn,
    validate_intent,
    validate_scene_blueprint,
)

__all__ = [
    "SceneValidationError",
    "SceneTurnUsage",
    "BUILTIN_CAPABILITIES",
    "CapabilityPack",
    "capabilities_for_intent",
    "DeterministicSceneGenerator",
    "DeterministicIntentPolicy",
    "DeterministicWorldAdjudicator",
    "commit_turn",
    "ensure_scene",
    "enter_scene",
    "evolve_scene_time",
    "travel_to_scene",
    "project_perception",
    "run_scene_turns",
    "resolve_ambient_npc_requests",
    "scene_generation_context",
    "validate_adjudicated_turn",
    "validate_intent",
    "validate_scene_blueprint",
]
