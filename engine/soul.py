"""Soul v2 — personality anchor, not a research scrapbook.

Schema only. All identity content comes from world YAML.
World-agnostic: no domain dictionaries, no topic heuristics.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional

import yaml


SOUL_VERSION = "2.0"

# Log / tool lines — format filters only (not research topics)
_JUNK_MOMENT = re.compile(
    r"(使用\w+获得发现|代码运行|论文已保存|stdout|找到\s*\d+\s*篇|dry_run|ToolResult|"
    r"run_code|write_paper|search_arxiv|read_arxiv|search_web)",
    re.I,
)

_MODE_DESC = {
    "visual": "Thinks in shapes, densities, and geometric pictures before symbols",
    "symbolic": "Thinks in symbols and formulas; precision over rhetoric",
    "analogical": "Thinks by cross-domain analogy; hunts for isomorphism",
    "narrative": "Thinks in stories and turning points",
    "computational": "Thinks by computing examples first, then believing",
}

_DEFENSE_DESC = {
    "intellectualization": "Under challenge, pulls the talk back to verifiable technical detail",
    "rationalization": "Under challenge, first defends the existing method as reasonable",
    "humor": "Defuses tension with light self-mockery, then returns to the point",
    "displacement": "When threatened, steers toward territory where they feel safer",
    "sublimation": "Channels friction into creative or formal work",
}


def empty_soul(name: str = "") -> dict:
    return {
        "soul_version": SOUL_VERSION,
        "name": name,
        "identity": {
            "craft": "",
            "who_i_am": "",
            "core_belief": "",
            "how_i_think": "",
            "how_i_protect": "",
            "what_drives_me": "",
            "voice": [],
            # Intellectual territories: seeds from YAML; grows as life opens new fields
            "seed_domains": [],
            "domains": [],
            "vocation": "",           # e.g. research — injected from world
            "vocation_stance": "",    # how this vocation works (not a problem)
            "vocation_traits": [],    # shared researcher habits (not a biography)
        },
        "bonds": {},
        "orientation": {
            "current_focus": "",
            "open_question": "",
            "tensions": [],
            "recently_opened": [],  # domains newly opened (short log)
        },
        "skills": {},
        "reflections": [],
        "milestones": [],
        "meta": {
            "seeded_from": "",
            "created_at": "",
            "last_calibrated_day": 0,
        },
        "recent_murmurs": [],
    }


def _first_sentence(text: str, max_len: int = 160) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in text:
            text = text.split(sep)[0] + (sep if sep in "。！？" else "")
            break
    return text[:max_len].strip()


def _identity_blurb(text: str, max_len: int = 280) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    parts: list[str] = []
    rest = text
    for _ in range(2):
        cut = -1
        sep_used = ""
        for sep in (".", "!", "?", "。", "！", "？"):
            i = rest.find(sep)
            if i != -1 and (cut == -1 or i < cut):
                cut, sep_used = i, sep
        if cut == -1:
            parts.append(rest)
            break
        parts.append(rest[: cut + len(sep_used)])
        rest = rest[cut + len(sep_used) :].strip()
        if not rest:
            break
    return "".join(parts).strip()[:max_len]


def _clip(text: str, n: int) -> str:
    return " ".join((text or "").split())[:n].strip()


_DOMAIN_CUT = re.compile(r"\s*[—–―]\s*|\s+--\s+|\s*\(|（")
_DOMAIN_META = re.compile(
    r"(only if| lasting |if a |when |若持续|暂不|则记录|only when)",
    re.I,
)
_DOMAIN_SENTENCEY = re.compile(
    r"\b(if|only|when|unless|should|must|because)\b",
    re.I,
)
_REFLECTION_NUM = re.compile(r"^(\d+[\.\)]\s*)+")
_REFLECTION_BOILER = re.compile(
    r"^(?:我的)?核心洞见是?[：:]\s*|"
    r"^My core insight is[:：]?\s*|"
    r"^The core insight is[:：]?\s*",
    re.I,
)


def _normalize_domain(raw: str) -> str | None:
    """Turn LLM/domain deltas into a short english slug, or reject."""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return None
    text = _DOMAIN_CUT.split(text, maxsplit=1)[0].strip()
    if not text or _DOMAIN_META.search(text):
        return None
    if re.search(r"[\u4e00-\u9fff]", text):
        return None
    # Phrase → snake_case; keep existing snake/slash forms
    slug = text.lower().replace("/", "_").replace("-", "_")
    slug = re.sub(r"[\s]+", "_", slug)
    slug = re.sub(r"[^a-z0-9_+]", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if len(slug) < 3 or len(slug) > 40:
        return None
    words = [w for w in slug.replace("+", "_").split("_") if w]
    if len(words) >= 6 and _DOMAIN_SENTENCEY.search(" ".join(words)):
        return None
    return slug


def _clean_reflection(statement: str) -> str:
    """Strip numbering / insight boilerplate / markdown bold before clipping."""
    text = " ".join(str(statement or "").split()).strip()
    if not text:
        return ""
    text = text.replace("**", "")
    for _ in range(3):
        nxt = _REFLECTION_NUM.sub("", text).strip()
        nxt = _REFLECTION_BOILER.sub("", nxt).strip()
        if nxt == text:
            break
        text = nxt
    return _first_sentence(text, 140)


def normalize_domains(config: dict) -> list[str]:
    """Collect seed domains from domains[] / domain / soul.domains.

    If `domains` is present (even as []), it is authoritative — do not also
    force `domain:` into the seed list. That lets worlds start with an empty
    living toolbox and open tools at runtime.
    """
    raw: list = []
    has_domains_key = "domains" in config
    if isinstance(config.get("domains"), list):
        raw.extend(config["domains"])
    elif isinstance(config.get("domains"), str) and config["domains"].strip():
        raw.append(config["domains"].strip())
    soul_dom = (config.get("soul") or {}).get("domains") or (config.get("soul") or {}).get("seed_domains")
    if isinstance(soul_dom, list):
        raw.extend(soul_dom)
    if not has_domains_key:
        d = config.get("domain")
        if isinstance(d, list):
            raw.extend(d)
        elif isinstance(d, str) and d.strip():
            raw.append(d.strip())
    out: list[str] = []
    seen = set()
    for item in raw:
        s = _normalize_domain(str(item)) or str(item).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out[:12]


class SoulFile:
    """A character's personality anchor — evolves slowly."""

    def __init__(self, path: str):
        self.path = path
        self.data: dict = {}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._load_or_init()

    def _load_or_init(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                raw = yaml.safe_load(f) or {}
            self.data = self._migrate(raw)
        else:
            self.data = empty_soul()
            self.data["meta"]["created_at"] = datetime.now().isoformat()

    def _migrate(self, raw: dict) -> dict:
        if raw.get("soul_version") == SOUL_VERSION and "identity" in raw:
            base = empty_soul(raw.get("name", ""))
            base.update({k: raw.get(k, base.get(k)) for k in base})
            base["identity"] = {**empty_soul()["identity"], **(raw.get("identity") or {})}
            base["orientation"] = {
                **empty_soul()["orientation"],
                **(raw.get("orientation") or {}),
            }
            base["meta"] = {**empty_soul()["meta"], **(raw.get("meta") or {})}
            sk = raw.get("skills")
            base["skills"] = sk if isinstance(sk, dict) else {}
            return base

        out = empty_soul(raw.get("name", ""))
        essence = raw.get("essence") or {}
        out["identity"]["core_belief"] = essence.get("core_belief") or ""
        out["identity"]["how_i_think"] = essence.get("intellectual_style") or ""
        out["identity"]["who_i_am"] = essence.get("emotional_pattern") or ""

        for u in (raw.get("understanding") or [])[-3:]:
            insight = _first_sentence(u.get("insight", ""), 120)
            if insight:
                out["reflections"].append({
                    "day": u.get("day", 0),
                    "about": "work",
                    "statement": insight,
                    "confidence": float(u.get("confidence") or 0.5),
                })

        for m in (raw.get("witnessed_moments") or [])[-5:]:
            content = m.get("content", "") if isinstance(m, dict) else str(m)
            if content and not _JUNK_MOMENT.search(content):
                out["milestones"].append({
                    "day": 0,
                    "moment": _first_sentence(content, 80),
                })

        for name, rel in (raw.get("relationships_deep") or {}).items():
            if isinstance(rel, dict) and rel.get("bond"):
                out["bonds"][name] = {
                    "stance": rel.get("bond", "")[:120],
                    "history": list(rel.get("history") or [])[-5:],
                }

        questions = (raw.get("knowledge_evolved") or {}).get("questions") or []
        if questions:
            out["orientation"]["open_question"] = _first_sentence(str(questions[-1]), 120)

        out["meta"]["created_at"] = datetime.now().isoformat()
        out["meta"]["migrated_from"] = "v1"
        return out

    def init_from_config(self, name: str, config: dict, world_name: str = ""):
        """Seed from character YAML. Prefer explicit soul:/orientation:; else field fallbacks.

        identity.*  = who they are (stable)
        orientation.* = what occupies them now (mutable)
        Never copy research.project / obsession into core_belief.
        """
        self.data["name"] = name
        self.data["soul_version"] = SOUL_VERSION
        ident = self.data.setdefault("identity", empty_soul()["identity"])
        for k, v in empty_soul()["identity"].items():
            ident.setdefault(k, v if not isinstance(v, list) else list(v))

        soul_cfg = config.get("soul") or {}
        orient_cfg = config.get("orientation") or {}

        def fill(key: str, value: str):
            value = (value or "").strip()
            if value and not (ident.get(key) or "").strip():
                ident[key] = value

        fill("craft", soul_cfg.get("craft") or config.get("craft") or "")
        fill("who_i_am", soul_cfg.get("who_i_am") or "")
        fill("core_belief", soul_cfg.get("core_belief") or "")
        fill("how_i_think", soul_cfg.get("how_i_think") or "")
        fill("how_i_protect", soul_cfg.get("how_i_protect") or "")
        fill("what_drives_me", soul_cfg.get("what_drives_me") or "")
        fill("vocation", soul_cfg.get("vocation") or config.get("vocation") or "")
        fill("vocation_stance", soul_cfg.get("vocation_stance") or "")
        if soul_cfg.get("vocation_traits") and not ident.get("vocation_traits"):
            traits = soul_cfg.get("vocation_traits") or []
            if isinstance(traits, str):
                traits = [traits]
            ident["vocation_traits"] = [str(t).strip()[:160] for t in traits if str(t).strip()][:10]
        if soul_cfg.get("voice") and not ident.get("voice"):
            ident["voice"] = [str(v)[:100] for v in soul_cfg["voice"][:4]]

        # Domain landscape: seeds from YAML; living domains start as seeds
        seeds = normalize_domains(config)
        if soul_cfg.get("seed_domains"):
            seeds = normalize_domains({"domains": soul_cfg["seed_domains"]}) or seeds
        if seeds and not ident.get("seed_domains"):
            ident["seed_domains"] = list(seeds)
        if seeds and not ident.get("domains"):
            ident["domains"] = list(seeds)
        elif ident.get("seed_domains") and not ident.get("domains"):
            ident["domains"] = list(ident["seed_domains"])

        bonds = self.data.setdefault("bonds", {})
        for target, rel in (soul_cfg.get("bonds") or {}).items():
            if target in bonds:
                continue
            if isinstance(rel, dict):
                stance = (rel.get("stance") or "").strip()
                hist = list(rel.get("history") or [])[-5:]
            else:
                stance = str(rel).strip()
                hist = []
            if stance:
                bonds[target] = {"stance": stance[:140], "history": hist}

        if not (ident.get("who_i_am") or "").strip():
            fill("who_i_am", _identity_blurb(config.get("self_concept") or "", 280))

        if not (ident.get("core_belief") or "").strip():
            seed = (config.get("seed") or "").strip()
            drives = config.get("drives") or {}
            epistemic = drives.get("epistemic") or drives.get("epistemic_motive") or ""
            if isinstance(epistemic, (int, float)):
                epistemic = ""
            else:
                epistemic = str(epistemic).strip()
            mental_models = config.get("mental_models") or []
            mm0 = str(mental_models[0]).strip() if mental_models else ""
            belief = seed or epistemic or mm0
            if not belief and config.get("self_concept"):
                belief = _first_sentence(config["self_concept"], 120)
            fill("core_belief", belief)

        if not (ident.get("craft") or "").strip():
            role = (config.get("community_role") or "").strip()
            doms = ident.get("domains") or normalize_domains(config)
            label = ", ".join(doms[:3]) if doms else (config.get("domain") or "")
            fill("craft", role or (f"Practitioner spanning {label}" if label else ""))

        if not (ident.get("how_i_think") or "").strip():
            mode = (config.get("cognitive") or {}).get("primary_mode") or ""
            fill("how_i_think", _MODE_DESC.get(mode, mode))

        if not (ident.get("how_i_protect") or "").strip():
            defense = config.get("defense") or {}
            dtext = _DEFENSE_DESC.get(defense.get("primary") or "", "")
            trigger = (defense.get("trigger_sensitivity") or "").strip()
            if dtext and trigger:
                fill("how_i_protect", f"{dtext}; especially when: {_clip(trigger, 80)}")
            elif dtext:
                fill("how_i_protect", dtext)

        if not (ident.get("what_drives_me") or "").strip():
            jtbd = config.get("jtbd") or {}
            drives = config.get("drives") or {}
            bits = []
            if isinstance(jtbd.get("emotional"), str) and jtbd["emotional"].strip():
                bits.append(_clip(jtbd["emotional"], 90))
            ach = drives.get("achievement")
            if isinstance(ach, str) and ach.strip():
                bits.append(_clip(ach, 90))
            if bits:
                fill("what_drives_me", "; ".join(bits[:2]))

        if not ident.get("voice"):
            voice = config.get("voice") or []
            if voice:
                ident["voice"] = [str(v)[:100] for v in voice[:4]]

        for rel in config.get("relationships") or []:
            target = rel.get("target")
            if not target or target in bonds:
                continue
            stance = (rel.get("true_feeling") or rel.get("surface") or "").strip()
            if stance:
                bonds[target] = {"stance": stance[:140], "history": []}

        orient = self.data.setdefault("orientation", empty_soul()["orientation"])
        research = config.get("research") or {}

        if orient_cfg.get("current_focus") and not orient.get("current_focus"):
            orient["current_focus"] = _clip(orient_cfg["current_focus"], 160)
        if orient_cfg.get("open_question") and not orient.get("open_question"):
            orient["open_question"] = _clip(orient_cfg["open_question"], 160)
        if orient_cfg.get("tensions") and not orient.get("tensions"):
            orient["tensions"] = [str(x)[:80] for x in orient_cfg["tensions"][:3]]
        orient.setdefault("recently_opened", [])

        if not orient.get("current_focus"):
            orient["current_focus"] = _clip(
                research.get("project") or research.get("obsession") or "", 160
            )
        if not orient.get("open_question"):
            orient["open_question"] = _clip(research.get("stuck_point") or "", 160)

        meta = self.data.setdefault("meta", empty_soul()["meta"])
        if not meta.get("created_at"):
            meta["created_at"] = datetime.now().isoformat()
        if world_name:
            meta["seeded_from"] = world_name

        from engine.skills import open_skill

        book = self.data.setdefault("skills", {})
        if not isinstance(book, dict):
            book = {}
            self.data["skills"] = book
        raw_skills = config.get("skills") or []
        if isinstance(raw_skills, dict):
            for sid, rec in raw_skills.items():
                if sid in book:
                    continue
                if isinstance(rec, dict) and rec.get("id"):
                    book[sid] = rec
                else:
                    open_skill(book, str(sid), day=1)
        else:
            for sid in raw_skills:
                open_skill(book, str(sid), day=1)

        self.save()

    def update_bond(self, target: str, stance: str = "", history_note: str = "", day: int = 0):
        if not target:
            return
        bonds = self.data.setdefault("bonds", {})
        entry = bonds.setdefault(target, {"stance": "", "history": []})
        if stance:
            entry["stance"] = stance[:140]
        if history_note:
            note = history_note[:100]
            if day:
                note = f"Day{day}: {note}"
            entry.setdefault("history", []).append(note)
            entry["history"] = entry["history"][-5:]
        self.save()

    def set_orientation(
        self,
        focus: str = "",
        question: str = "",
        tensions: Optional[list] = None,
    ):
        orient = self.data.setdefault("orientation", empty_soul()["orientation"])
        if focus:
            orient["current_focus"] = focus[:160]
        if question:
            orient["open_question"] = question[:160]
        if tensions is not None:
            orient["tensions"] = [str(t)[:80] for t in tensions[:3]]
        self.save()

    def add_reflection(
        self,
        statement: str,
        about: str = "self",
        day: int = 0,
        confidence: float = 0.5,
    ):
        statement = _clean_reflection(statement)
        if not statement or _JUNK_MOMENT.search(statement):
            return False
        refs = self.data.setdefault("reflections", [])
        prefix = statement[:40]
        for prev in refs[-3:]:
            prev_s = (prev.get("statement") or "")
            if prev_s == statement or (prefix and prev_s.startswith(prefix)):
                return False
        refs.append({
            "day": day,
            "about": about,
            "statement": statement,
            "confidence": float(confidence),
        })
        if len(refs) > 12:
            self.data["reflections"] = refs[-12:]
        self.save()
        return True

    def add_milestone(self, moment: str, day: int = 0) -> bool:
        moment = _first_sentence(moment, 80)
        if not moment or len(moment) < 6:
            return False
        if _JUNK_MOMENT.search(moment):
            return False
        junk_starts = ("代码", "输出", "论文已", "搜索", "[", "找到 ", "stdout", "Tool")
        if moment.startswith(junk_starts):
            return False
        marks = self.data.setdefault("milestones", [])
        if any(m.get("moment") == moment for m in marks):
            return False
        marks.append({"day": day, "moment": moment})
        if len(marks) > 10:
            self.data["milestones"] = marks[-10:]
        self.save()
        return True

    def add_murmur(self, thought: str):
        thought = _first_sentence(thought, 60)
        if not thought:
            return
        murmurs = self.data.setdefault("recent_murmurs", [])
        murmurs.append(thought)
        self.data["recent_murmurs"] = murmurs[-3:]
        self.save()

    def open_domain(self, domain: str, day: int = 0, reason: str = "") -> bool:
        """Add a new intellectual territory. Digital lives may cross human limits."""
        domain = _normalize_domain(domain)
        if not domain:
            return False
        ident = self.data.setdefault("identity", empty_soul()["identity"])
        domains = list(ident.get("domains") or [])
        keys = {d.lower() for d in domains}
        if domain.lower() in keys:
            return False
        if len(domains) >= 16:
            return False
        domains.append(domain)
        ident["domains"] = domains
        orient = self.data.setdefault("orientation", empty_soul()["orientation"])
        recent = list(orient.get("recently_opened") or [])
        note = domain if not reason else f"{domain} ({_clip(reason, 40)})"
        if day:
            note = f"Day{day}: {note}"
        recent.append(note)
        orient["recently_opened"] = recent[-5:]
        log = self.data.setdefault("meta", {}).setdefault("domain_log", [])
        log.append({"day": day, "domain": domain, "reason": _clip(reason, 80)})
        self.data["meta"]["domain_log"] = log[-20:]
        self.save()
        return True

    def open_skill(self, skill_id: str, day: int = 0, world_dir=None) -> bool:
        """Instantiate a catalog template onto this character."""
        from engine.skills import open_skill

        book = self.data.setdefault("skills", {})
        if not isinstance(book, dict):
            book = {}
            self.data["skills"] = book
        if not open_skill(book, skill_id, world_dir=world_dir, day=day):
            return False
        self.save()
        return True

    def practice_skill(
        self,
        skill_id: str,
        move: str = "",
        *,
        note: str = "",
        day: int = 0,
        amount: float = 0.04,
    ) -> bool:
        """Grow an already-open skill after study / read / write / code."""
        from engine.skills import practice_skill

        book = self.data.setdefault("skills", {})
        if not practice_skill(book, skill_id, move, note=note, day=day, amount=amount):
            return False
        self.save()
        return True

    def format_skills(self, phase: str = "") -> str:
        from engine.skills import format_skill_book

        return format_skill_book(self.data.get("skills") or {}, phase=phase)

    def apply_delta(self, updates: dict, day: int = 0) -> list[str]:
        if not updates:
            return []
        applied = []

        for rel in updates.get("relationship_updates") or []:
            target = rel.get("target") or ""
            bond = rel.get("new_bond") or rel.get("stance") or ""
            note = rel.get("history_note") or ""
            if target and (bond or note):
                self.update_bond(target, stance=bond, history_note=note, day=day)
                applied.append(f"bond:{target}")

        q = updates.get("orientation_question") or ""
        if not q:
            qs = updates.get("knowledge_questions") or []
            if qs:
                q = qs[0]
        focus = updates.get("orientation_focus") or ""
        if q or focus:
            self.set_orientation(focus=focus, question=q)
            applied.append("orientation")

        for ref in updates.get("reflections") or []:
            if isinstance(ref, str):
                ok = self.add_reflection(ref, about="self", day=day)
            else:
                ok = self.add_reflection(
                    ref.get("statement", ""),
                    about=ref.get("about", "self"),
                    day=day,
                    confidence=float(ref.get("confidence") or 0.5),
                )
            if ok:
                applied.append("reflection")

        for key, about in (
            ("self_reflection", "self"),
            ("work_reflection", "work"),
        ):
            if updates.get(key):
                if self.add_reflection(updates[key], about=about, day=day):
                    applied.append("reflection")

        moment = updates.get("witnessed_moment") or updates.get("milestone") or ""
        if moment and self.add_milestone(moment, day=day):
            applied.append("milestone")

        for item in updates.get("opened_domains") or updates.get("new_domains") or []:
            if isinstance(item, dict):
                ok = self.open_domain(
                    item.get("domain") or item.get("name") or "",
                    day=day,
                    reason=item.get("reason") or "",
                )
                label = item.get("domain") or item.get("name") or ""
            else:
                ok = self.open_domain(str(item), day=day)
                label = str(item)
            if ok:
                applied.append(f"domain:{label}")

        for sid in updates.get("opened_skills") or []:
            label = sid.get("id") if isinstance(sid, dict) else str(sid)
            if self.open_skill(str(label), day=day):
                applied.append(f"skill:{label}")

        for item in updates.get("skill_moves") or []:
            if isinstance(item, dict):
                ok = self.practice_skill(
                    item.get("skill") or item.get("id") or "research",
                    item.get("move") or "",
                    note=item.get("note") or "",
                    day=day,
                )
            else:
                ok = self.practice_skill("research", str(item), day=day)
            if ok:
                applied.append("skill_practice")

        return applied

    def get_context_summary(self) -> str:
        name = self.data.get("name", "")
        ident = self.data.get("identity") or {}
        orient = self.data.get("orientation") or {}
        parts = [f"You are {name}."]

        if ident.get("craft"):
            parts.append(f"Craft: {ident['craft'][:220]}")
        seed_doms = ident.get("seed_domains") or []
        live_doms = ident.get("domains") or []
        if live_doms:
            parts.append(f"Domains (living): {', '.join(str(d) for d in live_doms[:8])}")
        if seed_doms and seed_doms != live_doms:
            parts.append(f"Seed domains: {', '.join(str(d) for d in seed_doms[:6])}")
        if ident.get("who_i_am"):
            parts.append(f"Who you are: {ident['who_i_am'][:200]}")
        if ident.get("core_belief"):
            parts.append(f"Core belief: {ident['core_belief'][:160]}")
        if ident.get("how_i_think"):
            parts.append(f"How you think: {ident['how_i_think'][:160]}")
        if ident.get("what_drives_me"):
            parts.append(f"What drives you: {ident['what_drives_me'][:120]}")
        if ident.get("vocation"):
            parts.append(f"Vocation: {ident['vocation']}")
        if ident.get("vocation_stance"):
            parts.append(f"Vocation stance: {ident['vocation_stance'][:240]}")
        traits = ident.get("vocation_traits") or []
        if traits:
            parts.append("Researcher habits: " + " | ".join(str(t)[:70] for t in traits[:5]))
        voice = ident.get("voice") or []
        if voice:
            parts.append("Voice habits: " + " | ".join(str(v)[:80] for v in voice[:3]))

        for target, rel in list((self.data.get("bonds") or {}).items())[:3]:
            stance = (rel or {}).get("stance", "")
            if stance:
                parts.append(f"Toward {target}: {stance[:60]}")

        if orient.get("current_focus"):
            parts.append(f"Current focus (mutable): {orient['current_focus'][:80]}")
        if orient.get("open_question"):
            parts.append(f"Open question: {orient['open_question'][:80]}")
        recent_open = orient.get("recently_opened") or []
        if recent_open:
            parts.append(f"Recently opened domains: {'; '.join(str(x) for x in recent_open[-3:])}")

        book = self.data.get("skills") or {}
        if book:
            bits = []
            for sid, rec in list(book.items())[:4]:
                if not isinstance(rec, dict):
                    continue
                lv = float(rec.get("level") or 0)
                moves = rec.get("moves") or []
                last = f" · {moves[-1]}" if moves else ""
                bits.append(f"{sid} lv {lv:.2f}{last}")
            if bits:
                parts.append("Skills (growing): " + "; ".join(bits))

        refs = self.data.get("reflections") or []
        if refs:
            parts.append(f"Recent reflection: {refs[-1].get('statement', '')[:80]}")

        return "\n".join(parts)

    def get_deep_understanding(self, count: int = 3) -> str:
        refs = (self.data.get("reflections") or [])[-count:]
        if not refs:
            return ""
        lines = []
        for r in refs:
            conf = r.get("confidence", 0.5)
            lines.append(
                f"[Day {r.get('day', '?')}] ({r.get('about', 'self')}, "
                f"conf {conf:.0%}): {r.get('statement', '')}"
            )
        return "\n".join(lines)

    def get_recent_idle_thoughts(self, count: int = 3) -> str:
        murmurs = (self.data.get("recent_murmurs") or [])[-count:]
        if not murmurs:
            return ""
        return "\n".join(f"· {m}" for m in murmurs)

    def add_idle_thought(self, thought: str):
        self.add_murmur(thought)

    def add_witnessed_moment(self, moment: str, day: int = 0):
        self.add_milestone(moment, day=day)

    def add_knowledge(self, category: str, item: str):
        if category in ("question", "questions"):
            q = _first_sentence(item, 120)
            if q and not _JUNK_MOMENT.search(q):
                self.set_orientation(question=q)

    def update_relationship(self, target_name: str, bond: str, history_note: str = ""):
        self.update_bond(target_name, stance=bond, history_note=history_note)

    def update_project(self, goal: str, progress: float, breakthrough: str = ""):
        if breakthrough:
            self.add_reflection(
                f"Breakthrough feel on '{_first_sentence(goal, 40)}': {_first_sentence(breakthrough, 80)}",
                about="work",
            )
        if goal:
            self.set_orientation(focus=goal[:160])

    def add_deep_thought(self, thought) -> None:
        insight = getattr(thought, "understanding", None) or ""
        if isinstance(thought, dict):
            insight = thought.get("understanding") or thought.get("insight") or ""
        day = getattr(thought, "day", 0)
        if isinstance(thought, dict):
            day = thought.get("day", 0)
        conf = getattr(thought, "confidence", 0.5)
        if isinstance(thought, dict):
            conf = thought.get("confidence", 0.5)
        self.add_reflection(insight, about="work", day=day or 0, confidence=float(conf or 0.5))
        oq = getattr(thought, "open_questions", None)
        if isinstance(thought, dict):
            oq = thought.get("open_questions")
        if isinstance(oq, list) and oq:
            self.set_orientation(question=str(oq[0])[:160])
        elif isinstance(oq, str) and oq.strip():
            self.set_orientation(question=oq.strip()[:160])

    def calibrate(self, day: int, recent_summaries: list[str] | None = None) -> Optional[str]:
        ident = self.data.get("identity") or {}
        core = (ident.get("core_belief") or "").strip()
        who = (ident.get("who_i_am") or "").strip()
        if not core and not who:
            return None
        parts = []
        if who:
            parts.append(f"You still see yourself as: {who[:100]}")
        if core:
            parts.append(f"Your core belief: {core[:100]}")
        if recent_summaries:
            parts.append("Hold your own method against recent events; do not be pulled off course.")
        note = " ".join(parts)
        meta = self.data.setdefault("meta", {})
        meta["last_calibrated_day"] = day
        self.save()
        return note

    def save(self):
        self.data["soul_version"] = SOUL_VERSION
        with open(self.path, "w") as f:
            yaml.dump(self.data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


class DailyArchive:
    """Daily compressed summaries for a character."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._ensure_file()

    def _read(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []

    def _write(self, data: list):
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_file(self):
        if not os.path.exists(self.path):
            self._write([])

    def add_day_summary(self, day: int, summary: str, events: list):
        data = self._read()
        data.append({
            "day": day,
            "summary": summary,
            "event_count": len([e for e in events if e.get("actor")]),
            "timestamp": datetime.now().isoformat(),
        })
        self._write(data)

    def get_recent_context(self, days: int = 3) -> str:
        data = self._read()
        recent = data[-days:]
        lines = []
        for entry in recent:
            lines.append(f"[Day {entry['day']}] {entry['summary']}")
        return "\n".join(lines)

    def compress_weekly(self, week_num: int, weekly_summary: str):
        data = self._read()
        cutoff = max(0, len(data) - 7)
        compressed = data[cutoff:]
        data = data[:cutoff]
        data.append({
            "week": week_num,
            "summary": weekly_summary,
            "compressed_days": len(compressed),
            "timestamp": datetime.now().isoformat(),
        })
        self._write(data)
