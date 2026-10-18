from dataclasses import FrozenInstanceError

import pytest

from engine.participation import (
    AvatarProfile,
    AvatarSession,
    GateDecision,
    GateStatus,
    InterventionAttempt,
    Opportunity,
    ParticipantKind,
    UserGate,
    answer_gate,
    expire_gate,
    resolve_intervention,
)
from engine.runtime.character import (
    ProposalStatus,
    Scheme,
    SchemeStatus,
    abandon_scheme,
    advance_scheme,
    approve_soul_evolution,
    propose_soul_evolution,
    reject_soul_evolution,
)


class RecordingResolver:
    def __init__(self):
        self.calls = []

    def resolve(self, opportunity, attempt):
        self.calls.append((opportunity, attempt))
        return {
            "participant": opportunity.participant_id,
            "action": attempt.action,
        }


def _attempt(opportunity, suffix="1"):
    return InterventionAttempt(
        attempt_id=f"attempt-{suffix}",
        opportunity_id=opportunity.opportunity_id,
        participant_id=opportunity.participant_id,
        action="speak",
        arguments={"text": "我愿意试试"},
    )


def test_avatar_profile_and_session_are_immutable_value_contracts():
    profile = AvatarProfile("avatar-1", "旅人", (("pace", "slow"),))
    session = AvatarSession("session-1", profile, 10.0, 12.0)
    assert session.profile.avatar_id == "avatar-1"
    with pytest.raises(FrozenInstanceError):
        session.last_active_at = 13.0
    with pytest.raises(ValueError, match="precede"):
        AvatarSession("session-2", profile, 12.0, 11.0)


def test_avatar_and_npc_use_the_same_opportunity_resolver_port():
    avatar = Opportunity(
        "opp-avatar",
        "avatar-1",
        ParticipantKind.AVATAR,
        {"visible": ("gate",)},
    )
    npc = Opportunity(
        "opp-npc",
        "keeper",
        ParticipantKind.NPC,
        {"visible": ("gate",)},
    )
    resolver = RecordingResolver()

    avatar_result = resolve_intervention(avatar, _attempt(avatar), resolver)
    npc_result = resolve_intervention(npc, _attempt(npc, "2"), resolver)

    assert avatar_result == {
        "participant": "avatar-1",
        "action": "speak",
    }
    assert npc_result == {"participant": "keeper", "action": "speak"}
    assert [call[0].participant_kind for call in resolver.calls] == [
        ParticipantKind.AVATAR,
        ParticipantKind.NPC,
    ]


def test_user_can_submit_attempt_but_cannot_supply_delta():
    with pytest.raises(ValueError, match="cannot provide state deltas"):
        InterventionAttempt(
            "attempt-bad",
            "opp-1",
            "avatar-1",
            "force",
            {"nested": {"state_delta": {"trust": 1}}},
        )

    opportunity = Opportunity(
        "opp-1",
        "avatar-1",
        ParticipantKind.AVATAR,
        {},
    )
    wrong_owner = InterventionAttempt(
        "attempt-wrong",
        "opp-1",
        "other",
        "wait",
    )
    with pytest.raises(ValueError, match="does not own"):
        resolve_intervention(opportunity, wrong_owner, RecordingResolver())


def test_gate_answers_before_deadline_and_defaults_to_abstain_at_deadline():
    gate = UserGate(
        "gate-1",
        "opp-1",
        trigger="avatar enters the contested room",
        deadline=20.0,
    )
    assert expire_gate(gate, now=19.9) is gate

    expired = expire_gate(gate, now=20.0)
    assert expired.status is GateStatus.EXPIRED
    assert expired.decision is GateDecision.ABSTAIN
    assert gate.status is GateStatus.PENDING

    answered = answer_gate(
        gate,
        GateDecision.ACCEPT,
        answered_at=19.0,
    )
    assert answered.status is GateStatus.ANSWERED
    assert answered.decision is GateDecision.ACCEPT
    with pytest.raises(ValueError, match="already closed"):
        answer_gate(answered, GateDecision.DECLINE, answered_at=19.5)


