"""World Builder: auto-expand minimal character configs into full psychology models.

The engine takes sparse user input (just name + domain + seed) and generates
reasonable defaults for personality, cognitive style, defense mechanisms, etc.

Architecture:
  1. Domain Archetypes — default profiles for common domains
  2. Seed Analysis — extract personality cues from seed text
  3. Template Inheritance — merge prototype → character → user overrides
  4. Sociology Derivation — infer community structure from relationships
"""

import random
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Domain Archetypes
# ═══════════════════════════════════════════════════════════════
# Each domain has a "typical" psychological profile. These are
# Bayesian priors — they get overridden by more specific information.

DOMAIN_ARCHETYPES = {
    "mathematics": {
        "personality": {"openness": 7, "conscientiousness": 6, "extraversion": 4, "agreeableness": 4, "neuroticism": 5},
        "cognitive": {"primary_mode": "visual", "secondary_mode": "symbolic", "metacognition": 5, "ambiguity_tolerance": 4},
        "drives": {"autonomy": 7, "competence": 8, "relatedness": 4,
                   "achievement": "Solve a problem that has bothered the field for years",
                   "epistemic": "Obsessed with deep structure hidden under surfaces"},
        "defense": {"primary": "intellectualization", "trigger_sensitivity": "When their methodology is dismissed"},
        "voice_hints": ["Illustrates with domain examples", "Gets more technical when excited", "Pedantic about rigor"],
        "toolkit": ["run_code", "write_paper", "search_arxiv", "search_web"],
    },
    "literature": {
        "personality": {"openness": 9, "conscientiousness": 4, "extraversion": 5, "agreeableness": 6, "neuroticism": 7},
        "cognitive": {"primary_mode": "narrative", "secondary_mode": "analogical", "metacognition": 8, "ambiguity_tolerance": 8},
        "drives": {"autonomy": 8, "competence": 5, "relatedness": 7,
                   "achievement": "Write one sentence that still satisfies them at dawn",
                   "epistemic": "Obsessed with felt truth of experience, not mere fact"},
        "defense": {"primary": "sublimation", "trigger_sensitivity": "When work is called practically worthless"},
        "voice_hints": ["Speaks in images and metaphor", "Cares about the sound of language", "Notices emotional detail"],
        "toolkit": ["write_paper"],
    },
    "philosophy": {
        "personality": {"openness": 9, "conscientiousness": 5, "extraversion": 6, "agreeableness": 3, "neuroticism": 4},
        "cognitive": {"primary_mode": "analogical", "secondary_mode": "symbolic", "metacognition": 9, "ambiguity_tolerance": 7},
        "drives": {"autonomy": 9, "competence": 6, "relatedness": 6,
                   "achievement": "Ask a question nobody framed before — even without an answer",
                   "epistemic": "Addicted to why-questions of meaning, not only causal why"},
        "defense": {"primary": "rationalization", "trigger_sensitivity": "When called insufficiently rigorous"},
        "voice_hints": ["Uses thought experiments", "Questions premises more than conclusions", "Says 'it depends how you define...'"],
        "toolkit": ["write_paper"],
    },
    "science": {
        "personality": {"openness": 7, "conscientiousness": 7, "extraversion": 5, "agreeableness": 5, "neuroticism": 4},
        "cognitive": {"primary_mode": "visual", "secondary_mode": "symbolic", "metacognition": 4, "ambiguity_tolerance": 3},
        "drives": {"autonomy": 6, "competence": 8, "relatedness": 5,
                   "achievement": "Overturn a fashionable theory with one clean experiment",
                   "epistemic": "Never finished asking what rules the world runs on"},
        "defense": {"primary": "intellectualization", "trigger_sensitivity": "When data is doubted without alternative data"},
        "voice_hints": ["Appeals to experiment and data", "Distrusts untested claims", "Says 'let us try it'"],
        "toolkit": ["run_code", "write_paper", "search_arxiv", "search_web"],
    },
    "art": {
        "personality": {"openness": 10, "conscientiousness": 3, "extraversion": 6, "agreeableness": 7, "neuroticism": 8},
        "cognitive": {"primary_mode": "visual", "secondary_mode": "narrative", "metacognition": 7, "ambiguity_tolerance": 9},
        "drives": {"autonomy": 10, "competence": 6, "relatedness": 7,
                   "achievement": "Make something that leaves a viewer silent for three seconds",
                   "epistemic": "Obsessed with beauty that unsettles, not decoration"},
        "defense": {"primary": "sublimation", "trigger_sensitivity": "When work is analyzed instead of felt"},
        "voice_hints": ["Speaks in sensory texture", "Trusts feeling over analysis", "Occasionally poetic"],
        "toolkit": ["write_paper"],
    },
    "custom": {
        "personality": {"openness": 6, "conscientiousness": 5, "extraversion": 5, "agreeableness": 5, "neuroticism": 5},
        "cognitive": {"primary_mode": "symbolic", "metacognition": 5, "ambiguity_tolerance": 5},
        "drives": {"autonomy": 6, "competence": 6, "relatedness": 5,
                   "achievement": "Leave a mark in a domain they chose",
                   "epistemic": "Curiosity about the unknown"},
        "defense": {"primary": "intellectualization", "trigger_sensitivity": "When a core belief is challenged"},
        "voice_hints": [],
        "toolkit": [],
    },
}

