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
from engine.culture import format_practice_context, resolve_sociology, resolve_world_frame
from engine.research import research_prompt_block

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

            self.characters[name]._skills_text = self.world_frame.get("skills_text") or {}
            self.characters[name]._research_protocol = research_prompt_block(self.world_frame)
            self.characters[name]._world_practice = format_practice_context(self.world_frame)

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

        self._seed_world_into_memories()

        tool_configs = config.get("tools", [])
        self.tool_registry = (
            ToolRegistry(
                tool_configs,
                output_dir,
                llm,
                world_frame=self.world_frame,
                config=config,
            )
            if tool_configs
            else None
        )

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
        self._deposit_seed_library()

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
            # Anchor to current clock so "hours since last" isn't huge at t≈12
            self._last_deep_think[name] = self.clock

        # Per-slice LLM budget (set by run_slice / live wake)
        self._llm_calls_slice_start = 0
        self._max_llm_calls_slice: int | None = None

    def _llm_budget_ok(self) -> bool:
        """True if another LLM call is allowed in the current slice."""
        if self._max_llm_calls_slice is None:
            return True
        used = getattr(self.llm, "call_count", 0) - self._llm_calls_slice_start
        return used < self._max_llm_calls_slice

    def _deposit_seed_library(self) -> None:
        """Put world.seed_library URLs + seed_readings onto commons/archive/studies.

        Completeness goals:
        - URLs visible as startup shelf
        - Mathematical statements visible as readable text (not just links)
        - Every study chamber gets a starter card (characters spawn there)
        - Commons echo reminds the cast of the founding shelf
        """
        frame = getattr(self, "world_frame", {}) or {}
        library = frame.get("seed_library") or []
        readings = frame.get("seed_readings") or []
        if isinstance(library, str):
            library = [library]
        if isinstance(readings, str):
            readings = [readings]
        if (not library and not readings) or not getattr(self, "environment", None):
            return
        archive = self.environment.nodes.get("archive")
        commons = self.environment.nodes.get("commons")
        already = ""
        for node in (archive, commons):
            if node and node.contents:
                already += " ".join(
                    str((c.get("content") if isinstance(c, dict) else c) or "")
                    for c in node.contents
                )

        def _add(node, text: str, item_type: str, limit: int):
            if not node or not text:
                return
            node.add_content(text[:limit], item_type=item_type)

        for item in library:
            if isinstance(item, dict):
                title = (item.get("title") or item.get("name") or "").strip()
                url = (item.get("url") or item.get("link") or item.get("href") or "").strip()
                note = (item.get("note") or item.get("why") or "").strip()
                text = " · ".join(x for x in (title, url, note) if x)
            else:
                text = str(item).strip()
            if not text or text in already:
                continue
            _add(archive, text, "seed", 400)
            _add(commons, text, "seed", 400)
            already += text

        reading_cards: list[str] = []
        for item in readings:
            if isinstance(item, dict):
                title = (item.get("title") or item.get("name") or "").strip()
                body = (item.get("body") or item.get("text") or item.get("statement") or "").strip()
                source = (item.get("source") or item.get("url") or "").strip()
                text = f"{title}\n{body}" if title else body
                if source:
                    text = f"{text}\n(source: {source})"
            else:
                text = str(item).strip()
            if not text or text[:80] in already:
                continue
            _add(archive, text, "math_reading", 2500)
            _add(commons, text, "math_reading", 1200)
            reading_cards.append(text)
            already += text[:80]

        # Starter card in each study — characters begin there, not in archive.
        shelf_titles = []
        for item in library[:6]:
            if isinstance(item, dict):
                t = (item.get("title") or "").strip()
                u = (item.get("url") or "").strip()
                if t or u:
                    shelf_titles.append(f"- {t}: {u}".strip(": "))
            else:
                shelf_titles.append(f"- {str(item)[:80]}")
        starter = "【社区启动种子】\n"
        if shelf_titles:
            starter += "书架入口:\n" + "\n".join(shelf_titles) + "\n"
        if reading_cards:
            starter += "\n开箱原文（先读这个再扯名词）:\n" + reading_cards[0][:900]
        starter += (
            "\n\n下一步: 认领一条世界级难题 → search_arxiv / read_arxiv 深读 → "
            "打开需要的工具 → 写 Claim。"
        )
        for name in list(getattr(self, "characters", {}) or {}):
            nid = f"{name.lower().replace(' ', '_')}_study"
            study = self.environment.nodes.get(nid)
            if not study:
                continue
            study_blob = " ".join(
                str((c.get("content") if isinstance(c, dict) else c) or "")
                for c in (study.contents or [])
            )
            if "社区启动种子" in study_blob:
                continue
            study.add_content(starter[:2200], item_type="seed_starter")

        if commons:
            echoes = " ".join(str(e.get("content") or "") for e in (commons.echoes or []))
            if "种子书架" not in echoes and "seed shelf" not in echoes.lower():
                commons.add_echo(
                    "白板上钉着种子书架：Clay / 顶刊入口 / 开箱数学原文。"
                    "先读原文与链接，再谈工作。只会甩名词 = 社区无能。",
                    "社区",
                )
            if "种子书架" not in (commons.description or ""):
                commons.description = (
                    (commons.description or "中央大厅。").rstrip()
                    + " 白板上钉着社区启动种子书架与开箱数学原文。"
                )

        try:
            self.environment.save()
        except Exception:
            pass

    def _seed_world_into_memories(self) -> None:
        """Give every character a founding memory of the shared seed shelf."""
        from engine.memory import Episode

        frame = getattr(self, "world_frame", {}) or {}
        library = frame.get("seed_library") or []
        readings = frame.get("seed_readings") or []
        if isinstance(library, str):
            library = [library]
        if isinstance(readings, str):
            readings = [readings]
        if not library and not readings:
            return

        titles = []
        for item in library[:8]:
            if isinstance(item, dict):
                t = (item.get("title") or "").strip()
                u = (item.get("url") or "").strip()
                titles.append(f"{t} ({u})" if u else t)
            else:
                titles.append(str(item)[:100])
        reading_bits = []
        for item in readings[:3]:
            if isinstance(item, dict):
                reading_bits.append(
                    f"{(item.get('title') or '').strip()}: "
                    f"{(item.get('body') or item.get('statement') or '').strip()[:220]}"
                )
            else:
                reading_bits.append(str(item)[:220])
        detail = "社区启动时钉上的种子书架:\n" + "\n".join(f"- {t}" for t in titles if t)
        if reading_bits:
            detail += "\n\n开箱数学原文:\n" + "\n".join(f"- {r}" for r in reading_bits)
        detail += (
            "\n\n规则: 先读原文/链接，自己认领世界级难题，打开需要的工具；"
            "禁止预定专业地盘，禁止只甩名词。"
        )

        for name, mem in (getattr(self, "memories", {}) or {}).items():
            if any("seed_shelf" in (getattr(e, "tags", None) or []) for e in mem.episodes):
                continue
            mem.remember(Episode(
                id=f"{name}_backstory_seed_shelf",
                time=0.0,
                day=-1,
                type="backstory",
                summary="社区种子书架钉上了大厅与知识库",
                detail=detail[:900],
                emotional_valence="curious",
                importance=0.95,
                tags=["seed_shelf", "backstory", "founding"],
            ))
            mem.save()

    def _llm_calls_used(self) -> int:
        return getattr(self.llm, "call_count", 0) - self._llm_calls_slice_start
