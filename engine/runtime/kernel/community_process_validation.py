"""Narrow permission for system processes to cite actual material/service changes."""

from __future__ import annotations

from engine.contracts.ecology import validate_quantities
from engine.runtime.kernel.events import EventValidationError


def process_dependencies(event, state):
    raw = event.data.get("service_dependencies", ())
    inputs = event.data.get("process_inputs", ())
    outputs = event.data.get("process_outputs", ())
    try:
        devices = tuple(tuple(row) for row in raw)
        if not devices or len(devices) > 8 or len(dict(devices)) != len(devices):
            raise ValueError("service dependencies must be unique and bounded")
        for device_id, threshold in devices:
            if not isinstance(device_id, str) or device_id not in state.entities:
                raise ValueError("service dependency is not an existing device")
            condition = state.entities[device_id].components.get("attributes", {}).get("condition")
            if isinstance(condition, bool) or not isinstance(condition, int):
                raise ValueError("service dependency has no condition")
            if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 100:
                raise ValueError("invalid service threshold")
        inputs, outputs = tuple(tuple(row) for row in inputs), tuple(tuple(row) for row in outputs)
        validate_quantities(inputs)
        validate_quantities(outputs)
        if any(item not in state.resources for item, _ in (*inputs, *outputs)):
            raise ValueError("process materials are not registered")
        if {key for key, _ in devices} & {key for key, _ in (*inputs, *outputs)}:
            raise ValueError("a service device cannot be a consumed or produced material")
    except (ValueError, TypeError) as exc:
        raise EventValidationError("invalid process service dependencies") from exc
    return devices, inputs, outputs


def process_source_allowed(event, origin, state):
    if event.event_type.value != "process_settled" or event.actor_id is not None:
        return False
    devices, inputs, outputs = process_dependencies(event, state)
    device_ids = {key for key, _ in devices}
    materials = {key for key, _ in (*inputs, *outputs)}
    return (
        any(patch.entity_id in device_ids for patch in origin.delta.entity_patches)
        or any(change.item_id in materials for change in origin.delta.resources)
        or origin.event_type.value == "activity_started"
        and origin.data["activity"]["verb"] == "repair"
        and origin.data["activity"]["target_id"] in device_ids
    )
