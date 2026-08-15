"""Community Environment — the shared information space.

Characters are energy beings. Their world is a structured information field
composed of Nodes — spaces they can inhabit, modify, and create.

Nodes affect what activities are possible and how effective they are.
Characters can reshape their environment, and the environment shapes them back.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Node:
    """A structured information space within the community."""
    id: str
    type: str               # study_chamber | commons | archive | garden | workshop
    name: str
    description: str
    created_by: str = "community"
    aesthetics: str = ""
    mutable: bool = True

    # State
    occupants: list = field(default_factory=list)
    echoes: list = field(default_factory=list)     # lingering thoughts
    contents: list = field(default_factory=list)    # stored knowledge/artifacts
    resources: dict = field(default_factory=dict)   # available tools/resources
    connections: list = field(default_factory=list) # connected node IDs

    # Modifiers — how this node affects activities
    modifiers: dict = field(default_factory=lambda: {
        "focus": 0.0,           # % boost to study quality
        "social_energy": 0.0,   # % reduction in social energy cost
        "energy_recovery": 0.0, # % boost to rest recovery
        "inspiration_rate": 0.0,# % boost to idle thought frequency
        "computation_speed": 0.0,
    })

    def get_available_activities(self) -> list:
        """Activities that can be performed in this node."""
        activity_map = {
            "study_chamber": ["deep_study", "computation", "writing"],
            "commons": ["discussion", "gathering", "debate", "casual_talk"],
            "archive": ["research", "reading", "writing"],
            "contemplation_garden": ["rest", "idle_thought", "reflection", "entertainment"],
            "workshop": ["run_code", "computation", "numerical_experiment"],
        }
        return activity_map.get(self.type, ["rest"])

    def apply_modifiers(self, activity: str) -> dict:
        """Return modifier effects for an activity in this node."""
        effects = {}
        if activity in ("deep_study", "computation", "writing"):
            effects["focus_boost"] = self.modifiers.get("focus", 0)
        if activity in ("discussion", "gathering", "debate"):
            effects["energy_discount"] = self.modifiers.get("social_energy", 0)
        if activity == "rest":
            effects["recovery_boost"] = self.modifiers.get("energy_recovery", 0)
        if activity == "idle_thought":
            effects["frequency_boost"] = self.modifiers.get("inspiration_rate", 0)
        return effects

    def add_echo(self, thought: str, author: str):
        """Leave a lingering thought in this node."""
        self.echoes.append({"author": author, "content": thought})
        if len(self.echoes) > 20:
            self.echoes = self.echoes[-20:]

    def get_echoes(self, count: int = 3) -> str:
        """Get recent echoes for context."""
        recent = self.echoes[-count:]
        if not recent:
            return ""
        return "\n".join(f"「{e['author']}曾在此留下: {e['content'][:60]}」" for e in recent)

    def add_content(self, item: str, item_type: str = "note"):
        """Deposit knowledge/artifact in this node."""
        self.contents.append({"type": item_type, "content": item})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "name": self.name,
            "description": self.description, "created_by": self.created_by,
            "aesthetics": self.aesthetics, "mutable": self.mutable,
            "occupants": self.occupants, "echoes": self.echoes,
            "contents": self.contents, "connections": self.connections,
            "modifiers": self.modifiers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Node":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Environment:
    """The community's shared information space."""

    def __init__(self, path: str = None, characters: dict = None):
        self.nodes: dict[str, Node] = {}
        self.character_locations: dict[str, str] = {}  # char_name -> node_id
        self.path = path

        if path and os.path.exists(path):
            self._load()
            if characters:
                self.ensure_cast(characters)
        else:
            self._init_layout(characters)

    def _shared_nodes(self) -> list:
        return [
            Node("commons", "commons", "中央大厅",
                 "圆形空间。中央共享白板上留着所有人的笔迹与未完成的推导。",
                 created_by="community"),
            Node("garden", "contemplation_garden", "静思园",
                 "空旷的场域。每个人看到的取决于此刻的心境。",
                 modifiers={"energy_recovery": 0.30, "inspiration_rate": 0.25}),
            Node("archive", "archive", "知识库",
                 "研究成果与文献笔记的汇聚之地。书架会自己重新排列。",
                 modifiers={"inspiration_rate": 0.10}),
            Node("workshop", "workshop", "计算工坊",
                 "共享计算资源池。实验输出可以直接投到大厅白板。",
                 modifiers={"computation_speed": 0.20}),
        ]

    @staticmethod
    def _study_node_for(name: str, config: dict | None = None) -> Node:
        """Build a study chamber from character craft/domains — no lore hardcoding."""
        cfg = config or {}
        soul = cfg.get("soul") or {}
        craft = (soul.get("craft") or cfg.get("craft") or cfg.get("community_role") or "").strip()
        domains = cfg.get("domains") or []
        if isinstance(domains, str):
            domains = [domains]
        if not domains and cfg.get("domain"):
            domains = [cfg.get("domain")]
        label = ", ".join(str(d).replace("_", " ") for d in domains[:3] if d)
        nid = f"{name.lower().replace(' ', '_')}_study"
        desc = f"{name} 的工作室。"
        if label:
            desc += f" 草稿与笔记围绕: {label}。"
        if craft:
            desc += f" 气质：{craft[:100]}"
        mode = (cfg.get("cognitive") or {}).get("primary_mode") or ""
        aesthetics = {
            "computational": "终端、参数表、被划掉的误差曲线",
            "visual": "草图、密度图、几何碎片",
            "analogical": "对照表、跨领域箭头",
            "symbolic": "公式墙、被圈出的引理",
            "narrative": "时间线与情节式笔记",
        }.get(mode, "未完成的推导与摊开的文献")
        return Node(
            nid, "study_chamber", f"{name} 的工作室",
            desc, created_by=name, aesthetics=aesthetics,
            modifiers={"focus": 0.20, "energy_cost": -0.08},
        )

    def _init_layout(self, characters: dict = None):
        """Shared spaces + one study per character (cast-driven)."""
        for n in self._shared_nodes():
            self.nodes[n.id] = n

        chars = characters or {}
        for name, char in chars.items():
            cfg = getattr(char, "config", None) or (char if isinstance(char, dict) else {})
            study = self._study_node_for(name, cfg)
            self.nodes[study.id] = study
            self.character_locations[name] = study.id

        # Connect everything to commons; archive↔workshop
        for nid, node in self.nodes.items():
            if nid == "commons":
                continue
            if "commons" not in node.connections:
                node.connections.append("commons")
            if nid not in self.nodes["commons"].connections:
                self.nodes["commons"].connections.append(nid)
        if "archive" in self.nodes and "workshop" in self.nodes:
            if "workshop" not in self.nodes["archive"].connections:
                self.nodes["archive"].connections.append("workshop")
            if "archive" not in self.nodes["workshop"].connections:
                self.nodes["workshop"].connections.append("archive")

        # Orphans without a room start in commons
        for name in chars:
            if name not in self.character_locations:
                self.character_locations[name] = "commons"

    def ensure_cast(self, characters: dict):
        """Add missing study rooms / placements when cast changes or file is stale."""
        if "commons" not in self.nodes:
            for n in self._shared_nodes():
                self.nodes.setdefault(n.id, n)
        for name, char in (characters or {}).items():
            cfg = getattr(char, "config", None) or {}
            study = self._study_node_for(name, cfg)
            if study.id not in self.nodes:
                self.nodes[study.id] = study
                if "commons" in self.nodes:
                    study.connections.append("commons")
                    if study.id not in self.nodes["commons"].connections:
                        self.nodes["commons"].connections.append(study.id)
            if name not in self.character_locations:
                self.character_locations[name] = study.id

    # ─── Character Movement ────────────────────────────────────

    def move_character(self, char_name: str, node_id: str) -> bool:
        """Move a character to a node. Returns False if node doesn't exist."""
        if node_id not in self.nodes:
            return False

        old = self.character_locations.get(char_name)
        if old and old in self.nodes:
            if char_name in self.nodes[old].occupants:
                self.nodes[old].occupants.remove(char_name)

        self.nodes[node_id].occupants.append(char_name)
        self.character_locations[char_name] = node_id
        return True

    def get_location(self, char_name: str) -> Optional[Node]:
        """Get the node a character is currently in."""
        node_id = self.character_locations.get(char_name)
        if node_id:
            return self.nodes.get(node_id)
        return None

    def get_occupants(self, node_id: str) -> list:
        """Get characters currently in a node."""
        if node_id in self.nodes:
            return self.nodes[node_id].occupants
        return []

    # ─── Node Operations ──────────────────────────────────────

    def create_node(self, char_name: str, node_id: str, node_type: str,
                    name: str, description: str, aesthetics: str = "") -> Optional[Node]:
        """A character creates a new node. Costs significant energy."""
        if node_id in self.nodes:
            return None  # already exists

        modifiers = {}
        if node_type == "study_chamber":
            modifiers = {"focus": 0.20}
        elif node_type == "contemplation_garden":
            modifiers = {"energy_recovery": 0.30, "inspiration_rate": 0.20}

        node = Node(node_id, node_type, name, description,
                     created_by=char_name, aesthetics=aesthetics,
                     modifiers=modifiers)
        self.nodes[node_id] = node

        # Auto-connect to commons
        if "commons" in self.nodes:
            self.nodes["commons"].connections.append(node_id)
            node.connections.append("commons")

        return node

    def modify_node(self, char_name: str, node_id: str,
                    new_description: str = None, new_aesthetics: str = None,
                    new_modifiers: dict = None) -> bool:
        """Modify an existing node. Only mutable nodes can be changed."""
        if node_id not in self.nodes:
            return False
        node = self.nodes[node_id]
        if not node.mutable and node.created_by != char_name:
            return False

        if new_description:
            node.description = new_description
        if new_aesthetics:
            node.aesthetics = new_aesthetics
        if new_modifiers:
            node.modifiers.update(new_modifiers)
        return True

    def deposit(self, char_name: str, node_id: str, content: str, 
                content_type: str = "note") -> bool:
        """Deposit knowledge into a node."""
        if node_id not in self.nodes:
            return False
        self.nodes[node_id].add_content(content, content_type)
        return True

    def leave_echo(self, char_name: str, node_id: str, thought: str) -> bool:
        """Leave a lingering thought in a node."""
        if node_id not in self.nodes:
            return False
        self.nodes[node_id].add_echo(thought, char_name)
        return True

    # ─── Context for Prompts ──────────────────────────────────

    def get_location_context(self, char_name: str) -> str:
        """Get environmental context for a character's current location."""
        node = self.get_location(char_name)
        if node is None:
            return ""

        parts = [f"你在「{node.name}」: {node.description}"]
        echoes = node.get_echoes(2)
        if echoes:
            parts.append(f"这里的回响:\n{echoes}")
        if node.contents:
            lines = []
            for item in node.contents[-6:]:
                if isinstance(item, dict):
                    body = (item.get("content") or "").strip()
                    kind = item.get("type") or "note"
                else:
                    body = str(item).strip()
                    kind = "note"
                if body:
                    lines.append(f"- [{kind}] {body[:160]}")
            if lines:
                parts.append("这里能翻到的材料:\n" + "\n".join(lines))
        occupants = [o for o in node.occupants if o != char_name]
        if occupants:
            parts.append(f"这里还有: {', '.join(occupants)}")

        return "\n".join(parts)

    # ─── Persistence ──────────────────────────────────────────

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({
                "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
                "character_locations": self.character_locations,
            }, f, ensure_ascii=False, indent=2)

    def _load(self):
        with open(self.path) as f:
            data = json.load(f)
        for nid, ndata in data.get("nodes", {}).items():
            self.nodes[nid] = Node.from_dict(ndata)
        self.character_locations = data.get("character_locations", {})
