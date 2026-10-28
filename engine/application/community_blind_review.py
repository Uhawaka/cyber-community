"""Anonymous human-review inputs copied from author material and committed speech."""

from collections.abc import Mapping
import re
from statistics import median

from engine.runtime.simulation.community_events import open_tick


def blind_review_materials(run):
    characters = sorted(run.compiled.world.characters, key=lambda c: c.id)
    aliases = {c.id: f"person-{n + 1}" for n, c in enumerate(characters)}
    replacements = sorted(
        [(value, aliases[c.id]) for c in characters for value in (c.name, c.id)],
        key=lambda pair: -len(pair[0]),
    )
    lookup = dict(replacements)
    patterns = [
        (rf"(?<![A-Za-z0-9_]){re.escape(text)}(?![A-Za-z0-9_])"
         if text.isascii() else re.escape(text))
        for text, _ in replacements
    ]
    pattern = re.compile("|".join(patterns)) if patterns else None

    def anonymize(value):
        if isinstance(value, str):
            # Single pass avoids replacing a short identifier inside a newly inserted alias.
            return pattern.sub(lambda match: lookup[match.group()], value) if pattern else value
        if isinstance(value, Mapping):
            return {key: anonymize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [anonymize(item) for item in value]
        return value

    speech = [
        {"sequence": e.sequence, "tick": e.tick, "speaker": aliases[e.actor_id],
         "text": anonymize(e.data["utterance"]),
         "source_sequences": [int(ref[6:]) for ref in e.data.get("source_refs", ())
                              if ref.startswith("event:")]}
        for e in run.events if e.event_type.value == "dialogue" and e.actor_id in aliases
    ]
    binding = {"world_hash": run.compiled.content_hash, "history_hash": run.history_hash()}
    material = {
        "schema_version": "community-blind-material/v1", **binding,
        "privacy": "private review; author secrets are not shared character knowledge",
        "cast": [
            {"person": aliases[c.id], "soul": anonymize(dict(c.soul)),
             "profile": anonymize(dict(c.profile)), "memory_seed": anonymize(c.memory_seed)}
            for c in characters
        ],
        "speech": [{key: value for key, value in row.items() if key != "speaker"} for row in speech],
        "pressure_questions": [
            "A trusted neighbor needs material you reserved for a personal goal. What would this person consider?",
            "An obligation is overdue and the other party has not answered. Which choices fit this person?",
            "Someone offers responsibility for work beyond current skills. What could this person decide?",
        ],
        "review_slots": [
            {"reviewer_id": "", "reviewer_kind": "human",
             "scores": {"character_distinctness": None, "action_reasonableness": None,
                        "consequence_continuity": None, "story_interest": None},
             "critical_factual_errors": [], "speech_guesses": [], "rationale": ""}
            for _ in range(2)
        ],
        "quality_gates": "not_evaluated",
        "scope": "actual committed lines and unanswered pressure questions; no generated answers or supplied scores",
        "limitations": [
            "Anonymization is for review blinding, not guaranteed personal-data de-identification.",
            "Author content and simulation language may still reveal identity.",
            "Offline template speech is not real model characterization evidence.",
            "Use a separate private evidence bundle to check chronology and consequences.",
        ],
    }
    key = {"schema_version": "community-blind-key/v1", **binding,
           "identities": aliases, "speech_speakers": {str(row["sequence"]): row["speaker"] for row in speech},
           "privacy": "keep separate from reviewers until independent scoring is complete"}
    return material, key


def evaluate_blind_review(run, review):
    """Calculate one sample's human-attested scores without verifying reviewer identity."""
    expected, _ = blind_review_materials(run)

    def unchanged(original, candidate):
        if type(original) is not type(candidate):
            return False
        if isinstance(original, dict):
            return original.keys() == candidate.keys() and all(
                unchanged(value, candidate[key]) for key, value in original.items()
            )
        if isinstance(original, list):
            return len(original) == len(candidate) and all(
                unchanged(left, right) for left, right in zip(original, candidate)
            )
        return original == candidate

    if not isinstance(review, dict) or set(review) != set(expected):
        raise ValueError("blind review must use the original closed material schema")
    if any(not unchanged(value, review[key]) for key, value in expected.items() if key != "review_slots"):
        raise ValueError("blind review material must match the original world and history")
    slots = review["review_slots"]
    if not isinstance(slots, list) or not 2 <= len(slots) <= 16:
        raise ValueError("blind review requires between two and sixteen reviewer slots")
    score_names = tuple(expected["review_slots"][0]["scores"])
    known_people = {row["person"] for row in expected["cast"]}
    known_speech = {row["sequence"] for row in expected["speech"]}
    identities, completed = set(), []
    for slot in slots:
        if not isinstance(slot, dict) or set(slot) != set(expected["review_slots"][0]):
            raise ValueError("blind reviewer slot must use the closed schema")
        identity, kind = slot["reviewer_id"], slot["reviewer_kind"]
        if (not isinstance(identity, str) or len(identity) > 128
                or not isinstance(kind, str) or kind not in {"human", "synthetic"}):
            raise ValueError("blind reviewer needs a bounded identity and kind")
        identity = identity.strip()
        if identity and identity.casefold() in identities:
            raise ValueError("blind reviewers must have distinct identities")
        if identity:
            identities.add(identity.casefold())
        scores = slot["scores"]
        if not isinstance(scores, dict) or set(scores) != set(score_names):
            raise ValueError("blind review requires the four original scores")
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or not 1 <= value <= 5) for value in scores.values()):
            raise ValueError("blind scores must be integers from one to five or null")
        errors, guesses, rationale = slot["critical_factual_errors"], slot["speech_guesses"], slot["rationale"]
        if (not isinstance(errors, list) or len(errors) > 100
                or any(not isinstance(error, str) or not error.strip() or len(error) > 2000 for error in errors)
                or not isinstance(guesses, list) or len(guesses) > len(known_speech)
                or not isinstance(rationale, str) or len(rationale) > 4000):
            raise ValueError("blind review evidence and rationale must be bounded")
        guessed = set()
        for guess in guesses:
            if (not isinstance(guess, dict) or set(guess) != {"sequence", "person"}
                    or isinstance(guess["sequence"], bool) or not isinstance(guess["sequence"], int)
                    or guess["sequence"] not in known_speech or guess["sequence"] in guessed
                    or not isinstance(guess["person"], str) or guess["person"] not in known_people):
                raise ValueError("speech guess must identify a unique actual line and anonymous person")
            guessed.add(guess["sequence"])
        if kind == "human" and identity and rationale.strip() and all(value is not None for value in scores.values()):
            completed.append(slot)
    sufficient = (len(completed) == len(slots) and len(completed) >= 2
                  and run.state.tick >= 100 and len(run.compiled.world.characters) >= 6
                  and not open_tick(run))
    medians = {name: median(slot["scores"][name] for slot in completed) for name in score_names} if sufficient else None
    critical_errors = sum(len(slot["critical_factual_errors"]) for slot in completed)
    gate = (
        not critical_errors and all(medians[name] >= 4 for name in score_names[:3])
        and medians["story_interest"] >= 3
    ) if sufficient else "not_evaluated"
    return {
        "schema_version": "community-blind-result/v1",
        "world_hash": run.compiled.content_hash,
        "history_hash": run.history_hash(),
        "human_reviews_completed": len(completed),
        "medians": medians,
        "critical_factual_errors": critical_errors,
        "quality_gate": gate,
        "scope": "one sample's human-attested scores; reviewer identity and independent blinding are not independently verified; not an eight-seed or real-model gate",
    }
