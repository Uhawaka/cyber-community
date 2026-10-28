"""Score explicit reviewer annotations, never substitute event counts for semantic judgment."""

from dataclasses import asdict

from engine.application.community_validation import IMPORTANT
from engine.runtime.kernel.event_codec import event_record

REVIEW_IMPORTANT = IMPORTANT | {"use", "move", "speak", "cancel", "reject", "record", "read", "lend", "repay", "resign",
                                "take_role", "leave_role", "censure", "lease", "return_lease"}

REPETITION_VERDICTS = {"productive", "new_information", "new_attempt", "neutral", "unproductive", "pending"}
EXPLANATION_VERDICTS = {"explained", "unexplained", "pending", "not_required"}


def quality_review_template(run):
    actions = []
    for event in run.events:
        for index, action in enumerate(event.delta.actions):
            actions.append({
                "sequence": event.sequence, "action_index": index,
                "explanation": "pending" if action.kind in REVIEW_IMPORTANT else "not_required",
                "repetition": "pending", "rationale": "", "evidence": [],
            })
    return {
        "schema_version": "community-quality-review/v1",
        "world_hash": run.compiled.content_hash, "history_hash": run.history_hash(),
        "reviewer_id": "", "reviewer_kind": "human",
        "actions": actions, "chains": [], "chains_complete": False,
    }


def quality_review_bundle(run):
    """Privileged audit input. It is not a character context or public observation."""
    return {
        "schema_version": "community-quality-bundle/v1",
        "world_hash": run.compiled.content_hash, "history_hash": run.history_hash(),
        "privacy": "private audit; not public or a shared character context",
        "events": [event_record(event) for event in run.events],
        "actions": [
            {"sequence": event.sequence, "action_index": index, "tick": event.tick,
             "action": asdict(action), "reason": event.data.get("summary") or event.data.get("utterance", ""),
             "source_refs": event.data.get("source_refs", ()),
             "observers": event.observers}
            for event in run.events for index, action in enumerate(event.delta.actions)
        ],
        "annotation_template": quality_review_template(run),
        "scope": "human action/semantic/chain review; literary identity and real model behavior remain separate",
    }