# Sub-domain overrides — more specific than the domain archetype
# Example: number_theorist is a mathematician but with higher conscientiousness
SUBDOMAIN_OVERRIDES = {
    "analytic_number_theory": {"personality": {"conscientiousness": 8, "extraversion": 3}},
    "category_theory": {"personality": {"openness": 9, "conscientiousness": 4}, "cognitive": {"primary_mode": "symbolic"}},
    "mathematical_physics": {"personality": {"openness": 8}, "cognitive": {"primary_mode": "analogical"}},
}


# ═══════════════════════════════════════════════════════════════
# Seed Analysis
# ═══════════════════════════════════════════════════════════════
# Extract personality cues from the seed text using simple heuristics.
# This is intentionally simple — the LLM handles the deep characterization.

def analyze_seed(seed: str) -> dict:
    """Extract personality cues from seed text.

    Uses multi-dimensional keyword analysis to build a psychological
    profile from a short character seed.
    """
    cues = {}
    seed_lower = seed.lower()

    # ── Emotional tone → neuroticism & openness ──
    intense_emotion = ["痴迷", "疯狂", "崩溃", "狂喜", "绝望", "执念", "吞噬", "燃烧", 
                       "撕裂", "不可抑制", "日夜", "寝食"]
    melancholic = ["孤独", "寂寞", "沉思", "沉重", "悲", "忧", "愁", "叹", "哀", "独"]
    serene = ["平静", "从容", "淡", "静", "安然", "随", "任", "闲", "云", "水", "禅"]
    exuberant = ["笑", "豪", "放", "狂", "飞", "天", "酒", "醉", "歌", "舞"]

    neuroticism_score = 5
    openness_score = 5

    for w in intense_emotion:
        if w in seed:
            neuroticism_score = min(10, neuroticism_score + 2)
            openness_score = min(10, openness_score + 1)
            break
    for w in melancholic:
        if w in seed:
            neuroticism_score = min(10, neuroticism_score + 1)
            openness_score = min(10, openness_score + 1)
            break
    for w in serene:
        if w in seed:
            neuroticism_score = max(1, neuroticism_score - 2)
            openness_score = min(10, openness_score + 1)
            break
    for w in exuberant:
        if w in seed:
            neuroticism_score = max(1, neuroticism_score - 1)
            openness_score = min(10, openness_score + 2)
            break

    cues["neuroticism"] = neuroticism_score
    cues["openness"] = openness_score

    # ── Social orientation → extraversion ──
    social_high = ["人们", "大家", "广厦", "天下", "众生", "万", "俱", "交流", "辩论", "讨论"]
    social_low = ["独", "孤", "自", "闭", "静坐", "独处", "一人", "无人"]

    extraversion_score = 5
    for w in social_high:
        if w in seed:
            extraversion_score = min(10, extraversion_score + 2)
            break
    for w in social_low:
        if w in seed:
            extraversion_score = max(1, extraversion_score - 2)
            break
    cues["extraversion"] = extraversion_score

    # ── Rigor → conscientiousness ──
    rigor_high = ["严格", "精确", "验证", "证明", "每一步", "不容", "必须", "计算", "算"]
    rigor_low = ["直觉", "模糊", "大概", "也许", "飘", "随", "任"]

    conscientiousness_score = 5
    for w in rigor_high:
        if w in seed:
            conscientiousness_score = min(10, conscientiousness_score + 2)
            break
    for w in rigor_low:
        if w in seed:
            conscientiousness_score = max(1, conscientiousness_score - 2)
            break
    cues["conscientiousness"] = conscientiousness_score

    # ── Conflict stance → agreeableness ──
    conflict_prone = ["摧毁", "打破", "推翻", "挑", "战", "怒", "吼", "不信任", "不屑"]
    peacemaker = ["庇", "护", "安", "解", "融", "和", "一起", "共", "痛", "苦"]

    agreeableness_score = 5
    for w in conflict_prone:
        if w in seed:
            agreeableness_score = max(1, agreeableness_score - 2)
            break
    for w in peacemaker:
        if w in seed:
            agreeableness_score = min(10, agreeableness_score + 2)
            break
    cues["agreeableness"] = agreeableness_score

    return cues


