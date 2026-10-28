"""Synthetic index costs, not long-run community or narrative acceptance."""

import argparse
from dataclasses import replace
import platform
from statistics import median
from time import perf_counter
from types import SimpleNamespace

from engine.contracts.cognition import KnowledgeClaim, MemoryRecord
from engine.contracts.society import ExchangeOffer
from engine.runtime.character import community_memory
from engine.runtime.character.community_knowledge import OwnedClaims
from engine.runtime.character.community_pending import PendingRecords
from engine.runtime.character.community_outcomes import OutcomeIndex
from engine.runtime.kernel.events import EventType
from engine.runtime.kernel.community_validation_index import CommunityValidationIndex
from scripts.community_quality import private_json


def measured(operation, repeats):
    timings, result = [], None
    for _ in range(repeats):
        start = perf_counter()
        result = operation()
        timings.append(perf_counter() - start)
    return result, median(timings)


def sample(size, repeats):
    memories = community_memory.MemoryIndex()
    memories.add(MemoryRecord("old", "a", 0, "old important lamp evidence", ("event:0",),
                              entity_ids=("lamp",), importance=90))
    claims = OwnedClaims()
    claims["own"] = KnowledgeClaim("own", "a", "lamp", "condition", "broken", ("event:0",), 0, "inference")
    pending = PendingRecords("offer_id", {"proposed"}, ("sender_id", "recipient_id"))
    for n in range(size):
        for owner in ("a", "b"):
            memories.add(MemoryRecord(f"{owner}:{n}", owner, n + 1, f"ordinary {owner} event {n}",
                                     ("event:0",), importance=20))
        claim = replace(claims["own"], claim_id=f"foreign:{n}", owner_id="b")
        claims[claim.claim_id] = claim
        key = f"terminal:{n}"
        pending[key] = ExchangeOffer(key, "x", "y", "wire", 1, ("event:0",), 24, status="expired")
    pending["open"] = ExchangeOffer("open", "a", "b", "wire", 1, ("event:0",), 24)
    retrieve = lambda: memories.retrieve("a", tick=size, entity_ids=("lamp",), limit=12)
    heap_result, heap_seconds = measured(retrieve, repeats)
    original_heapify, original_pop = community_memory.heapify, community_memory.heappop
    try:
        # Same scoring/selection code with full-sort ordering provides an exact comparison.
        community_memory.heapify = lambda values: values.sort()
        community_memory.heappop = lambda values: values.pop(0)
        sorted_result, sort_seconds = measured(retrieve, repeats)
    finally:
        community_memory.heapify, community_memory.heappop = original_heapify, original_pop
    own, own_seconds = measured(lambda: tuple(claims.owned("a")), repeats)
    all_own, scan_seconds = measured(lambda: tuple(c for c in claims.values() if c.owner_id == "a"), repeats)
    opened, pending_seconds = measured(pending.pending, repeats)
    scanned, terminal_scan_seconds = measured(
        lambda: tuple(r for r in pending.values() if r.status == "proposed"), repeats,
    )
    outcomes = OutcomeIndex()
    events = [
        SimpleNamespace(sequence=n, tick=1, event_type=EventType.EXCHANGE_UPDATED,
                        data={"offer": {"status": "accepted", "sender_id": f"foreign:{n}",
                                        "recipient_id": "a", "item_id": "wire", "quantity": 1}})
        for n in range(size)
    ]
    events.append(SimpleNamespace(
        sequence=size, tick=2, event_type=EventType.EXCHANGE_UPDATED,
        data={"offer": {"status": "accepted", "sender_id": "b", "recipient_id": "a",
                        "item_id": "wire", "quantity": 1}},
    ))
    for event in events:
        outcomes.add(event)
    request = SimpleNamespace(helper_id="b", requester_id="a", item_id="wire", quantity=1, deadline_tick=24)
    indexed, indexed_seconds = measured(lambda: outcomes.delivery(request, -1, events), repeats)
    scanned_outcome, outcome_scan_seconds = measured(
        lambda: next(e for e in events if e.data["offer"]["sender_id"] == "b"), repeats,
    )
    validation = CommunityValidationIndex()
    commit_ids = [f"commit:{number}" for number in range(size)]
    validation.commit_ids.update(commit_ids)
    target = commit_ids[-1]
    found, commit_seconds = measured(lambda: target in validation.commit_ids, repeats)
    scanned_commit, commit_scan_seconds = measured(lambda: any(key == target for key in commit_ids), repeats)
    return {
        "owned_memories": size + 1, "foreign_memories": size, "terminal_offers": size,
        "heap_seconds": heap_seconds, "full_sort_seconds": sort_seconds,
        "owned_claim_seconds": own_seconds, "global_claim_scan_seconds": scan_seconds,
        "pending_seconds": pending_seconds, "terminal_scan_seconds": terminal_scan_seconds,
        "ordering_identical": heap_result == sorted_result,
        "old_evidence_recalled": heap_result[0].record.memory_id == "old",
        "owner_selection_identical": own == all_own,
        "pending_selection_identical": opened == scanned,
        "indexed_outcome_seconds": indexed_seconds, "outcome_scan_seconds": outcome_scan_seconds,
        "outcome_selection_identical": indexed == scanned_outcome,
        "indexed_commit_seconds": commit_seconds, "commit_scan_seconds": commit_scan_seconds,
        "commit_selection_identical": found == scanned_commit,
    }


def main(argv=None):
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 100 or any(not 1 <= size <= 100000 for size in args.sizes):
        parser.error("sizes must be 1..100000 and repeats 1..100")
    records = [sample(size, args.repeats) for size in args.sizes]
    private_json(args.output, {
        "schema_version": "community-index-benchmark/v1",
        "python": platform.python_version(), "platform": platform.platform(),
        "repeats": args.repeats, "samples": records,
        "scope": "synthetic retrieval/selection cost; not 1000 Tick quality or whole-engine performance",
    })
    return int(any(not all(row[field] for field in (
        "ordering_identical", "old_evidence_recalled", "owner_selection_identical",
        "pending_selection_identical", "outcome_selection_identical", "commit_selection_identical",
    )) for row in records))


if __name__ == "__main__":
    raise SystemExit(main())