def evaluate_quality_review(run, review):
    required = set(quality_review_template(run))
    if not isinstance(review, dict) or set(review) != required or review["schema_version"] != "community-quality-review/v1":
        raise ValueError("review must use the closed quality annotation schema")
    if review["world_hash"] != run.compiled.content_hash or review["history_hash"] != run.history_hash():
        raise ValueError("review belongs to another world or history")
    if (not isinstance(review["reviewer_kind"], str) or review["reviewer_kind"] not in {"human", "synthetic"}
            or not isinstance(review["reviewer_id"], str) or len(review["reviewer_id"]) > 128):
        raise ValueError("review requires an explicit reviewer kind and identity")
    if not isinstance(review["chains_complete"], bool):
        raise ValueError("chain review completeness must be a boolean")
    if not isinstance(review["actions"], list) or not isinstance(review["chains"], list):
        raise ValueError("review actions and chains must be arrays")
    actions = {(e.sequence, i): (e, a) for e in run.events for i, a in enumerate(e.delta.actions)}
    annotations = {}
    for row in review["actions"]:
        if not isinstance(row, dict) or set(row) != {"sequence", "action_index", "explanation", "repetition", "rationale", "evidence"}:
            raise ValueError("unknown or missing action annotation fields")
        key = (row["sequence"], row["action_index"])
        if any(isinstance(n, bool) or not isinstance(n, int) for n in key) or key not in actions or key in annotations:
            raise ValueError("annotation requires a unique real action")
        event, action = actions[key]
        if (not isinstance(row["explanation"], str) or not isinstance(row["repetition"], str)
                or row["explanation"] not in EXPLANATION_VERDICTS or row["repetition"] not in REPETITION_VERDICTS):
            raise ValueError("unknown semantic review verdict")
        if action.kind in REVIEW_IMPORTANT and row["explanation"] == "not_required":
            raise ValueError("important actions cannot opt out of explanation review")
        if not isinstance(row["rationale"], str) or len(row["rationale"]) > 2000:
            raise ValueError("review rationale must be bounded text")
        if not isinstance(row["evidence"], list) or len(row["evidence"]) > 16:
            raise ValueError("review evidence must be a bounded event array")
        for sequence in row["evidence"]:
            if (isinstance(sequence, bool) or not isinstance(sequence, int)
                    or not 0 <= sequence <= event.sequence):
                raise ValueError("review evidence cannot cite unknown or future events")
            origin = run.events[sequence]
            if action.character_id != origin.actor_id and action.character_id not in origin.observers:
                raise ValueError("action explanation cannot cite knowledge unavailable to its actor")
        if (row["explanation"] in {"explained", "unexplained"} or row["repetition"] != "pending") and (
            not row["rationale"].strip() or not row["evidence"]
        ):
            raise ValueError("completed semantic judgments require rationale and real evidence")
        annotations[key] = row
    if set(annotations) != set(actions):
        raise ValueError("review must account for every action, not only favorable samples")
    chain_ids, roots, consequences, independent = set(), set(), set(), []
    for chain in review["chains"]:
        if not isinstance(chain, dict) or set(chain) != {"chain_id", "initiator", "consequences", "verdict", "rationale"}:
            raise ValueError("unknown or missing chain annotation fields")
        root, ends = chain["initiator"], chain["consequences"]
        if (not isinstance(chain["chain_id"], str) or not chain["chain_id"].strip()
                or len(chain["chain_id"]) > 128 or chain["chain_id"] in chain_ids
                or not isinstance(chain["verdict"], str)
                or chain["verdict"] not in {"independent", "not_independent", "pending"}):
            raise ValueError("chain needs a unique identity and explicit reviewer judgment")
        chain_ids.add(chain["chain_id"])
        if (not isinstance(ends, list) or len(ends) > 1000
                or not isinstance(chain["rationale"], str) or len(chain["rationale"]) > 2000):
            raise ValueError("chain consequences and rationale must be bounded")
        nodes = [root, *ends]
        if any(isinstance(n, bool) or not isinstance(n, int) or not 0 <= n < len(run.events) for n in nodes):
            raise ValueError("chain evidence must reference actual events")
        if chain["verdict"] != "independent":
            continue
        start = run.events[root]
        if not ends or not chain["rationale"].strip() or len(chain["rationale"]) > 2000:
            raise ValueError("independent chain requires reviewer reasoning and consequences")
        if not any(a.kind not in {"wait", "rest", "inspect", "read"} for a in start.delta.actions):
            raise ValueError("story chain requires a character-initiated substantive action")
        if len(set(ends)) != len(ends):
            raise ValueError("chain consequences cannot repeat an event")
        if root in roots | consequences or set(ends) & (consequences | roots):
            raise ValueError("same initiator or consequence cannot be counted as independent chains twice")
        if any(n <= root for n in ends) or max(run.events[n].tick for n in ends) <= start.tick:
            raise ValueError("chain consequence must occur after initiation")
        if any(not (run.events[n].delta.resources or run.events[n].delta.inventories
                    or run.events[n].delta.entity_patches or run.events[n].delta.moves
                    or run.events[n].data.get("learned_skill")
                    or (run.events[n].event_type.value == "organization_read"
                        and run.events[n].actor_id != run.events[n].data["record"]["author_id"]
                        and (run.events[n].data["record"]["claim"].get("expires_tick") is None
                             or run.events[n].data["record"]["claim"]["expires_tick"] > run.events[n].tick))
                    or run.events[n].data.get("commitment", {}).get("status") in {"fulfilled", "breached"}
                    or run.events[n].data.get("loan", {}).get("status") in {"overdue", "repaid"}
                    or run.events[n].event_type.value in {"membership_updated", "organization_role_updated", "organization_censured"}
                    or run.events[n].data.get("handoff", {}).get("status") == "accepted") for n in ends):
            raise ValueError("chain consequences require real material, information or social change")
        if max((run.events[n].tick - 1) // 24 for n in ends) <= (start.tick - 1) // 24:
            raise ValueError("chain must cross a real simulated day boundary")
        roots.add(root)
        consequences.update(ends)
        independent.append(chain["chain_id"])
    important = [row for key, row in annotations.items() if actions[key][1].kind in REVIEW_IMPORTANT]
    explained = sum(row["explanation"] == "explained" for row in important)
    explanation_rate = explained / len(important) if important else None
    windows = []
    for end in range(20, run.state.tick + 1):
        selected = [row for key, row in annotations.items() if end - 20 < actions[key][0].tick <= end]
        if selected:
            unproductive = sum(row["repetition"] == "unproductive" for row in selected)
            windows.append({"from_tick": max(1, end - 19), "to_tick": end,
                            "actions": len(selected), "unproductive": unproductive,
                            "rate": unproductive / len(selected)})
    worst = max(windows, key=lambda window: window["rate"]) if windows else None
    human = review["reviewer_kind"] == "human" and bool(review["reviewer_id"].strip())
    sufficient = human and run.state.tick >= 100 and len(run.compiled.world.characters) >= 6
    explanation_done = bool(important) and all(row["explanation"] != "pending" for row in important)
    repetition_done = worst is not None and all(row["repetition"] != "pending" for row in annotations.values())
    chains_done = review["chains_complete"] and all(c["verdict"] != "pending" for c in review["chains"])
    return {
        "schema_version": "community-quality-result/v1",
        "world_hash": run.compiled.content_hash, "history_hash": run.history_hash(),
        "reviewer_id": review["reviewer_id"], "reviewer_kind": review["reviewer_kind"],
        "action_explanation_rate": explanation_rate, "worst_semantic_repetition_window": worst,
        "attested_independent_chains": independent,
        "quality_gates": {
            "action_explanation": explanation_rate >= 0.8 if sufficient and explanation_done else "not_evaluated",
            "unproductive_repetition": worst["rate"] <= 0.15 if sufficient and repetition_done else "not_evaluated",
            "independent_cross_day_story_chains": len(independent) >= 3 if sufficient and chains_done else "not_evaluated",
            "character_and_literary_blind_review": "not_evaluated",
            "real_model_behavior": "not_evaluated",
        },
        "scope": "scores supplied semantic attestations, not independently verified reviewer identity or automatic literary judgment",
    }
