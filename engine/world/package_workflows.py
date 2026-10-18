"""Closed registries and validators for typed package workflows."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from engine.catalogs import literary_skill_ids, literary_skill_stage, world_voice_ids
from engine.contracts import EDITORIAL_STAGE_GRAPH
from engine.world.package_spec import PackageDiagnostic, WorkflowDefinition, WorkflowStep
from engine.world.package_validation import _reject_unknown_fields

WORKFLOW_SCHEMA_VERSION = "world-workflow/v1alpha1"
PRESENTATION_WORKFLOW_SCHEMA_VERSION = "world-workflow/v1alpha3"
WORKFLOW_OPS = {
    "genesis": (
        "load_world",
        "load_locations",
        "load_characters",
        "load_resources",
        "load_passages",
    ),
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
}
WORKFLOW_POLICIES = {
    "genesis": frozenset(),
    "evolution": frozenset(
        {
            "need_decay",
            "action_budget",
            "opportunity_budget",
            "incident_budget",
            "memory_budget",
            "max_catchup_ticks",
            "hot_character_ids",
            "hot_location_ids",
            "phase_predicates",
        }
    ),
    "intervention": frozenset(
        {"avatar_offline_policy", "allow_incidents", "allow_gates", "allow_fate"}
    ),
    "presentation": frozenset(
        {
            "unpresented_event_threshold",
            "critical_event_threshold",
            "renderer",
            "audience_default",
            "episode",
            "style",
            "editorial_pipeline",
        }
    ),
}


def compile_workflow(
    expected_kind: str,
    ref: str,
    document: dict[str, Any],
    diagnostics: list[PackageDiagnostic],
) -> WorkflowDefinition:
    _reject_unknown_fields(
        document, {"schema_version", "kind", "steps", "policy"}, ref, diagnostics
    )
    schema_version = str(document.get("schema_version") or "")
    kind = str(document.get("kind") or "")
    expected_schema_version = (
        PRESENTATION_WORKFLOW_SCHEMA_VERSION
        if expected_kind == "presentation"
        else WORKFLOW_SCHEMA_VERSION
    )
    if schema_version != expected_schema_version:
        diagnostics.append(
            PackageDiagnostic(
                "UNSUPPORTED_WORKFLOW_SCHEMA",
                f"{ref}.schema_version",
                f"expected {expected_schema_version}",
            )
        )
    if kind != expected_kind:
        diagnostics.append(
            PackageDiagnostic(
                "WORKFLOW_KIND_MISMATCH",
                f"{ref}.kind",
                f"expected workflow kind {expected_kind}",
            )
        )
    raw_steps = document.get("steps")
    steps: list[WorkflowStep] = []
    if not isinstance(raw_steps, list):
        diagnostics.append(
            PackageDiagnostic("INVALID_WORKFLOW_STEPS", f"{ref}.steps", "steps must be an array")
        )
        raw_steps = []
    for index, raw_step in enumerate(raw_steps):
        path = f"{ref}.steps[{index}]"
        if not isinstance(raw_step, dict):
            diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_STEP", path, "step must be an object"))
            continue
        _reject_unknown_fields(raw_step, {"op"}, path, diagnostics)
        op = raw_step.get("op")
        if not isinstance(op, str) or op not in WORKFLOW_OPS[expected_kind]:
            diagnostics.append(
                PackageDiagnostic(
                    "UNKNOWN_WORKFLOW_OP",
                    f"{path}.op",
                    f"unsupported {expected_kind} operation: {op}",
                )
            )
            continue
        steps.append(WorkflowStep(op))
    expected_ops = WORKFLOW_OPS[expected_kind]
    selected_ops = tuple(step.op for step in steps)
    valid_orders = (
        (
            (
                "environment_update",
                "incident_scheduler",
                "actor_windows",
                "scheme_progress",
                "memory_consolidation",
                "phase_check",
            ),
            (
                "environment_update",
                "incident_scheduler",
                "scene_turns",
                "scheme_progress",
                "memory_consolidation",
                "phase_check",
            ),
        )
        if expected_kind == "evolution"
        else (expected_ops,)
    )
    if selected_ops not in valid_orders:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOW_ORDER",
                f"{ref}.steps",
                f"{expected_kind} operations must match one closed registered order",
            )
        )
    raw_policy = document.get("policy")
    if not isinstance(raw_policy, dict):
        diagnostics.append(
            PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{ref}.policy", "policy must be an object")
        )
        raw_policy = {}
    _reject_unknown_fields(
        raw_policy, set(WORKFLOW_POLICIES[expected_kind]), f"{ref}.policy", diagnostics
    )
    _validate_policy(expected_kind, raw_policy, ref, diagnostics)
    canonical = {
        "schema_version": schema_version,
        "kind": kind,
        "steps": [{"op": step.op} for step in steps],
        "policy": raw_policy,
    }
    return WorkflowDefinition(
        schema_version=schema_version,
        kind=kind,
        steps=tuple(steps),
        policy=tuple(sorted(raw_policy.items())),
        content_hash=hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        ref=ref,
    )


def _validate_policy(
    kind: str,
    policy: dict[str, Any],
    ref: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    path = f"{ref}.policy"
    if kind == "genesis":
        return
    if kind == "evolution":
        decay = policy.get("need_decay")
        required = {"fatigue", "social", "resources", "knowledge", "exploration"}
        if not isinstance(decay, dict):
            diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.need_decay", "need_decay must be an object"))
        else:
            _reject_unknown_fields(decay, required, f"{path}.need_decay", diagnostics)
            if set(decay) != required or any(not _non_negative_int(value) for value in decay.values()):
                diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.need_decay", "all five need decay values must be non-negative integers"))
        for field in ("action_budget", "opportunity_budget", "incident_budget", "memory_budget", "max_catchup_ticks"):
            if not _non_negative_int(policy.get(field)):
                diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.{field}", f"{field} must be a non-negative integer"))
        for field in ("hot_character_ids", "hot_location_ids"):
            value = policy.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.{field}", f"{field} must be an array of strings"))
        _validate_phase_predicates(
            policy.get("phase_predicates"), f"{path}.phase_predicates", diagnostics
        )
    elif kind == "intervention":
        if policy.get("avatar_offline_policy") != "pause":
            diagnostics.append(PackageDiagnostic("UNKNOWN_WORKFLOW_POLICY", f"{path}.avatar_offline_policy", "only avatar_offline_policy=pause is supported"))
        for field in ("allow_incidents", "allow_gates", "allow_fate"):
            if not isinstance(policy.get(field), bool):
                diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.{field}", f"{field} must be boolean"))
    elif kind == "presentation":
        for field in ("unpresented_event_threshold", "critical_event_threshold"):
            value = policy.get(field)
            if not _non_negative_int(value) or value < 1:
                diagnostics.append(PackageDiagnostic("INVALID_WORKFLOW_POLICY", f"{path}.{field}", f"{field} must be a positive integer"))
        if policy.get("renderer") not in {
            "literary_skill",
            "structured_literary",
            "deterministic",
        }:
            diagnostics.append(PackageDiagnostic("UNKNOWN_WORKFLOW_POLICY", f"{path}.renderer", "renderer is not registered"))
        if policy.get("audience_default") not in {"omniscient", "observer"}:
            diagnostics.append(PackageDiagnostic("UNKNOWN_WORKFLOW_POLICY", f"{path}.audience_default", "audience_default is not registered"))
        if policy.get("episode") is not None:
            _validate_episode_policy(
                policy.get("episode"), f"{path}.episode", diagnostics
            )
        if policy.get("style") is not None:
            _validate_style_policy(
                policy.get("style"), f"{path}.style", diagnostics
            )
        _validate_editorial_pipeline(
            policy.get("editorial_pipeline"),
            f"{path}.editorial_pipeline",
            diagnostics,
        )


def _validate_editorial_pipeline(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    if value is None:
        return
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EDITORIAL_PIPELINE",
                path,
                "editorial pipeline must be an array of registered skill ids",
            )
        )
        return
    if any(item not in literary_skill_ids() for item in value):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EDITORIAL_PIPELINE",
                path,
                "editorial pipeline contains an unknown skill",
            )
        )
        return
    if tuple(literary_skill_stage(item) for item in value) != (
        EDITORIAL_STAGE_GRAPH
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EDITORIAL_PIPELINE",
                path,
                "editorial skills must fill the four registered stages in order",
            )
        )


def _validate_episode_policy(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    fields = {
        "max_events",
        "max_world_time_span",
        "min_narrative_events",
        "max_repeated_action",
        "min_arc_events",
    }
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOW_POLICY", path, "episode must be an object"
            )
        )
        return
    _reject_unknown_fields(value, fields, path, diagnostics)
    if set(value) != fields:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOW_POLICY",
                path,
                "episode policy requires all typed fields",
            )
        )
    for field in fields:
        item = value.get(field)
        if not _non_negative_int(item) or item < 1:
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_WORKFLOW_POLICY",
                    f"{path}.{field}",
                    f"{field} must be a positive integer",
                )
            )


def _validate_style_policy(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    fields = {
        "skill_id",
        "voice_id",
        "language",
        "point_of_view",
        "narrative_distance",
        "register",
        "rhythm",
        "dialogue_density",
        "imagery_domains",
        "forbidden_phrases",
        "scene_shape",
        "exposition",
        "revision_level",
    }
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOW_POLICY", path, "style must be an object"
            )
        )
        return
    _reject_unknown_fields(value, fields, path, diagnostics)
    if set(value) != fields:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_WORKFLOW_POLICY",
                path,
                "style policy requires all typed fields",
            )
        )
    enums = {
        "language": {"zh-CN"},
        "point_of_view": {"omniscient", "limited", "observer"},
        "narrative_distance": {"intimate", "close", "medium", "distant"},
        "register": {
            "contemporary",
            "literary",
            "vernacular",
            "classical-vernacular",
        },
        "rhythm": {"restrained", "balanced", "brisk"},
        "dialogue_density": {"sparse", "balanced", "rich"},
        "scene_shape": {"turn-centered"},
        "exposition": {"implicit", "direct"},
        "revision_level": {"developmental-and-line"},
    }
    skill_id = value.get("skill_id")
    if skill_id not in literary_skill_ids():
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_LITERARY_SKILL",
                f"{path}.skill_id",
                f"literary skill is not registered: {skill_id}",
            )
        )
    voice_id = value.get("voice_id")
    if voice_id not in world_voice_ids():
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_WORLD_VOICE",
                f"{path}.voice_id",
                f"world voice is not registered: {voice_id}",
            )
        )
    for field, allowed in enums.items():
        if value.get(field) not in allowed:
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_WORKFLOW_POLICY",
                    f"{path}.{field}",
                    f"{field} is not a registered typed value",
                )
            )
    for field in ("imagery_domains", "forbidden_phrases"):
        items = value.get(field)
        if (
            not isinstance(items, list)
            or any(not isinstance(item, str) or not item.strip() for item in items)
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_WORKFLOW_POLICY",
                    f"{path}.{field}",
                    f"{field} must be an array of non-empty strings",
                )
            )


def _non_negative_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _validate_phase_predicates(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    if not isinstance(value, list):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_PHASE_PREDICATES", path, "phase_predicates must be an array"
            )
        )
        return
    seen: set[str] = set()
    for index, phase in enumerate(value):
        phase_path = f"{path}[{index}]"
        if not isinstance(phase, dict):
            diagnostics.append(
                PackageDiagnostic("INVALID_PHASE_PREDICATE", phase_path, "phase must be an object")
            )
            continue
        _reject_unknown_fields(
            phase, {"id", "target", "predicates", "unresolved_items"}, phase_path, diagnostics
        )
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not phase_id.strip() or phase_id in seen:
            diagnostics.append(
                PackageDiagnostic("INVALID_PHASE_PREDICATE", f"{phase_path}.id", "phase id must be unique and non-empty")
            )
        else:
            seen.add(phase_id)
        if "target" not in phase:
            diagnostics.append(
                PackageDiagnostic("INVALID_PHASE_PREDICATE", f"{phase_path}.target", "target is required")
            )
        unresolved = phase.get("unresolved_items")
        if not isinstance(unresolved, list) or any(
            not isinstance(item, str) or not item.strip() for item in unresolved
        ):
            diagnostics.append(
                PackageDiagnostic("INVALID_PHASE_PREDICATE", f"{phase_path}.unresolved_items", "unresolved_items must be an array of strings")
            )
        predicates = phase.get("predicates")
        if not isinstance(predicates, list) or not predicates:
            diagnostics.append(
                PackageDiagnostic("INVALID_PHASE_PREDICATE", f"{phase_path}.predicates", "predicates must be a non-empty array")
            )
            continue
        for predicate_index, predicate in enumerate(predicates):
            _validate_phase_condition(
                predicate, f"{phase_path}.predicates[{predicate_index}]", diagnostics
            )


def _validate_phase_condition(
    value: Any, path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    if not isinstance(value, dict):
        diagnostics.append(PackageDiagnostic("INVALID_PHASE_CONDITION", path, "predicate must be an object"))
        return
    kind = value.get("type")
    expected = {
        "tick": {"type", "minimum"},
        "resource": {"type", "resource_id", "minimum"},
        "relationship": {"type", "source_id", "target_id", "minimum"},
    }.get(kind)
    if expected is None or set(value) != expected:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_PHASE_CONDITION",
                path,
                "predicate must be typed tick, resource, or relationship",
            )
        )
        return
    if not _non_negative_int(value.get("minimum")):
        diagnostics.append(
            PackageDiagnostic("INVALID_PHASE_CONDITION", f"{path}.minimum", "minimum must be a non-negative integer")
        )
