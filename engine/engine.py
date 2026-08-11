"""Main simulation engine — DES event loop (assembled from mixins).

Modules:
  sim_lifecycle  — bootstrap, run, day boundary
  sim_activity   — activate / spontaneous / study / idle
  sim_social     — collision / gathering / seminar / collab
  sim_world      — observe / tools / env / anonymous events
  sim_cognition  — context injection / memory / deep think
"""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

from engine.events import EventQueue
from engine.character import Character
from engine.llm import LLM
from engine.soul import SoulFile, DailyArchive
from engine.tools import ToolRegistry
from engine.sociology import CommunityEngine
from engine.deep_think import DeepThinkEngine
from engine.environment import Environment
from engine.thought_loop import InnerDialogue
from engine.needs import NeedsState
from engine.mission import MissionBoard
from engine.rich_env import RichEnvironment
from engine.production import ProductionPipeline
from engine.memory import Memory
from engine.collaboration import CollaborationBoard
from engine.anonymous_events import AnonymousEventBoard
from engine.culture import resolve_sociology, resolve_world_frame

from engine.sim_lifecycle import LifecycleMixin
from engine.sim_activity import ActivityMixin
from engine.sim_social import SocialMixin
from engine.sim_world import WorldMixin
from engine.sim_cognition import CognitionMixin


class SimulationEngine(
    LifecycleMixin,
    ActivityMixin,
    SocialMixin,
    WorldMixin,
    CognitionMixin,
):
    """Discrete Event Simulation engine for the community."""

    def __init__(self, config: dict, llm: LLM, memory=None, dry_run: bool = False):
        self.config = config
        self.llm = llm
        self.memory = memory
        self.dry_run = dry_run  # skip external API calls (for smoke tests)

        self.queue = EventQueue()
        self.clock = 0.0  # virtual time
        self.day = 1
        self.running = False

        # Create characters
        self.characters: dict[str, Character] = {}
        self.souls: dict[str, SoulFile] = {}
        self.archives: dict[str, DailyArchive] = {}

        self.world_frame = resolve_world_frame(config)
        permeability = self.world_frame.get("permeability", "connected")
        # In dry_run, use temp dir to avoid contaminating persistent files
        if dry_run:
            self._output_dir = Path(tempfile.mkdtemp(prefix="cc_dryrun_"))
        else:
            self._output_dir = Path("outputs") / config.get("name", "community").replace(" ", "-")
        output_dir = self._output_dir

        for char_cfg in config.get("characters", []):
            name = char_cfg["name"]
            lam = char_cfg.get("autonomy", {}).get("lam", random.uniform(0.5, 1.0))
            char_cfg["_permeability"] = permeability
            self.characters[name] = Character(name, char_cfg, lam=lam)

            soul_path = output_dir / "souls" / f"{name}.yaml"
            soul = SoulFile(str(soul_path))
            soul.init_from_config(
                name,
                char_cfg,
                world_name=self.world_frame.get("name", ""),
            )
            self.souls[name] = soul

            archive_path = output_dir / "archives" / f"{name}.json"
            self.archives[name] = DailyArchive(str(archive_path))

        self.event_log: list[dict] = []

        self.memories: dict[str, Memory] = {}
        for char_cfg in config.get("characters", []):
            name = char_cfg["name"]
            mem_path = output_dir / "memory" / f"{name}.json"
            mem = Memory(str(mem_path))
            has_backstory = any(e.type == "backstory" for e in mem.episodes)
            if not has_backstory:
                mem.seed_backstory(char_cfg)
            self.memories[name] = mem

        tool_configs = config.get("tools", [])
        self.tool_registry = ToolRegistry(tool_configs, output_dir, llm) if tool_configs else None

        self.society = CommunityEngine(
            self.characters,
            sociology_config=resolve_sociology(config),
        )

        self.deep_think = DeepThinkEngine(llm)
        self._event_counts: dict[str, dict] = {}
        self._last_deep_think: dict[str, float] = {}

        self._dialogues: dict[str, InnerDialogue] = {}

        env_path = output_dir / "environment.json"
        self.environment = Environment(str(env_path), characters=self.characters)

        self.rich_env = RichEnvironment(self.environment, self.characters, self.society)

        self.missions = MissionBoard(self.characters)

        self.needs: dict[str, NeedsState] = {}
        for name in self.characters:
            self.needs[name] = NeedsState()

        prod_path = output_dir / "production.json"
        self.production = ProductionPipeline(str(prod_path), llm)

        self.collab = CollaborationBoard()
        self.anonymous = AnonymousEventBoard()

        self._search_history: dict[str, set] = {}

        for name in self.characters:
            self._event_counts[name] = {"study": 0, "collision": 0, "tool": 0}
            self._last_deep_think[name] = 0.0
