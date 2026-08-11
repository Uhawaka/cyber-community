"""Production Pipeline: observation → reasoning → discussion → artifacts.

The community's purpose: mathematicians observe the human world, process
what they find through their distinct cognitive styles, debate with each
other, and produce tangible intellectual outputs.

Pipeline:
  External Input → Observation → Study → Collision/Gathering → Artifact → Archive
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Artifact:
    """A tangible intellectual product of the community."""
    id: str
    type: str               # paper | conjecture | counterexample | insight | debate_record
    title: str
    content: str
    authors: list
    created_day: int
    confidence: float = 0.5  # how confident are the authors?
    status: str = "draft"    # draft | published | refuted | superseded
    references: list = field(default_factory=list)  # other artifacts it builds on
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "title": self.title,
            "content": self.content, "authors": self.authors,
            "created_day": self.created_day, "confidence": self.confidence,
            "status": self.status, "references": self.references,
            "timestamp": self.timestamp or datetime.now().isoformat(),
        }


class ProductionPipeline:
    """Manages the observation → production → archive flow."""

    def __init__(self, path: str, llm=None):
        self.path = path
        self.llm = llm
        self.artifacts: list[Artifact] = []
        self.observations: list[dict] = []  # recent external inputs
        self._counter = 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    # ─── Artifact Creation ─────────────────────────────────────

    def create_artifact(self, artifact_type: str, title: str, content: str,
                        authors: list, confidence: float = 0.5,
                        references: list = None) -> Artifact:
        """Record a new intellectual product."""
        self._counter += 1
        art = Artifact(
            id=f"art_{self._counter:04d}",
            type=artifact_type,
            title=title,
            content=content,
            authors=authors,
            created_day=getattr(self, '_current_day', 1),
            confidence=confidence,
            references=references or [],
            timestamp=datetime.now().isoformat(),
        )
        self.artifacts.append(art)
        self.save()
        return art

    def get_recent(self, count: int = 5) -> list[Artifact]:
        """Get most recent artifacts."""
        return self.artifacts[-count:]

    def get_by_author(self, author: str, count: int = 5) -> list[Artifact]:
        """Get artifacts by a specific author."""
        return [a for a in self.artifacts if author in a.authors][-count:]

    def get_by_type(self, artifact_type: str, count: int = 5) -> list[Artifact]:
        """Get artifacts of a specific type."""
        return [a for a in self.artifacts if a.type == artifact_type][-count:]

    # ─── Observation Pipeline ─────────────────────────────────

    def record_observation(self, source: str, content: str, 
                            found_by: str, importance: float = 0.5):
        """Record an external observation (arxiv paper, news, problem)."""
        self.observations.append({
            "source": source,
            "content": content,
            "found_by": found_by,
            "importance": importance,
            "day": getattr(self, '_current_day', 1),
        })
        if len(self.observations) > 50:
            self.observations = self.observations[-50:]

    def get_unprocessed_observations(self, char_name: str) -> list[dict]:
        """Get observations this character hasn't seen yet."""
        # Simple: return recent observations not by this character
        return [o for o in self.observations[-10:] 
                if o.get("found_by") != char_name]

    # ─── Digest Generation ────────────────────────────────────

    def generate_digest(self, period: str = "daily") -> str:
        """Generate a summary of the community's intellectual production."""
        recent = self.get_recent(10)
        if not recent:
            return "本周期无产出。"

        if not self.llm:
            summary_parts = []
            for a in recent[-5:]:
                summary_parts.append(f"[{a.type}] {a.title} by {', '.join(a.authors)}")
            return "产出摘要:\n" + "\n".join(summary_parts)

        summary_parts = []
        for a in recent[-5:]:
            summary_parts.append(
                f"[{a.type}] {a.title} by {', '.join(a.authors)} "
                f"(confidence: {a.confidence:.0%})"
            )

        prompt = f"""社区的{period}产出总结：

{chr(10).join(summary_parts)}

写一份简洁的{period}报（150字以内）：
1. 最值得注意的发现
2. 最有趣的争论
3. 下一步方向"""

        return self.llm.chat(
            [{"role": "user", "content": prompt}],
            system="你是社区的记录者。简洁、精确。",
            temperature=0.5,
        )

    # ─── Persistence ──────────────────────────────────────────

    def save(self):
        with open(self.path, "w") as f:
            json.dump({
                "artifacts": [a.to_dict() for a in self.artifacts],
                "observations": self.observations,
                "counter": self._counter,
            }, f, ensure_ascii=False, indent=2)

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.artifacts = [Artifact(**a) for a in data.get("artifacts", [])]
                self.observations = data.get("observations", [])
                self._counter = data.get("counter", 0)
            except (json.JSONDecodeError, TypeError):
                pass
