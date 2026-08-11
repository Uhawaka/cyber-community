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

    def __init__(self, path: str = None):
        self.nodes: dict[str, Node] = {}
        self.character_locations: dict[str, str] = {}  # char_name -> node_id
        self.path = path

        if path and os.path.exists(path):
            self._load()
        else:
            self._init_default()

    def _init_default(self):
        """Create the default community layout."""
        defaults = [
            Node("commons", "commons", "中央大厅",
                 "圆形空间。中央共享白板上留着所有人的笔迹。", created_by="community"),
            Node("elias_study", "study_chamber", "Elias 的计算室",
                 "质数标记在数轴上浮动。墙角堆着算到一半的草稿。",
                 created_by="Elias", aesthetics="数值的、密集的、数据构成的河流",
                 modifiers={"focus": 0.20, "energy_cost": -0.10}),
            Node("yuki_study", "study_chamber", "Yuki 的箭头回廊",
                 "无数箭头构成交换图。每一条都是一次逻辑跳转。",
                 created_by="Yuki", aesthetics="抽象的、极简的、箭头搭建的教堂",
                 modifiers={"focus": 0.25, "energy_cost": -0.05}),
            Node("pavel_study", "study_chamber", "Pavel 的实验室",
                 "湍流可视化在旋转。方程写在流动的表面上。",
                 created_by="Pavel", aesthetics="物理的、动态的、风暴中心的涡旋",
                 modifiers={"focus": 0.15, "computation_speed": 0.20}),
            Node("garden", "contemplation_garden", "静思园",
                 "空旷的场域。每个人看到的取决于此刻的心境。",
                 modifiers={"energy_recovery": 0.30, "inspiration_rate": 0.25}),
            Node("archive", "archive", "知识库",
                 "所有研究成果的汇聚之地。书架会自己重新排列。",
                 modifiers={"inspiration_rate": 0.10}),
            Node("workshop", "workshop", "计算工坊",
                 "共享计算资源池。数值实验的结果直接投射到大厅白板。",
                 modifiers={"computation_speed": 0.20}),
        ]
        for n in defaults:
            self.nodes[n.id] = n

        # Default connections
        connections = [
            ("commons", "elias_study"), ("commons", "yuki_study"),
            ("commons", "pavel_study"), ("commons", "garden"),
            ("commons", "archive"), ("commons", "workshop"),
            ("archive", "workshop"),
        ]
        for a, b in connections:
            if a in self.nodes and b in self.nodes:
                self.nodes[a].connections.append(b)
                self.nodes[b].connections.append(a)

        # Initial character locations
        self.character_locations = {
            "Elias": "elias_study",
            "Yuki": "yuki_study",
            "Pavel": "pavel_study",
        }

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
