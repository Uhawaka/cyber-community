"""Audit invitation opportunities at recorded offline decision boundaries."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from engine.contracts.community import ActionVerb
from engine.runtime.character.community_context import decision_context
from engine.runtime.character.community_membership_policy import choose_invitation
from engine.runtime.character.community_policy import CommunityLifePolicy
from engine.runtime.kernel.events import EventLog, EventType
from engine.runtime.kernel.lifecycle import create_run
from engine.world import compile_package
from scripts.community_probe import policy_provenance


def audit_sample(compiled, sample):
    """Rebuild exactly the reported prefix; do not infer unobserved decisions."""
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
            context = decision_context(run, event.actor_id)
            counts["decisions"] += 1
            if context.invitation_groups:
                counts["local_group"] += 1
            if context.invitation_groups and dict(context.needs).get("social", 0) >= 30:
                counts["local_group_and_social"] += 1
            heard = [
                claim for claim in context.capabilities
                if claim.channel == "heard" and claim.source_person == claim.subject
            ]
            if heard:
                counts["heard_capability"] += 1
            visible = {entity.entity_id for entity in context.perception.entities
                       if entity.kind == "character"}
            outsiders = {
                person for _, members in context.invitation_groups
                for person in visible if person != context.actor_id and person not in members
            }
            if outsiders:
                counts["local_nonmember"] += 1
            if (dict(context.needs).get("social", 0) >= 30
                    and any(dict(context.relationships).get(person, 0) > 0 for person in outsiders)):
                counts["local_trusted_nonmember_and_social"] += 1
            if any(
                claim.subject in visible and claim.subject not in members
                and claim.predicate.removeprefix("skill:") in context.learning_interests
                and claim.predicate.removeprefix("skill:") not in context.skills
                for _, members in context.invitation_groups for claim in heard
            ):
                counts["local_interested_nonmember"] += 1
            proposal = choose_invitation(policy, context)
            if proposal:
                counts["eligible"] += 1
                chosen = policy.propose(context)
                if chosen.verb is not ActionVerb.INVITE:
                    counts["eligible_preempted"] += 1
            if any(action.kind == "invite" for action in event.delta.actions):
                counts["invites"] += 1
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
    if not samples or any(sample.get("error") for sample in samples):
        parser.error("requested samples are missing or failed")
    if args.output.exists():
        parser.error("output already exists")
    audited = [audit_sample(result.compiled, sample) for sample in samples]
    total = Counter()
    for sample in audited:
        total.update(sample["counts"])
    output = {
        "schema_version": "community-invitation-audit/v1",
        "world_hash": report["world_hash"],
        "policy": CommunityLifePolicy.version,
        "samples": audited,
        "totals": dict(sorted(total.items())),
        "limitations": [
            "Only recorded action boundaries are audited; sleeping and rejected decisions are excluded.",
            "Eligibility is a deterministic policy diagnostic, not a quality or governance verdict.",
            "Counters overlap and do not identify a single cause for every missing invitation.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
