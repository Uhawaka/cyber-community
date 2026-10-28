"""Voluntary temporary possession, explicit return and non-seizing expiry."""

from dataclasses import asdict, replace

from engine.contracts.community import ActionVerb
from engine.contracts.society import MaterialLease
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.community_lease_validation import lease_inventory_delta
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def write_lease(run, record, actor_id, *, verb=None, target=None, system=False):
    return commit(
        run, EventType.LEASE_UPDATED, actor_id=actor_id,
        observers=tuple(sorted(p for p in (record.lessor_id, record.lessee_id)
                               if run.state.characters[p].active)),
        delta=Delta(inventories=lease_inventory_delta(record),
                    actions=(ActionRecord(actor_id, verb.value, target, run.state.tick),) if verb else ()),
        data={"lease": asdict(record), "system_update": system,
              "summary": f"temporary possession {record.item_id}: {record.status}"},
        sources=record.source_refs, target_id=record.item_id,
        commit_id=f"lease:{record.lease_id}:{record.status}",
    )


def lease_action(run, proposal, context):
    projection = community_projection(run)
    if proposal.verb is ActionVerb.LEASE:
        if proposal.target_id not in {e.entity_id for e in context.perception.entities if e.kind == "character"}:
            raise ValueError("lease requires a visible local recipient")
        record = MaterialLease(
            proposal.proposal_id, proposal.actor_id, proposal.target_id, proposal.item_id,
            proposal.quantity, proposal.requested_quantity or 24, proposal.source_refs, run.state.tick + 24,
        )
    else:
        old = projection.leases.get(proposal.target_id)
        if old is None or old.lessee_id != proposal.actor_id:
            raise ValueError("only lessee may answer or return")
        status = {ActionVerb.ACCEPT: "accepted", ActionVerb.REJECT: "rejected",
                  ActionVerb.RETURN_LEASE: "returned"}[proposal.verb]
        record = replace(old, status=status,
                         due_tick=run.state.tick + old.duration_ticks if status == "accepted" else old.due_tick,
                         source_refs=tuple(dict.fromkeys(
                             (*proposal.source_refs, f"event:{projection.social_latest[('lease', old.lease_id)]}"),
                         )))
    return write_lease(run, record, proposal.actor_id, verb=proposal.verb, target=proposal.target_id)


def settle_leases(run):
    projection = community_projection(run)
    for record in projection.leases.pending():
        deadline = record.answer_deadline_tick if record.status == "proposed" else record.due_tick
        if run.state.tick <= deadline:
            continue
        write_lease(run, replace(
            record, status="expired" if record.status == "proposed" else "overdue",
            source_refs=(f"event:{projection.social_latest[('lease', record.lease_id)]}",),
        ), record.lessor_id, system=True)
