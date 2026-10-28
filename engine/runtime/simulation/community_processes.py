"""Deterministic material cycles, including explicit external supply ledgers."""

from __future__ import annotations

from engine.contracts import ComponentPatch, ComponentValue, PatchOperation
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import Delta, EventType, QuantityDelta
from engine.runtime.simulation.community_events import commit, present


def settle_processes(run):
    settled = {
        e.data.get("process_id") for e in run.log.current_tick_events()
        if e.event_type is EventType.PROCESS_SETTLED
    }
    for process in sorted(run.compiled.community.processes, key=lambda p: p.process_id):
        if process.process_id in settled or run.state.tick % process.interval_ticks:
            continue
        quantities, patches = [], []
        device = run.state.entities.get(process.device_id)
        condition = device.components["attributes"]["condition"] if device else 100
        reserved = any(
            a.target_id in {process.device_id, *(key for key, _ in process.required_devices)}
            for a in community_projection(run).activities.values()
            if a.verb.value == "repair"
        )
        status, reason = "settled", ""
        if reserved:
            status, reason = "paused", "device is reserved for maintenance"
        elif any(
            run.state.entities[device_id].components["attributes"]["condition"] < threshold
            for device_id, threshold in process.required_devices
        ):
            status, reason = "blocked", "required service is unavailable"
        elif process.kind == "production" and condition <= 20:
            status, reason = "blocked", "device condition is too low for production"
        elif any(run.state.resources[item] < quantity for item, quantity in process.inputs):
            status, reason = "blocked", "insufficient inputs"
        elif process.kind == "production" and any(
            run.state.resources[item] + quantity - dict(process.inputs).get(item, 0) > process.capacity
            for item, quantity in process.outputs
        ):
            status, reason = "blocked", "output capacity exhausted"
        if status == "settled":
            quantities.extend(QuantityDelta("world", item, -amount) for item, amount in process.inputs)
            for item, amount in process.outputs:
                available = max(0, process.capacity - run.state.resources[item])
                produced = min(amount, available) if process.kind == "supply" else amount
                if produced:
                    quantities.append(QuantityDelta("world", item, produced))
            if device and process.wear and condition > 0:
                attributes = dict(device.components["attributes"])
                attributes["condition"] = max(0, condition - process.wear)
                patches.append(ComponentPatch(
                    PatchOperation.UPSERT_COMPONENT, process.device_id, device.version,
                    component=ComponentValue("attributes", attributes),
                ))
        ledger = tuple((q.item_id, q.amount) for q in quantities)
        commit(
            run, EventType.PROCESS_SETTLED, observers=present(run, process.location_id),
            delta=Delta(resources=tuple(quantities), entity_patches=tuple(patches)),
            data={"process_id": process.process_id, "kind": process.kind,
                  "status": status, "reason": reason, "location_id": process.location_id,
                  "ledger": ledger, "external_supply": process.kind == "supply",
                  "summary": f"{process.process_id}: {status}; {reason}",
                  **({"service_dependencies": process.required_devices,
                      "process_inputs": process.inputs, "process_outputs": process.outputs}
                     if process.required_devices else {})},
            commit_id=f"process:{process.process_id}:{run.state.tick}",
            target_id=process.device_id or process.location_id,
            sources=_causes(run, process) if process.required_devices else (),
        )


def _causes(run, process):
    devices = {key for key, _ in process.required_devices}
    materials = {key for key, _ in (*process.inputs, *process.outputs)}
    found, repairs_found, refs = set(), set(), []
    for event in reversed(run.events):
        touched = {p.entity_id for p in event.delta.entity_patches if p.entity_id in devices}
        touched.update(q.item_id for q in event.delta.resources if q.item_id in materials)
        if event.event_type is EventType.ACTIVITY_STARTED and event.data["activity"]["verb"] == "repair":
            target = event.data["activity"]["target_id"]
            if target in devices:
                touched.add(target)
        restored = (
            {p.entity_id for p in event.delta.entity_patches if p.entity_id in devices}
            if event.event_type is EventType.ACTIVITY_FINISHED and event.data.get("status") == "completed"
            else set()
        )
        if touched - found or restored - repairs_found:
            refs.append(f"event:{event.sequence}")
            found.update(touched)
            repairs_found.update(restored)
        if len(refs) >= 16 or found >= devices | materials and repairs_found >= devices:
            break
    return tuple(reversed(refs))
