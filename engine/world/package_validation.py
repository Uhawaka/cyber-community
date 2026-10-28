"""Schema, rule, entity, and authoring-policy validation."""

from __future__ import annotations

from typing import Any

from engine.world.package_spec import PackageCharacter, PackageDiagnostic, PackageLocation, PackagePassage, PackageResource

MAX_LOCATIONS = 256
MAX_CHARACTERS = 64
MAX_RESOURCES = 512
MAX_PASSAGES = 1_024
MAX_RULES = 256
MAX_MEMORY_SEEDS = 64
MAX_MEMORY_SUMMARY_LENGTH = 2_000
FORBIDDEN_PREARRANGEMENT_FIELDS = frozenset(
    {
        "blocking",
        "character_arc",
        "character_arcs",
        "conflict",
        "dialogue",
        "dialogues",
        "obligation",
        "obligations",
        "outcome",
        "outcomes",
        "script",
        "stakes",
    }
)


def _unique_ids(
    ids: list[str], path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    seen: set[str] = set()
    for index, item_id in enumerate(ids):
        if not item_id:
            diagnostics.append(
                PackageDiagnostic("EMPTY_ID", f"{path}[{index}].id", "id is required")
            )
        elif item_id in seen:
            diagnostics.append(
                PackageDiagnostic("DUPLICATE_ID", f"{path}[{index}].id", item_id)
            )
        seen.add(item_id)


def _validate_structured_rules(
    rules: list[dict[str, Any]],
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    """Validate the deliberately small Incident/UserGate authoring surface."""

    seen: set[str] = set()
    for index, rule in enumerate(rules):
        path = f"world.yaml.rules[{index}]"
        rule_type = rule.get("type")
        if rule_type not in {"incident", "user_gate", "fate_intervention"}:
            _reject_unknown_rule_fields(
                rule, {"id", "statement"}, path, diagnostics
            )
            if (
                not isinstance(rule.get("id"), str)
                or not rule["id"].strip()
                or not isinstance(rule.get("statement"), str)
                or not rule["statement"].strip()
            ):
                diagnostics.append(
                    PackageDiagnostic(
                        "INVALID_RULE",
                        path,
                        "declarative rule requires non-empty id and statement",
                    )
                )
            continue
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            diagnostics.append(PackageDiagnostic("INVALID_RULE", f"{path}.id", "structured rule id is required"))
        elif rule_id in seen:
            diagnostics.append(PackageDiagnostic("DUPLICATE_RULE_ID", f"{path}.id", rule_id))
        else:
            seen.add(rule_id)
        if rule_type == "incident" and _is_after_trigger(rule.get("trigger")):
            _validate_after_trigger(
                rule.get("trigger"), f"{path}.trigger", resource_ids, diagnostics
            )
        elif rule_type != "fate_intervention":
            _validate_trigger(rule.get("trigger"), f"{path}.trigger", diagnostics)
        _reject_prescribed_reactions(rule, path, diagnostics)
        if rule_type == "incident":
            _validate_incident(rule, path, resource_ids, diagnostics)
        elif rule_type == "user_gate":
            _validate_user_gate(rule, path, resource_ids, diagnostics)
        else:
            _validate_fate_intervention(rule, path, resource_ids, diagnostics)


def _validate_rule_location(
    rule: dict[str, Any], path: str, diagnostics: list[PackageDiagnostic]
) -> None:
    location_id = rule.get("location_id")
    if location_id is None:
        return
    if not isinstance(location_id, str) or not location_id.strip():
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_RULE_LOCATION",
                f"{path}.location_id",
                "location_id must be a non-empty location id",
            )
        )


def _is_after_trigger(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"after"}


def _validate_after_trigger(
    value: Any,
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    after = value.get("after") if isinstance(value, dict) else None
    if (
        not isinstance(after, dict)
        or set(after) != {"action", "entity_id"}
        or after.get("action") not in {"inspect", "work", "take"}
        or not isinstance(after.get("entity_id"), str)
        or after["entity_id"] not in resource_ids
    ):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_RULE_TRIGGER",
                path,
                "after trigger requires a logged inspect, work, or take of a known resource",
            )
        )


def _validate_trigger(value: Any, path: str, diagnostics: list[PackageDiagnostic]) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"tick"}
        or isinstance(value.get("tick"), bool)
        or not isinstance(value.get("tick"), int)
        or value["tick"] < 1
    ):
        diagnostics.append(PackageDiagnostic("INVALID_RULE_TRIGGER", path, "trigger must be {'tick': positive integer}"))


