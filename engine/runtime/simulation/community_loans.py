"""Voluntary material loans and repayment, without automatic debt collection."""

from dataclasses import asdict, replace

from engine.contracts.community import ActionVerb
from engine.contracts.society import MaterialLoan
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.community_loan_validation import loan_inventory_delta
from engine.runtime.kernel.events import ActionRecord, Delta, EventType
from engine.runtime.simulation.community_events import commit


def write_loan(run, record, actor_id, *, verb=None, target=None, system=False):
    return commit(
        run, EventType.LOAN_UPDATED, actor_id=actor_id,
        observers=tuple(sorted(p for p in (record.lender_id, record.borrower_id)
                               if run.state.characters[p].active)),
        delta=Delta(inventories=loan_inventory_delta(record), actions=(
            (ActionRecord(actor_id, verb.value, target, run.state.tick),) if verb else ()
        )),
        data={"loan": asdict(record), "system_update": system,
              "summary": f"material loan {record.item_id}: {record.status}"},
        sources=record.source_refs, target_id=record.item_id,
        commit_id=f"loan:{record.loan_id}:{record.status}",
    )


def loan_action(run, proposal, context):
    projection = community_projection(run)
    if proposal.verb is ActionVerb.LEND:
        if proposal.target_id not in {e.entity_id for e in context.perception.entities if e.kind == "character"}:
            raise ValueError("loan requires an eye-level local borrower")
        if proposal.requested_item_id and proposal.requested_item_id != proposal.item_id:
            raise ValueError("material loan repayment uses the same registered item")
        record = MaterialLoan(
            proposal.proposal_id, proposal.actor_id, proposal.target_id, proposal.item_id,
            proposal.quantity, proposal.requested_quantity or proposal.quantity,
            proposal.source_refs, run.state.tick + 24,
        )
    else:
        old = projection.loans.get(proposal.target_id)
        if old is None or old.borrower_id != proposal.actor_id:
            raise ValueError("only addressed borrower may answer or repay")
        status = {ActionVerb.ACCEPT: "accepted", ActionVerb.REJECT: "rejected", ActionVerb.REPAY: "repaid"}[proposal.verb]
        source = projection.social_latest[("loan", old.loan_id)]
        record = replace(old, status=status, source_refs=tuple(dict.fromkeys(
            (*proposal.source_refs, f"event:{source}"),
        )))
    return write_loan(run, record, proposal.actor_id, verb=proposal.verb, target=proposal.target_id)


def settle_loans(run):
    projection = community_projection(run)
    for record in projection.loans.pending():
        if run.state.tick <= record.deadline_tick:
            continue
        source = projection.social_latest[("loan", record.loan_id)]
        write_loan(run, replace(
            record, status="expired" if record.status == "proposed" else "overdue",
            source_refs=(f"event:{source}",),
        ), record.lender_id, system=True)
