"""Serialization helpers for coarse simulation settlements."""

from __future__ import annotations

from typing import Any

from engine.runtime.kernel.events import Delta


def delta_summary(delta: Delta) -> dict[str, Any]:
    return {
        "needs": tuple(
            {"character_id": item.character_id, "need": item.need, "amount": item.amount}
            for item in delta.needs
        ),
        "resources": tuple(
            {"owner_id": item.owner_id, "item_id": item.item_id, "amount": item.amount}
            for item in delta.resources
        ),
        "inventories": tuple(
            {"owner_id": item.owner_id, "item_id": item.item_id, "amount": item.amount}
            for item in delta.inventories
        ),
        "knowledge": tuple(
            {
                "character_id": item.character_id,
                "fact_id": item.fact_id,
                "source_id": item.source_id,
            }
            for item in delta.knowledge
        ),
        "disclosures": tuple(
            {
                "speaker_id": item.speaker_id,
                "listener_id": item.listener_id,
                "fact_id": item.fact_id,
            }
            for item in delta.disclosures
        ),
        "plans": tuple(
            {"character_id": item.character_id, "plan": item.plan}
            for item in delta.plans
        ),
        "advance_time": delta.advance_time,
        "advance_tick": delta.advance_tick,
    }