def _validate_incident(
    rule: dict[str, Any],
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    allowed = {"id", "type", "trigger", "summary", "cost", "effects", "location_id"}
    _reject_unknown_rule_fields(rule, allowed, path, diagnostics)
    if not isinstance(rule.get("summary"), str) or not rule["summary"].strip():
        diagnostics.append(PackageDiagnostic("INVALID_INCIDENT", f"{path}.summary", "incident summary is required"))
    cost = rule.get("cost", 1)
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
        diagnostics.append(PackageDiagnostic("INVALID_INCIDENT", f"{path}.cost", "incident cost must be a positive integer"))
    _validate_effects(rule.get("effects"), f"{path}.effects", resource_ids, diagnostics)
    _validate_rule_location(rule, path, diagnostics)


def _validate_user_gate(
    rule: dict[str, Any],
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    allowed = {
        "id",
        "type",
        "trigger",
        "prompt",
        "deadline_ticks",
        "choices",
        "location_id",
    }
    _reject_unknown_rule_fields(rule, allowed, path, diagnostics)
    if not isinstance(rule.get("prompt"), str) or not rule["prompt"].strip():
        diagnostics.append(PackageDiagnostic("INVALID_USER_GATE", f"{path}.prompt", "gate prompt is required"))
    _validate_rule_location(rule, path, diagnostics)
    deadline = rule.get("deadline_ticks", 1)
    if isinstance(deadline, bool) or not isinstance(deadline, int) or deadline < 0:
        diagnostics.append(PackageDiagnostic("INVALID_USER_GATE", f"{path}.deadline_ticks", "deadline_ticks must be a non-negative integer"))
    choices = rule.get("choices")
    if not isinstance(choices, list) or not choices:
        diagnostics.append(PackageDiagnostic("INVALID_USER_GATE", f"{path}.choices", "gate choices must be a non-empty array"))
        return
    choice_ids: set[str] = set()
    for index, choice in enumerate(choices):
        choice_path = f"{path}.choices[{index}]"
        if not isinstance(choice, dict):
            diagnostics.append(PackageDiagnostic("INVALID_USER_GATE_CHOICE", choice_path, "choice must be an object"))
            continue
        _reject_unknown_rule_fields(
            choice,
            {"id", "label", "observation", "effects", "costs"},
            choice_path,
            diagnostics,
        )
        choice_id = choice.get("id")
        if not isinstance(choice_id, str) or not choice_id.strip() or choice_id == "abstain":
            diagnostics.append(PackageDiagnostic("INVALID_USER_GATE_CHOICE", f"{choice_path}.id", "choice id is required and cannot be abstain"))
        observation = choice.get("observation")
        if observation is not None and (
            not isinstance(observation, str) or not observation.strip()
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_USER_GATE_CHOICE",
                    f"{choice_path}.observation",
                    "observation must be a non-empty string",
                )
            )
        elif choice_id in choice_ids:
            diagnostics.append(PackageDiagnostic("DUPLICATE_CHOICE_ID", f"{choice_path}.id", choice_id))
        else:
            choice_ids.add(choice_id)
        if not isinstance(choice.get("label"), str) or not choice["label"].strip():
            diagnostics.append(PackageDiagnostic("INVALID_USER_GATE_CHOICE", f"{choice_path}.label", "choice label is required"))
        _validate_effects(
            choice.get("effects", []),
            f"{choice_path}.effects",
            resource_ids,
            diagnostics,
            allow_empty=True,
        )
        _validate_effects(choice.get("costs", []), f"{choice_path}.costs", resource_ids, diagnostics, costs=True)


def _validate_fate_intervention(
    rule: dict[str, Any],
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    _reject_unknown_rule_fields(
        rule,
        {
            "id", "type", "summary", "conditions", "once", "cooldown_ticks",
            "effects", "costs",
        },
        path,
        diagnostics,
    )
    if not isinstance(rule.get("summary"), str) or not rule["summary"].strip():
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_INTERVENTION",
                f"{path}.summary",
                "fate intervention summary is required",
            )
        )
    once = rule.get("once", False)
    cooldown = rule.get("cooldown_ticks", 0)
    if not isinstance(once, bool):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_INTERVENTION", f"{path}.once", "once must be boolean"
            )
        )
    if isinstance(cooldown, bool) or not isinstance(cooldown, int) or cooldown < 0:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_INTERVENTION",
                f"{path}.cooldown_ticks",
                "cooldown_ticks must be a non-negative integer",
            )
        )
    if once is True and cooldown:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_INTERVENTION",
                path,
                "a one-time intervention cannot also declare a cooldown",
            )
        )
    _validate_fate_conditions(
        rule.get("conditions", {}),
        f"{path}.conditions",
        resource_ids,
        diagnostics,
    )
    _validate_effects(
        rule.get("effects"), f"{path}.effects", resource_ids, diagnostics
    )
    _validate_effects(
        rule.get("costs", []),
        f"{path}.costs",
        resource_ids,
        diagnostics,
        costs=True,
    )


