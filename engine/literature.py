"""Literature search policy — engine-level, domain-agnostic.

Problem this solves
-------------------
Speech may be Chinese, but *frontier research* is overwhelmingly English
(preprints, top journals, arXiv). Letting models emit Chinese method-sermons
as search queries yields empty arXiv hits and shallow noun-stacking.

Rules (default)
---------------
1. **Frontier channel (arXiv / primary academic web) → English queries.**
2. **Vernacular channel (explanations, local discourse, pedagogy) → Chinese OK**
   when the world allows it (`allow_vernacular`) or the world domain is in
   `vernacular_domains` (e.g. classical Chinese literature).
3. **Bilingual web (optional):** one English frontier query + one Chinese
   explanatory query — never Chinese-only for frontier intent.
4. **Never send CJK slogans to arXiv.** Rewrite via lexicon / Latin tokens /
   world fallback.
5. Worlds may override via `world.literature` without engine forks.

Config shape (optional under world:)
------------------------------------
  literature:
    frontier_language: en          # en (default) | zh (rare)
    allow_vernacular: true         # zh community may search zh for explanations
    bilingual_web: true            # web search emits EN + ZH tracks
    vernacular_domains: []         # domains where zh frontier is legitimate
    fallback_query: "open problems"  # English fallback when rewrite fails
    en_site_hints: []              # optional: ["arxiv.org", "jstor.org"]
    zh_site_hints: []              # optional: ["zhihu.com", "cnki.net"] — soft
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Soft token → English rewrite map (generic + STEM-heavy). Harmless no-ops
# when tokens never appear (poets / alien worlds).
_DEFAULT_LEXICON: list[tuple[tuple[str, ...], str]] = [
    (("riemann", "zeta", "ζ", "零点", "临界线"), "Riemann hypothesis zeta zeros"),
    (("birch", "bsd", "elliptic", "swinnerton"), "Birch Swinnerton-Dyer L-function"),
    (("hodge", "algebraic cycle"), "Hodge conjecture algebraic cycles"),
    (("navier", "stokes"), "Navier-Stokes regularity"),
    (("yang-mills", "mass gap"), "Yang-Mills mass gap"),
    (("arxiv", "preprint"), "recent arXiv preprint"),
    (("llm", "large language", "大模型"), "large language model"),
    (("quant", "alpha", "因子"), "quantitative finance factor model"),
]


@dataclass
class SearchQuery:
    """One concrete lookup the tools / observation pipeline can fire."""

    channel: str  # arxiv | web | web_zh
    text: str
    lang: str  # en | zh
    role: str = "frontier"  # frontier | vernacular | retry
    note: str = ""


@dataclass
class LiteraturePlan:
    intent: str
    frontier_lang: str
    allow_vernacular: bool
    queries: list[SearchQuery] = field(default_factory=list)
    rewritten_from_cjk: bool = False
    policy_note: str = ""


def looks_like_cjk(text: str) -> bool:
    return bool(_CJK_RE.search((text or "").strip()))


def resolve_literature_config(
    world_or_frame: Optional[dict] = None,
    config: Optional[dict] = None,
) -> dict:
    """Merge world.literature with safe defaults."""
    world = {}
    if isinstance(world_or_frame, dict):
        if "literature" in world_or_frame or "domain" in world_or_frame:
            world = world_or_frame
        elif isinstance(world_or_frame.get("world"), dict):
            world = world_or_frame["world"]
    if config and not world:
        world = (config.get("world") or {}) if isinstance(config, dict) else {}

    lit = world.get("literature") if isinstance(world.get("literature"), dict) else {}
    domain = str(world.get("domain") or "").strip().lower()

    # Re-entry: world_frame already carries a resolved literature block
    if (
        "frontier_language" in lit
        and "fallback_query" in lit
        and ("extra_lexicon" in lit or "lexicon" not in lit)
        and "allow_vernacular" in lit
    ):
        out = dict(lit)
        out.setdefault("world_domain", domain)
        out["extra_lexicon"] = lit.get("extra_lexicon") or lit.get("lexicon") or []
        return out

    frontier = str(lit.get("frontier_language") or lit.get("frontier_lang") or "en").lower()
    if frontier not in ("en", "zh"):
        frontier = "en"

    vernacular_domains = lit.get("vernacular_domains") or []
    if isinstance(vernacular_domains, str):
        vernacular_domains = [vernacular_domains]
    vernacular_domains = [str(d).strip().lower() for d in vernacular_domains if str(d).strip()]

    # Classical / local-language fields: zh frontier may be legitimate
    auto_vernacular = domain in {
        "literature", "chinese_literature", "poetry", "philosophy",
        "history", "sinology", "chinese_history",
    }

    allow_vernacular = lit.get("allow_vernacular")
    if allow_vernacular is None:
        allow_vernacular = True  # zh-speaking communes may hunt explanations
    allow_vernacular = bool(allow_vernacular)

    bilingual = lit.get("bilingual_web")
    if bilingual is None:
        bilingual = True
    bilingual = bool(bilingual)

    fallback = (lit.get("fallback_query") or lit.get("fallback") or "").strip()
    if not fallback:
        fallback = {
            "mathematics": "open problems mathematics",
            "physics": "open problems theoretical physics",
            "finance": "quantitative finance research",
            "literature": "literary criticism",
            "philosophy": "philosophy research",
        }.get(domain, "research open problems")

    return {
        "frontier_language": frontier,
        "allow_vernacular": allow_vernacular,
        "bilingual_web": bilingual,
        "vernacular_domains": vernacular_domains,
        "vernacular_frontier_ok": domain in vernacular_domains or auto_vernacular,
        "fallback_query": fallback[:80],
        "en_site_hints": list(lit.get("en_site_hints") or []),
        "zh_site_hints": list(lit.get("zh_site_hints") or []),
        "world_domain": domain,
        "extra_lexicon": lit.get("lexicon") or lit.get("extra_lexicon") or [],
    }


def _latin_keep(text: str) -> str:
    latin = _CJK_RE.sub(" ", text or "")
    latin = re.sub(r"\s+", " ", latin).strip(" .,;:|-")
    return latin


def to_frontier_english(
    query: str,
    focus: str = "",
    *,
    fallback: str = "research open problems",
    extra_lexicon: Optional[list] = None,
) -> tuple[str, bool]:
    """Return (english_query, was_rewritten_from_cjk)."""
    raw = " ".join((query or "").split())
    focus = " ".join((focus or "").split())
    blob = f"{raw} {focus}".lower()
    rewritten = looks_like_cjk(raw)

    if raw and not looks_like_cjk(raw) and len(raw) >= 6:
        cleaned = re.sub(
            r"\s+(survey|OR|journal|recent|arxiv\.org)+\s*$",
            "",
            raw,
            flags=re.I,
        ).strip()
        if cleaned:
            return cleaned[:120], False

    lexicon = list(_DEFAULT_LEXICON)
    for item in extra_lexicon or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            keys, eng = item
            if isinstance(keys, str):
                keys = [keys]
            lexicon.append((tuple(str(k) for k in keys), str(eng)))
        elif isinstance(item, dict):
            keys = item.get("keys") or item.get("from") or []
            eng = item.get("en") or item.get("to") or ""
            if keys and eng:
                if isinstance(keys, str):
                    keys = [keys]
                lexicon.append((tuple(str(k) for k in keys), str(eng)))

    for keys, eng in lexicon:
        if any(k.lower() in blob for k in keys):
            return eng[:120], rewritten

    latin = _latin_keep(f"{focus} {raw}")
    if len(latin) >= 8 and not looks_like_cjk(latin):
        return latin[:120], rewritten

    fb = (fallback or "research open problems").strip()
    return (fb[:120] if fb else "research open problems"), rewritten


def to_vernacular_zh(query: str, focus: str = "", *, fallback: str = "") -> str:
    """Keep or craft a Chinese explanatory query (not for arXiv)."""
    raw = " ".join((query or "").split())
    focus = " ".join((focus or "").split())
    if looks_like_cjk(raw) and len(raw) >= 4:
        # Drop method-sermon connectors a bit
        q = re.sub(r"^(从|把|将).{0,8}(转向|换成|变成)", "", raw)
        q = q.strip(" ，。；、") or raw
        return q[:80]
    # English focus → short zh wrapper for explanatory web search
    seed = _latin_keep(focus or raw) or fallback or "前沿研究"
    return f"{seed} 综述 或 解读"[:80]


def literature_query_hint(
    domains: list | None = None,
    focus: str = "",
    *,
    channel: str = "arxiv",
    lit_cfg: Optional[dict] = None,
) -> str:
    """Prompt hint for the LLM when proposing a search query."""
    cfg = lit_cfg or resolve_literature_config()
    bits = []
    if domains:
        bits.append("domains: " + ", ".join(str(d) for d in domains[:5]))
    if focus:
        bits.append("focus: " + focus[:100])
    extra = (" (" + "; ".join(bits) + ")") if bits else ""

    if channel == "web" and cfg.get("allow_vernacular") and cfg.get("bilingual_web"):
        return (
            "Propose an English frontier literature query (4–12 words)"
            f"{extra}. "
            "Primary query MUST be English (arXiv / top journals / field nouns). "
            "Optional: also set vernacular_zh to a short Chinese explanatory query "
            "for secondary web lookup. "
            "Bad: Chinese-only method sermons as the primary query."
        )
    return (
        "Generate a precise English academic search query (4–12 words)"
        f"{extra}. "
        "MUST be English — frontier literature is indexed in English. "
        "Good: field nouns + problem nouns from the literature. "
        "Bad: Chinese slogans like '从验证转向…作为检验标准'."
    )


def plan_literature_search(
    *,
    intent: str = "frontier",
    channel: str = "arxiv",
    query: str = "",
    focus: str = "",
    domains: list | None = None,
    world_or_frame: Optional[dict] = None,
    config: Optional[dict] = None,
) -> LiteraturePlan:
    """Build a multi-query literature plan for tools / observation.

    intent:
      frontier — primary research trail (default)
      vernacular — explanations / local discourse
      mixed — frontier EN + vernacular ZH on web
    channel:
      arxiv | web | observe
    """
    cfg = resolve_literature_config(world_or_frame, config)
    intent = (intent or "frontier").lower()
    channel = (channel or "arxiv").lower()

    fallback = cfg["fallback_query"]
    en, rewritten = to_frontier_english(
        query,
        focus=focus,
        fallback=fallback,
        extra_lexicon=cfg.get("extra_lexicon"),
    )

    queries: list[SearchQuery] = []
    policy = (
        f"frontier={cfg['frontier_language']}; vernacular_ok={cfg['allow_vernacular']}; "
        f"bilingual_web={cfg['bilingual_web']}"
    )

    if channel in ("arxiv", "observe"):
        # arXiv is always English under default policy
        if cfg["frontier_language"] == "zh" and cfg["vernacular_frontier_ok"]:
            zh = to_vernacular_zh(query, focus, fallback=fallback)
            queries.append(SearchQuery("arxiv", zh, "zh", "frontier", "world allows zh frontier"))
        else:
            queries.append(SearchQuery("arxiv", en, "en", "frontier", "arXiv requires English"))
            if rewritten:
                queries[0].note = "rewrote CJK slogan → English"

    if channel in ("web", "observe", "mixed") or intent == "mixed":
        en_web = en
        hints = cfg.get("en_site_hints") or []
        if hints and "site:" not in en_web.lower():
            site = " OR ".join(f"site:{h}" for h in hints[:3])
            en_web = f"{en_web} {site}"
        queries.append(SearchQuery("web", en_web[:160], "en", "frontier", "English frontier web"))

        want_zh = (
            cfg["allow_vernacular"]
            and cfg["bilingual_web"]
            and intent in ("frontier", "mixed", "vernacular", "observe")
            and channel in ("web", "observe", "mixed")
        )
        if want_zh:
            zh = to_vernacular_zh(query, focus, fallback=en)
            zh_hints = cfg.get("zh_site_hints") or []
            if zh_hints and "site:" not in zh:
                zh = f"{zh} " + " OR ".join(f"site:{h}" for h in zh_hints[:2])
            queries.append(SearchQuery("web_zh", zh[:100], "zh", "vernacular", "Chinese explanatory track"))

    if intent == "vernacular" and cfg["allow_vernacular"]:
        zh = to_vernacular_zh(query, focus, fallback=en)
        queries = [SearchQuery("web_zh", zh[:100], "zh", "vernacular", "vernacular-only intent")]

    # Dedupe
    out, seen = [], set()
    for q in queries:
        key = (q.channel, q.text.lower())
        if key in seen or not q.text.strip():
            continue
        seen.add(key)
        out.append(q)

    return LiteraturePlan(
        intent=intent,
        frontier_lang=cfg["frontier_language"],
        allow_vernacular=cfg["allow_vernacular"],
        queries=out,
        rewritten_from_cjk=rewritten,
        policy_note=policy,
    )


def primary_query(plan: LiteraturePlan, channel: str = "arxiv") -> str:
    """Pick the best query text for a concrete tool call."""
    channel = channel.lower()
    if channel == "arxiv":
        for q in plan.queries:
            if q.channel == "arxiv":
                return q.text
    if channel == "web":
        for q in plan.queries:
            if q.channel == "web":
                return q.text
        for q in plan.queries:
            if q.channel == "web_zh":
                return q.text
    if plan.queries:
        return plan.queries[0].text
    return "research open problems"


def observation_query_pairs(
    *,
    focus: str = "",
    domains: list | None = None,
    world_or_frame: Optional[dict] = None,
    config: Optional[dict] = None,
    char_domain: str = "",
) -> list[tuple[str, str]]:
    """(tool_channel, query) pairs for observe_world — EN frontier + optional ZH web."""
    doms = list(domains or [])
    if not doms and char_domain:
        doms = [char_domain] if isinstance(char_domain, str) else list(char_domain)

    plan = plan_literature_search(
        intent="frontier",
        channel="observe",
        query=focus,
        focus=focus,
        domains=doms,
        world_or_frame=world_or_frame,
        config=config,
    )
    pairs: list[tuple[str, str]] = []
    for q in plan.queries:
        if q.channel == "arxiv":
            pairs.append(("arxiv", q.text))
        elif q.channel in ("web", "web_zh"):
            pairs.append(("web", q.text))
    # Also add living domain English tokens
    for d in doms[:3]:
        token = str(d).replace("_", " ").strip()
        if token and not looks_like_cjk(token):
            pairs.append(("arxiv", token))
    out, seen = [], set()
    for kind, text in pairs:
        key = (kind, text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, text))
    return out[:6]
