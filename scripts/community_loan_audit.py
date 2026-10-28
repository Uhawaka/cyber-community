"""Audit material-loan opportunities at recorded offline decision boundaries."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from engine.contracts.community import ActionVerb
from engine.runtime.character.community_context import decision_context
from engine.runtime.character.community_exchange_choices import resource_reserves
from engine.runtime.character.community_policy import CommunityLifePolicy
from engine.runtime.kernel.events import EventLog, EventType
from engine.runtime.kernel.lifecycle import create_run
from engine.world import compile_package
from scripts.community_probe import policy_provenance


def audit_context(context, policy):
    """Count overlapping request conditions using only the acting person's context."""
    counts = Counter(decisions=1)
    visible = {entity.entity_id for entity in context.perception.entities}
    requests = [
        request for request in context.requests
        if request.status == "open" and request.helper_id == context.actor_id
    ]
    reserves = resource_reserves(context)
    stock = dict(context.inventory)
    trust = dict(context.relationships)
    sources = dict(context.trust_sources)
    for request in requests:
        counts["addressed_open_requests"] += 1
        local = request.requester_id in visible
        surplus = stock.get(request.item_id, 0) - reserves.get(request.item_id, 0) >= request.quantity
        interest = request.item_id in context.stocking_interests
        positive = trust.get(request.requester_id, 0) > 0
        anchor = bool(sources.get(request.requester_id))
        offered = any(
            offer.sender_id == context.actor_id and offer.recipient_id == request.requester_id
            and offer.item_id == request.item_id for offer in context.offers
        )
        outstanding = any(
            loan.lender_id == context.actor_id and loan.borrower_id == request.requester_id
            and loan.item_id == request.item_id and loan.status in {"proposed", "accepted", "overdue"}
            for loan in context.loans
        )
        overdue = any(
            loan.lender_id == context.actor_id and loan.borrower_id == request.requester_id
            and loan.status == "overdue" for loan in context.loans
        )
        credit_allowed = trust.get(request.requester_id, 0) == 0 or (positive and anchor)
        already_proposed = request.request_id in context.loaned_requests
        for name, condition in (
            ("requester_visible", local),
            ("surplus", surplus),
            ("stocking_interest", interest),
            ("positive_trust", positive),
            ("trust_anchor", anchor),
            ("existing_offer", offered),
            ("outstanding_loan", outstanding),
            ("overdue_debt", overdue),
            ("neutral_or_sourced_positive", credit_allowed),
            ("already_proposed", already_proposed),
            ("local_and_surplus", local and surplus),
            ("local_surplus_and_interest", local and surplus and interest),
            ("local_surplus_interest_trust_anchor", local and surplus and interest and positive and anchor),
            ("all_request_conditions", local and surplus and interest and credit_allowed
             and not offered and not outstanding and not overdue and not already_proposed),
        ):
            if condition:
                counts[name] += 1
    answer = policy.answer_requests(context, visible)
    if answer and answer.verb is ActionVerb.LEND:
        counts["answer_would_lend"] += 1
        if policy.propose(context) != answer:
            counts["lend_preempted"] += 1
        else:
            counts["policy_would_lend"] += 1
    return counts


def audit_sample(compiled, sample):
    seed, ticks = sample["seed"], sample["ticks"]
    events = EventLog.read_events(sample["log_path"], world_hash=compiled.content_hash)
    run = create_run(compiled, seed)
    if not events or events[0] != run.events[0]:
        raise ValueError("sample genesis does not match its world and seed")
    counts = Counter()
    policy = CommunityLifePolicy()
    for event in events[1:]:
        if (event.event_type is EventType.COMMUNITY_TICK and event.data.get("phase") == "open"
                and event.tick >= ticks):
            break
        if event.delta.actions and event.actor_id in run.state.characters:
            counts.update(audit_context(decision_context(run, event.actor_id), policy))
            if any(action.kind == "lend" for action in event.delta.actions):
                counts["recorded_lends"] += 1
        run.log.append(event)
    if run.state.tick != ticks or run.history_hash() != sample["history_hash"]:
        raise ValueError("sample prefix does not match its reported tick and history hash")
    return {"seed": seed, "ticks": ticks, "history_hash": sample["history_hash"],
            "counts": dict(sorted(counts.items()))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ticks", type=int, default=100)
    args = parser.parse_args(argv)
    result = compile_package(args.package)
    if not result.ok or result.compiled.community is None:
        parser.error("requires a valid community package")
    report = json.loads(args.report.read_text())
    if report["world_hash"] != result.compiled.content_hash:
        parser.error("probe world hash differs from package")
    if report["policy_provenance"] != policy_provenance():
        parser.error("probe policy provenance differs from current policy")
    samples = [sample for sample in report["samples"] if sample.get("ticks") == args.ticks]
    required_gates = {"action_sources", "nonnegative_inventory", "past_event_references",
                      "replay", "restore", "resume_next_tick"}
    if not samples or any(
        sample.get("error")
        or not required_gates.issubset(sample.get("mechanism_gates", {}))
        or not all(value is True for value in sample["mechanism_gates"].values())
        for sample in samples
    ):
        parser.error("requested samples are missing or failed")
    if args.output.exists():
        parser.error("output already exists")
    audited = [audit_sample(result.compiled, sample) for sample in samples]
    total = Counter()
    for sample in audited:
        total.update(sample["counts"])
    output = {
        "schema_version": "community-loan-audit/v1",
        "world_hash": report["world_hash"],
        "policy_provenance": report["policy_provenance"],
        "samples": audited,
        "totals": dict(sorted(total.items())),
        "limitations": [
            "Only recorded action boundaries are audited; sleeping and rejected decisions are excluded.",
            "Request counters overlap and may count the same request at multiple boundaries.",
            "Conditions are actor-local diagnostics, not proof of a natural loan cycle or quality.",
            "Policy provenance covers decision and context modules, not the full engine revision.",
        ],
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