# ═══════════════════════════════════════════════════════════════
# Persona variation — add individuality within same domain
# ═══════════════════════════════════════════════════════════════

def apply_individual_variation(profile: dict, seed: str, index: int) -> dict:
    """Add subtle random variations so characters in the same domain aren't identical.

    Uses deterministic random based on seed hash + index to ensure reproducibility.
    """
    import hashlib
    seed_bytes = (seed + str(index)).encode()
    seed_int = int(hashlib.md5(seed_bytes).hexdigest()[:8], 16)
    rng = random.Random(seed_int)

    result = dict(profile)

    # Vary each OCEAN dimension by ±1-2
    for dim in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
        if dim in result:
            variation = rng.randint(-2, 2)
            result[dim] = max(1, min(10, result[dim] + variation))

    return result


# ═══════════════════════════════════════════════════════════════
# World Builder
# ═══════════════════════════════════════════════════════════════

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def expand_character(char_config: dict, world_domain: str) -> dict:
    """Expand a minimal character config into a full psychology model.

    Args:
        char_config: Raw character config from YAML (may be minimal)
        world_domain: The world's primary domain (used for archetype defaults)

    Returns:
        Expanded character config with all psychology fields filled in.
    """
    result = dict(char_config)  # Start with user's input

    # Normalize multi-domain seeds (digital lives may span fields)
    doms = result.get("domains")
    if isinstance(doms, str):
        doms = [doms]
    if not doms:
        d = result.get("domain")
        if isinstance(d, list):
            doms = list(d)
        elif d:
            doms = [d]
    if isinstance(doms, list):
        cleaned, seen = [], set()
        for x in doms:
            s = str(x).strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                cleaned.append(s)
        result["domains"] = cleaned[:12]
        if cleaned and not result.get("domain"):
            result["domain"] = cleaned[0]
        elif cleaned and isinstance(result.get("domain"), list):
            result["domain"] = cleaned[0]

    # ── Step 1: Determine effective domain ──
    subdomain = result.get("domain", "")
    if isinstance(subdomain, list):
        subdomain = subdomain[0] if subdomain else ""
    primary_domain = world_domain
    # Try to map subdomain to primary domain
    domain_map = {
        "analytic_number_theory": "mathematics",
        "category_theory": "mathematics",
        "mathematical_physics": "science",
        "algebraic_geometry": "mathematics",
        "poetry": "literature",
        "fiction": "literature",
        "ethics": "philosophy",
        "epistemology": "philosophy",
        "physics": "science",
        "biology": "science",
        "painting": "art",
        "music": "art",
    }
    effective_domain = domain_map.get(subdomain, primary_domain)

    # ── Step 2: Get domain archetype ──
    archetype = DOMAIN_ARCHETYPES.get(effective_domain, DOMAIN_ARCHETYPES["custom"])

    # ── Step 3: Apply subdomain overrides ──
    subdomain_overrides = SUBDOMAIN_OVERRIDES.get(subdomain, {})

    # ── Step 4: Analyze seed for personality cues ──
    seed = char_config.get("seed", "")
    seed_cues = analyze_seed(seed) if seed else {}

    # ── Step 5: Merge: archetype → subdomain → seed cues → user explicit ──
    # Personality (OCEAN)
    base_personality = dict(archetype["personality"])
    base_personality = deep_merge(base_personality, subdomain_overrides.get("personality", {}))
    for dim in base_personality:
        if dim in seed_cues:
            base_personality[dim] = seed_cues[dim]
    user_personality = char_config.get("personality", {})
    if user_personality:
        base_personality = deep_merge(base_personality, user_personality)
    
    # Add individual variation (same domain ≠ same person)
    char_index = hash(char_config.get("name", "")) % 100
    base_personality = apply_individual_variation(base_personality, seed, char_index)
    
    result.setdefault("personality", base_personality)

    # Cognitive
    base_cognitive = dict(archetype["cognitive"])
    base_cognitive = deep_merge(base_cognitive, subdomain_overrides.get("cognitive", {}))
    user_cognitive = char_config.get("cognitive", {})
    if user_cognitive:
        base_cognitive = deep_merge(base_cognitive, user_cognitive)
    result.setdefault("cognitive", base_cognitive)

    # Drives
    base_drives = dict(archetype["drives"])
    user_drives = char_config.get("drives", {})
    if user_drives:
        base_drives = deep_merge(base_drives, user_drives)
    result.setdefault("drives", base_drives)

    # Defense
    base_defense = dict(archetype["defense"])
    user_defense = char_config.get("defense", {})
    if user_defense:
        base_defense = deep_merge(base_defense, user_defense)
    result.setdefault("defense", base_defense)

    # Self-concept: use seed if no explicit self_concept
    if not result.get("self_concept") and seed:
        result["self_concept"] = seed

    # Voice: top-level, else soul.voice, else archetype hints
    voice_hints = archetype.get("voice_hints", [])
    soul_voice = (char_config.get("soul") or {}).get("voice") or []
    user_voice = char_config.get("voice") or soul_voice
    result["voice"] = user_voice if user_voice else voice_hints

    # Research: generate default project if not provided
    if not result.get("research"):
        label = subdomain or effective_domain or "the field"
        result["research"] = {
            "project": f"Explore a new direction in {label}",
            "stuck_point": "No clear breakthrough path yet",
        }

    # Relationships: empty list if not provided
    result.setdefault("relationships", [])

    # Scripts: empty if not provided
    result.setdefault("scripts", {})

    # Generic English soul / orientation if author omitted them
    result["soul"] = _ensure_soul_block(result)
    result["orientation"] = _ensure_orientation_block(result)

    return result