def _validate_fate_conditions(
    value: Any,
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
) -> None:
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_CONDITIONS", path, "conditions must be an object"
            )
        )
        return
    _reject_unknown_rule_fields(
        value, {"tick_gte", "tick_lte", "resources"}, path, diagnostics
    )
    for name in ("tick_gte", "tick_lte"):
        tick = value.get(name)
        if tick is not None and (
            isinstance(tick, bool) or not isinstance(tick, int) or tick < 0
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_FATE_CONDITIONS",
                    f"{path}.{name}",
                    "tick bound must be a non-negative integer",
                )
            )
    resources = value.get("resources", [])
    if not isinstance(resources, list):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_FATE_CONDITIONS",
                f"{path}.resources",
                "resources must be an array",
            )
        )
        return
    for index, condition in enumerate(resources):
        item_path = f"{path}.resources[{index}]"
        if (
            not isinstance(condition, dict)
            or set(condition) != {"resource_id", "minimum"}
            or condition.get("resource_id") not in resource_ids
            or isinstance(condition.get("minimum"), bool)
            or not isinstance(condition.get("minimum"), int)
            or condition["minimum"] < 0
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_FATE_CONDITION",
                    item_path,
                    "resource condition requires a known resource_id and non-negative minimum",
                )
            )


def _validate_effects(
    value: Any,
    path: str,
    resource_ids: set[str],
    diagnostics: list[PackageDiagnostic],
    *,
    costs: bool = False,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, list) or (not costs and not allow_empty and not value):
        diagnostics.append(PackageDiagnostic("INVALID_RULE_EFFECTS", path, "effects must be a non-empty array" if not costs else "costs must be an array"))
        return
    for index, effect in enumerate(value):
        effect_path = f"{path}[{index}]"
        if not isinstance(effect, dict):
            diagnostics.append(PackageDiagnostic("INVALID_RULE_EFFECT", effect_path, "effect must be an object"))
            continue
        effect_type = effect.get("type")
        expected = {"type", "resource_id", "amount"} if effect_type == "resource" else {"type", "need", "amount"}
        if effect_type not in {"resource", "global_need"} or set(effect) != expected:
            diagnostics.append(PackageDiagnostic("INVALID_RULE_EFFECT", effect_path, "effect must be resource or global_need with only its structured fields"))
            continue
        amount = effect.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or (costs and amount < 0):
            diagnostics.append(PackageDiagnostic("INVALID_RULE_EFFECT", f"{effect_path}.amount", "amount must be an integer" + (" at least zero" if costs else "")))
        if effect_type == "resource" and effect.get("resource_id") not in resource_ids:
            diagnostics.append(PackageDiagnostic("UNKNOWN_RESOURCE", f"{effect_path}.resource_id", str(effect.get("resource_id"))))
        if effect_type == "global_need" and (not isinstance(effect.get("need"), str) or not effect["need"].strip()):
            diagnostics.append(PackageDiagnostic("INVALID_RULE_EFFECT", f"{effect_path}.need", "need is required"))


def _reject_unknown_rule_fields(
    value: dict[str, Any],
    allowed: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    for key in sorted(set(value) - allowed):
        diagnostics.append(PackageDiagnostic("UNKNOWN_RULE_FIELD", f"{path}.{key}", f"field is not allowed for this structured rule: {key}"))


def _reject_prescribed_reactions(value: Any, path: str, diagnostics: list[PackageDiagnostic]) -> None:
    prohibited = {"dialogue", "utterance", "line", "reaction", "response", "character_id", "actor_id"}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in prohibited:
                diagnostics.append(PackageDiagnostic("PRESCRIBED_CHARACTER_RESPONSE", child_path, "structured rules cannot prescribe dialogue or character responses"))
            _reject_prescribed_reactions(child, child_path, diagnostics)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_prescribed_reactions(child, f"{path}[{index}]", diagnostics)


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    for key in sorted(set(value) - allowed):
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_FIELD", f"{path}.{key}", f"field is not allowed: {key}"
            )
        )


def _validate_memory_seed(
    memory: list[dict[str, Any]],
    character_id: str,
    diagnostics: list[PackageDiagnostic],
) -> None:
    path = f"characters.{character_id}.memory.seed.json"
    if len(memory) > MAX_MEMORY_SEEDS:
        diagnostics.append(
            PackageDiagnostic(
                "LIMIT_EXCEEDED",
                path,
                f"at most {MAX_MEMORY_SEEDS} memory seeds are allowed",
            )
        )
    allowed = {"kind", "summary", "confidence", "visibility", "source"}
    for index, item in enumerate(memory):
        item_path = f"{path}[{index}]"
        _reject_unknown_fields(item, allowed, item_path, diagnostics)
        summary = item.get("summary")
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or len(summary) > MAX_MEMORY_SUMMARY_LENGTH
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_MEMORY_SEED",
                    f"{item_path}.summary",
                    f"summary must be non-empty and at most {MAX_MEMORY_SUMMARY_LENGTH} characters",
                )
            )
        confidence = item.get("confidence", 0.5)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            diagnostics.append(
                PackageDiagnostic(
                    "INVALID_MEMORY_SEED",
                    f"{item_path}.confidence",
                    "confidence must be a number from 0 through 1",
                )
            )

