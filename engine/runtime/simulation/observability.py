"""Tick reporting and causal event explanations."""

from __future__ import annotations

from dataclasses import dataclass

from engine.runtime.kernel.events import EventType
from engine.runtime.simulation.run import AutonomousRun

@dataclass(frozen=True)
class TickReport:
    from_tick: int
    to_tick: int
    requested_ticks: int
    executed_ticks: int
    detailed_event_count: int
    coarse_event_count: int
    character_action_count: int
    incident_count: int
    gate_count: int
    budget_exhausted: bool
    truncated_ticks: int = 0
    coarse_ticks: int = 0
    action_budget: int = 0
    actions_used: int = 0
    action_budget_exhausted: bool = False
    opportunity_budget: int = 0
    opportunities_evaluated: int = 0
    opportunity_budget_exhausted: bool = False
    incident_budget: int = 0
    incidents_used: int = 0
    incident_budget_exhausted: bool = False
    memory_budget: int = 0
    memory_updates_used: int = 0
    memory_budget_exhausted: bool = False
    executed_workflow_steps: tuple[str, ...] = ()


@dataclass
class _TickUsage:
    action_budget: int = 0
    actions_used: int = 0
    action_exhausted: bool = False
    opportunity_budget: int = 0
    opportunities_evaluated: int = 0
    opportunity_exhausted: bool = False
    incident_budget: int = 0
    incidents_used: int = 0
    incident_exhausted: bool = False
    memory_budget: int = 0
    memory_updates_used: int = 0
    memory_exhausted: bool = False
    executed_workflow_steps: tuple[str, ...] = ()

    def add(self, other: "_TickUsage") -> None:
        for name in (
            "action_budget",
            "actions_used",
            "opportunity_budget",
            "opportunities_evaluated",
            "incident_budget",
            "incidents_used",
            "memory_budget",
            "memory_updates_used",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.action_exhausted |= other.action_exhausted
        self.opportunity_exhausted |= other.opportunity_exhausted
        self.incident_exhausted |= other.incident_exhausted
        self.memory_exhausted |= other.memory_exhausted
        self.executed_workflow_steps += other.executed_workflow_steps

    @classmethod
    def from_report(cls, report: TickReport) -> "_TickUsage":
        return cls(
            action_budget=report.action_budget,
            actions_used=report.actions_used,
            action_exhausted=report.action_budget_exhausted,
            opportunity_budget=report.opportunity_budget,
            opportunities_evaluated=report.opportunities_evaluated,
            opportunity_exhausted=report.opportunity_budget_exhausted,
            incident_budget=report.incident_budget,
            incidents_used=report.incidents_used,
            incident_exhausted=report.incident_budget_exhausted,
            memory_budget=report.memory_budget,
            memory_updates_used=report.memory_updates_used,
            memory_exhausted=report.memory_budget_exhausted,
            executed_workflow_steps=report.executed_workflow_steps,
        )


@dataclass(frozen=True)
class CausalTrace:
    sequence: int
    event_type: EventType
    opportunity_id: str | None
    pre_state_hash: str | None
    rule_basis: tuple[str, ...]
    target_entity_id: str | None
    seed: int
    deterministic_cursor: int | None
    prior_movement_sequences: tuple[int, ...]
    colocation_basis: tuple[str, ...]
    workflow_kind: str | None
    workflow_step: str | None


def _tick_report(
    run: AutonomousRun,
    start_tick: int,
    start_sequence: int,
    requested: int,
    executed: int,
    usage: _TickUsage,
    *,
    truncated_ticks: int = 0,
    coarse_ticks: int = 0,
) -> TickReport:
    events = run.events[start_sequence:]
    coarse = sum(event.event_type is EventType.COARSE_TICK_SUMMARY for event in events)
    action_count = sum(len(event.delta.actions) for event in events)
    incident_types = {EventType.INCIDENT_OCCURRED, EventType.INCIDENT_RESTED}
    gate_types = {EventType.GATE_OPENED, EventType.GATE_WAITED}
    return TickReport(
        from_tick=start_tick,
        to_tick=run.state.tick,
        requested_ticks=requested,
        executed_ticks=executed,
        detailed_event_count=len(events) - coarse,
        coarse_event_count=coarse,
        character_action_count=action_count,
        incident_count=sum(event.event_type in incident_types for event in events),
        gate_count=sum(event.event_type in gate_types for event in events),
        budget_exhausted=any(
            (
                usage.action_exhausted,
                usage.opportunity_exhausted,
                usage.incident_exhausted,
                usage.memory_exhausted,
            )
        ),
        truncated_ticks=truncated_ticks,
        coarse_ticks=coarse_ticks,
        action_budget=usage.action_budget,
        actions_used=usage.actions_used,
        action_budget_exhausted=usage.action_exhausted,
        opportunity_budget=usage.opportunity_budget,
        opportunities_evaluated=usage.opportunities_evaluated,
        opportunity_budget_exhausted=usage.opportunity_exhausted,
        incident_budget=usage.incident_budget,
        incidents_used=usage.incidents_used,
        incident_budget_exhausted=usage.incident_exhausted,
        memory_budget=usage.memory_budget,
        memory_updates_used=usage.memory_updates_used,
        memory_budget_exhausted=usage.memory_exhausted,
        executed_workflow_steps=usage.executed_workflow_steps,
    )


def explain_event(run: AutonomousRun, sequence_or_id: int | str) -> CausalTrace:
    event = next(
        (
            item
            for item in run.events
            if item.sequence == sequence_or_id
            or item.opportunity_id == sequence_or_id
            or item.data.get("event_id") == sequence_or_id
        ),
        None,
    )
    if event is None:
        raise KeyError(f"unknown event: {sequence_or_id}")
    participants = {
        value
        for value in (
            event.actor_id,
            event.data.get("speaker_id"),
            event.data.get("listener_id"),
        )
        if isinstance(value, str)
    }
    movement: list[int] = []
    for participant in sorted(participants):
        prior = next(
            (
                candidate
                for candidate in reversed(run.events[: event.sequence])
                if any(move.character_id == participant for move in candidate.delta.moves)
            ),
            None,
        )
        if prior is not None:
            movement.append(prior.sequence)
    location = event.data.get("location_id")
    colocation = (
        tuple(f"{participant} was co-located at {location}" for participant in sorted(participants))
        if event.event_type is EventType.DIALOGUE and isinstance(location, str)
        else ()
    )
    return CausalTrace(
        sequence=event.sequence,
        event_type=event.event_type,
        opportunity_id=event.opportunity_id,
        pre_state_hash=event.pre_state_hash,
        rule_basis=event.rule_basis,
        target_entity_id=event.target_entity_id,
        seed=run.state.seed,
        deterministic_cursor=event.deterministic_cursor,
        prior_movement_sequences=tuple(sorted(set(movement))),
        colocation_basis=colocation,
        workflow_kind=event.data.get("workflow_kind"),
        workflow_step=event.data.get("workflow_step"),
    )