def _ensure_soul_block(char: dict) -> dict:
    """Fill a minimal English soul from existing fields — no domain essays."""
    soul = dict(char.get("soul") or {})
    seed = (char.get("seed") or "").strip()
    domain = (char.get("domain") or "their craft").strip()
    name = char.get("name") or "Someone"

    soul.setdefault("craft", (char.get("craft") or "").strip() or f"Practitioner in {domain}")
    soul.setdefault("who_i_am", (char.get("self_concept") or seed or f"{name}, working in {domain}")[:280])
    soul.setdefault("core_belief", seed or str((char.get("drives") or {}).get("epistemic") or "")[:200])
    mode = (char.get("cognitive") or {}).get("primary_mode") or ""
    soul.setdefault("how_i_think", mode or "Thinks carefully before speaking")
    defense = (char.get("defense") or {}).get("primary") or "intellectualization"
    soul.setdefault("how_i_protect", f"Default defense: {defense}")
    ach = (char.get("drives") or {}).get("achievement") or ""
    soul.setdefault("what_drives_me", str(ach)[:160] if ach else "Leave a trace of original work")
    if not soul.get("voice"):
        soul["voice"] = list(char.get("voice") or [])[:4]
    if "bonds" not in soul:
        bonds = {}
        for rel in char.get("relationships") or []:
            t = rel.get("target")
            if t:
                bonds[t] = {"stance": (rel.get("true_feeling") or rel.get("surface") or "")[:140]}
        soul["bonds"] = bonds
    return soul