def test_gate_rejects_non_abstain_default_and_late_answer_abstains():
    with pytest.raises(ValueError, match="default to abstain"):
        UserGate(
            "gate-1",
            "opp-1",
            trigger="danger",
            deadline=10.0,
            default=GateDecision.ACCEPT,
        )
    late = answer_gate(
        UserGate("gate-2", "opp-2", "danger", 10.0),
        GateDecision.ACCEPT,
        answered_at=10.0,
    )
    assert late.status is GateStatus.EXPIRED
    assert late.decision is GateDecision.ABSTAIN


def test_soul_evolution_requires_evidence_cooldown_and_bounded_magnitude():
    proposal = propose_soul_evolution(
        proposal_id="soul-1",
        character_id="keeper",
        trait="trust",
        proposed_value="more trusting",
        evidence_event_ids=("event-7", "event-9"),
        magnitude=0.2,
        current_version=10,
        last_evolution_version=5,
        cooldown_versions=3,
    )
    assert proposal.status is ProposalStatus.PENDING
    assert proposal.cooldown_until_version == 13

    with pytest.raises(ValueError, match="event evidence"):
        propose_soul_evolution(
            proposal_id="soul-no-evidence",
            character_id="keeper",
            trait="trust",
            proposed_value="changed",
            evidence_event_ids=(),
            magnitude=0.1,
            current_version=10,
            last_evolution_version=None,
            cooldown_versions=3,
        )
    with pytest.raises(ValueError, match="still in cooldown"):
        propose_soul_evolution(
            proposal_id="soul-cooldown",
            character_id="keeper",
            trait="trust",
            proposed_value="changed",
            evidence_event_ids=("event-10",),
            magnitude=0.1,
            current_version=10,
            last_evolution_version=9,
            cooldown_versions=3,
        )
    with pytest.raises(ValueError, match="maximum magnitude"):
        propose_soul_evolution(
            proposal_id="soul-large",
            character_id="keeper",
            trait="trust",
            proposed_value="changed",
            evidence_event_ids=("event-10",),
            magnitude=0.3,
            current_version=10,
            last_evolution_version=None,
            cooldown_versions=3,
        )


def test_soul_proposal_can_be_approved_or_rejected_exactly_once():
    proposal = propose_soul_evolution(
        proposal_id="soul-1",
        character_id="keeper",
        trait="trust",
        proposed_value="more trusting",
        evidence_event_ids=("event-7",),
        magnitude=0.1,
        current_version=10,
        last_evolution_version=None,
        cooldown_versions=3,
    )
    approved = approve_soul_evolution(
        proposal,
        reason="evidence is sufficient",
    )
    rejected = reject_soul_evolution(
        proposal,
        reason="evidence is contradicted",
    )
    assert approved.status is ProposalStatus.APPROVED
    assert rejected.status is ProposalStatus.REJECTED
    assert proposal.status is ProposalStatus.PENDING
    with pytest.raises(ValueError, match="already decided"):
        reject_soul_evolution(approved, reason="changed mind")


def test_scheme_tracks_target_progress_and_terminal_status():
    scheme = Scheme(
        scheme_id="scheme-1",
        character_id="keeper",
        target_state={"gate": "sealed"},
    )
    active = advance_scheme(scheme, progress=0.4)
    completed = advance_scheme(active, progress=1.0)

    assert active.target_state == {"gate": "sealed"}
    assert active.status is SchemeStatus.ACTIVE
    assert completed.progress == 1.0
    assert completed.status is SchemeStatus.COMPLETED
    with pytest.raises(ValueError, match="terminal"):
        advance_scheme(completed, progress=1.0)
    with pytest.raises(ValueError, match="backwards"):
        advance_scheme(active, progress=0.2)

    abandoned = abandon_scheme(active)
    assert abandoned.status is SchemeStatus.ABANDONED
    with pytest.raises(ValueError, match="cannot be abandoned"):
        abandon_scheme(completed)