def _ensure_orientation_block(char: dict) -> dict:
    orient = dict(char.get("orientation") or {})
    research = char.get("research") or {}
    orient.setdefault("current_focus", (research.get("project") or "")[:160])
    orient.setdefault("open_question", (research.get("stuck_point") or "")[:160])
    orient.setdefault("tensions", list(orient.get("tensions") or [])[:3])
    return orient


def expand_world(raw_config: dict) -> dict:
    """Expand a raw world config into a full simulation-ready config.

    Handles:
    - Flatten meta.name / description onto top-level for engine compatibility
    - Character expansion (minimal → full psychology + soul/orientation)
    - Sociology auto-derivation
    - Tool defaults
    - Inject speech_language onto characters
    """
    result = dict(raw_config)

    meta = raw_config.get("meta") or {}
    if not result.get("name") and meta.get("name"):
        result["name"] = meta["name"]
    if not result.get("description") and meta.get("description"):
        result["description"] = meta["description"]

    world = raw_config.get("world", {})
    world_domain = world.get("domain", raw_config.get("domain", {}).get("primary", "custom"))
    speech = world.get("speech_language") or "zh"

    # ── Expand characters ──
    expanded_chars = []
    for char_cfg in raw_config.get("characters", []):
        if char_cfg.get("$template"):
            # TODO: Load template from prototypes/ directory
            pass
        expanded = expand_character(char_cfg, world_domain)
        if not expanded.get("speech_language"):
            expanded["speech_language"] = speech
        expanded_chars.append(expanded)
    result["characters"] = expanded_chars

    # ── Auto-derive sociology if missing ──
    if "sociology" not in result or not result["sociology"]:
        result["sociology"] = _derive_sociology(expanded_chars)

    # ── Default tools from domain archetype ──
    if "tools" not in result or not result.get("tools"):
        archetype = DOMAIN_ARCHETYPES.get(world_domain, DOMAIN_ARCHETYPES["custom"])
        tool_names = list(archetype.get("toolkit", []))
        # Enclosed worlds should not get web search by default
        if world.get("permeability") == "enclosed":
            tool_names = [t for t in tool_names if t != "search_web"]
        result["tools"] = [{"name": t} for t in tool_names]

    return result


def _derive_sociology(characters: list) -> dict:
    """Auto-derive basic sociology from character relationships."""
    num_chars = len(characters)

    if num_chars <= 2:
        stage = "forming"
    elif num_chars <= 4:
        stage = "storming"
    else:
        stage = "performing"

    has_conflicts = False
    conflict_words = [
        "不安", "威胁", "嫉妒", "竞争", "不服",
        "fear", "threat", "jealous", "rival", "uneasy", "resent",
    ]
    bond_words = [
        "佩服", "欣赏", "尊重", "信任", "喜欢",
        "respect", "admir", "trust", "like", "fond", "rely",
    ]
    for char in characters:
        for rel in char.get("relationships", []):
            feeling = (rel.get("true_feeling") or "").lower()
            if any(w in feeling for w in conflict_words):
                has_conflicts = True

    sociology = {
        "development_stage": stage,
        "norms": {
            "positive": ["Honest exchange", "Critique the argument, not the person"],
            "negative": ["Personal attacks", "Taking credit without acknowledgment"],
        },
        "hierarchy": {
            "social_influence": "Hierarchy not yet settled",
            "tension_zones": ["Methodological differences may spark conflict"] if has_conflicts else [],
        },
        "collective_memory": {
            "key_events": [],
            "unresolved_tensions": [],
        },
    }

    return sociology
