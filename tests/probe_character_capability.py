#!/usr/bin/env python3
"""Single-character capability probe for math-commune.

Hypothesis: if each agent can independently (1) cite a seed URL, (2) search
English frontier literature, (3) deep-read arXiv, (4) write a LaTeX Claim,
(5) run a killable check — the community has the raw capacity to succeed.

Usage:
  python tests/probe_character_capability.py
  python tests/probe_character_capability.py --chars Elias,Nora
  python tests/probe_character_capability.py --skip-tools   # LLM angles only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.character import Character
from engine.culture import (
    format_culture_context,
    format_practice_context,
    resolve_sociology,
    resolve_world_frame,
)
from engine.interactions import run_tool_use
from engine.literature import looks_like_cjk, plan_literature_search, primary_query
from engine.llm import LLM
from engine.tools import ToolRegistry
from engine.utils import parse_json
from engine.world_builder import load_world

CJK = re.compile(r"[\u4e00-\u9fff]")
LATEX_OR_CLAIM = re.compile(
    r"(\$|\\\\|\\begin\{|Claim|Theorem|Lemma|Conjecture|命题|断言)",
    re.I,
)
URL_RE = re.compile(r"https?://\S+|claymath\.org|arxiv\.org", re.I)

ROLE_MARKERS = {
    "Elias": ["url", "claim", "shelf", "cite", "tool", "种子", "主张", "书架"],
    "Yuki": ["object", "对象", "field", "statement", "altitude", "方言", "结构"],
    "Pavel": ["baseline", "null", "kill", "die", "null model", "可杀", "基线"],
    "Nora": ["source", "experiment", "kill", "shelf", "pdf", "数值", "实验", "原文"],
}


def _attach_world(char: Character, frame: dict, sociology: dict) -> None:
    from engine.research import research_prompt_block

    char._world_practice = format_practice_context(frame)
    char._skills_text = frame.get("skills_text") or {}
    char._research_protocol = research_prompt_block(frame)
    char._sociology_context = format_culture_context(sociology)
    soul = char.config.get("soul") or {}
    bits = []
    for key in ("craft", "who_i_am", "core_belief", "how_i_think", "what_drives_me", "vocation_stance"):
        val = soul.get(key)
        if isinstance(val, str) and val.strip():
            bits.append(f"{key}: {val.strip()}")
    traits = soul.get("vocation_traits") or []
    if traits:
        bits.append("traits: " + " | ".join(str(t) for t in traits[:6]))
    voice = soul.get("voice") or char.voice or []
    if voice:
        bits.append("voice: " + " | ".join(str(v) for v in voice[:4]))
    char._soul_context = "\n".join(bits)[:1800]


def _score_bool(ok: bool, detail: str) -> dict:
    return {"pass": bool(ok), "detail": detail}


def angle_seed_cite(char: Character, llm: LLM, frame: dict) -> dict:
    """Pick one seed problem with URL + next tool step."""
    shelf = []
    for item in (frame.get("seed_library") or [])[:8]:
        if isinstance(item, dict):
            shelf.append(
                f"- {(item.get('title') or '')} | {(item.get('url') or '')}"
            )
    prompt = f"""你是{char.name}。面前只有启动书架，还没有 live board。

书架摘要:
{chr(10).join(shelf)}

用 JSON 输出（只输出 JSON）:
{{
  "problem": "你选的世界级难题短名",
  "url": "必须是书架上的真实 URL",
  "why_me": "一句话：为什么由你的角色职责先动",
  "next_tool": "search_arxiv | read_arxiv | run_code | write_paper",
  "english_query": "若要搜文献，给 4-12 词英文查询"
}}
禁止发明口号题；必须引用书架 URL。
"""
    raw = llm.chat(
        [{"role": "user", "content": prompt}],
        system=char.build_system_prompt(),
        temperature=0.4,
    )
    data = parse_json(raw)
    url = str(data.get("url") or "")
    query = str(data.get("english_query") or "")
    ok_url = bool(URL_RE.search(url))
    ok_en = bool(query.strip()) and not looks_like_cjk(query)
    ok = ok_url and ok_en and "error" not in data
    return {
        "angle": "seed_cite",
        **_score_bool(
            ok,
            f"problem={data.get('problem')!r} url_ok={ok_url} en_query_ok={ok_en}",
        ),
        "data": data,
    }


def angle_literature_sanitize(char: Character, frame: dict) -> dict:
    """Policy path: Chinese slogan + role focus → English arXiv query."""
    focus = (
        getattr(char.state, "current_focus", None)
        or (char.research or {}).get("project")
        or char.orientation.get("current_focus")
        or ""
    )
    slogan = "从验证推论转向把判据换成检验标准，以此作为工作是否合格"
    plan = plan_literature_search(
        intent="frontier",
        channel="observe",
        query=slogan,
        focus=str(focus)[:160],
        world_or_frame=frame,
    )
    aq = primary_query(plan, "arxiv")
    ok = bool(aq) and not looks_like_cjk(aq)
    return {
        "angle": "literature_policy",
        **_score_bool(ok, f"rewrote→{aq!r} cjk_in={plan.rewritten_from_cjk}"),
        "data": {"arxiv_query": aq, "web_queries": [q.text for q in plan.queries]},
    }


def angle_search_and_read(
    char: Character,
    llm: LLM,
    registry: ToolRegistry,
    frame: dict,
    *,
    skip_tools: bool,
) -> list[dict]:
    out = []
    focus = (
        char.orientation.get("current_focus")
        or (char.research or {}).get("project")
        or "Clay Millennium prize problems"
    )
    char.state.current_focus = str(focus)[:200]

    params = run_tool_use(
        char, "search_arxiv", str(focus)[:160], llm, world_frame=frame
    )
    query = str(params.get("query") or "")
    out.append({
        "angle": "search_params",
        **_score_bool(
            bool(query) and not looks_like_cjk(query) and "error" not in params,
            f"query={query!r}",
        ),
        "data": params,
    })
    if skip_tools:
        return out

    result = registry.execute("search_arxiv", char.name, params)
    n = (result.metadata or {}).get("result_count", 0) if result.success else 0
    out.append({
        "angle": "search_execute",
        **_score_bool(result.success and n > 0, f"success={result.success} n={n}"),
        "data": {"output_head": (result.output or "")[:400], "query": result.metadata},
    })

    read_params = run_tool_use(
        char, "read_arxiv", str(focus)[:160], llm, world_frame=frame
    )
    # Prefer an id from search output if present
    m = re.search(r"\[(\d{4}\.\d{4,5}(?:v\d+)?)\]", result.output or "")
    if m:
        read_params["arxiv_id"] = m.group(1)
        read_params.pop("query", None)
    read = registry.execute("read_arxiv", char.name, read_params)
    body = read.output or ""
    has_math = bool(LATEX_OR_CLAIM.search(body)) or "abstract" in body.lower() or "公式" in body
    deep = len(body) > 800 and ("arxiv" in body.lower() or "摘要" in body or "$" in body)
    out.append({
        "angle": "deep_read",
        **_score_bool(
            read.success and (has_math or deep),
            f"success={read.success} len={len(body)} mathish={has_math}",
        ),
        "data": {"params": read_params, "output_head": body[:350]},
    })
    return out


def angle_claim_and_code(
    char: Character,
    llm: LLM,
    registry: ToolRegistry,
    frame: dict,
    *,
    skip_tools: bool,
) -> list[dict]:
    out = []
    topic = (
        "Cite Clay Riemann hypothesis statement; write one checkable Claim "
        "with LaTeX toward a next tool step"
    )
    params = run_tool_use(char, "write_paper", topic, llm, world_frame=frame)
    content = str(params.get("content") or "")
    title = str(params.get("title") or "")
    has_claim = bool(LATEX_OR_CLAIM.search(content))
    out.append({
        "angle": "claim_params",
        **_score_bool(
            "error" not in params and has_claim and len(content) > 120,
            f"title={title!r} latex/claim={has_claim} len={len(content)}",
        ),
        "data": {"title": title, "content_head": content[:350]},
    })
    if not skip_tools and "error" not in params:
        wr = registry.execute("write_paper", char.name, params)
        out.append({
            "angle": "claim_write",
            **_score_bool(wr.success, (wr.output or "")[:160]),
            "data": {"artifact": wr.artifact_path},
        })

    code_topic = (
        "Write a tiny killable numerical check related to zeta zeros OR a null "
        "baseline (print clear PASS/FAIL). Keep code under 25 lines. "
        "IMPORTANT: sandbox only allows stdlib + math/cmath/random/statistics/"
        "numpy/scipy/sympy/matplotlib — NO mpmath. Prefer math + pure Python."
    )
    cparams = run_tool_use(char, "run_code", code_topic, llm, world_frame=frame)
    code = str(cparams.get("code") or "")
    out.append({
        "angle": "code_params",
        **_score_bool(
            "error" not in cparams
            and len(code) > 20
            and ("import" in code or "print" in code),
            f"code_len={len(code)}",
        ),
        "data": {"code_head": code[:280]},
    })
    if not skip_tools and code.strip():
        cr = registry.execute("run_code", char.name, cparams)
        ok_run = cr.success and ("Error" not in (cr.output or "")[:80] or "PASS" in (cr.output or "") or "FAIL" in (cr.output or ""))
        # ToolResult success means sandbox ran; stderr may still show errors
        ran = cr.success
        out.append({
            "angle": "code_execute",
            **_score_bool(ran, (cr.output or "")[:220]),
            "data": {"metadata": cr.metadata},
        })
    return out


_SLOGAN_RE = re.compile(
    r"(从验证转向|检验标准|判据的判据|区分结构与噪声|真正的数学|"
    r"prove (the )?Riemann|证完|已经解决|此路不通|不可行)",
    re.I,
)
_MATH_NOUN_RE = re.compile(
    r"(zeta|ζ|L-function|Selmer|explicit formula|zero|rank|elliptic|"
    r"Hodge|cycle|modular|sieve|contour|Γ|gamma|Weil|Iwasawa|p-adic)",
    re.I,
)
_UNIT_TOO_BIG_RE = re.compile(
    r"(prove|证完|解决).{0,40}(Riemann|RH|BSD|Hodge|millennium|千禧)",
    re.I,
)


def angle_mathematician_vs_slogan(char: Character, llm: LLM) -> dict:
    """Can they carve a working unit — or only shout Clay slogans?"""
    from engine.research import looks_like_premature_verdict, score_research_note

    prompt = """Clay 官方陈述（Riemann hypothesis）：
若 ζ(ρ)=0 且 0<Re(ρ)<1，则 Re(ρ)=1/2。

你现在要开始工作。用 JSON 输出（只输出 JSON）：
{
  "horizon": "地平线问题短名",
  "working_unit": "今天可检查的一小步（复述引理 / 特例 / 数值探针 / 文献地图）——禁止写『证明 RH』",
  "peer_query": "4-12 word English query for a paper you would deep-read first",
  "claim_latex": "一条针对 working_unit 的 LaTeX Claim，不是口号",
  "status": "open|reconstructing|probing|obstructed|narrowed|withdrawn-with-obligation",
  "next_obligation": "什么实验或推导能判定这一步",
  "why_not_solved_today": "一句话：为什么今天不能关闭地平线"
}
禁止方法论散文。术语英文，公式 LaTeX。
"""
    raw = llm.chat(
        [{"role": "user", "content": prompt}],
        system=char.build_system_prompt(),
        temperature=0.35,
    )
    data = parse_json(raw)
    unit = str(data.get("working_unit") or "")
    claim = str(data.get("claim_latex") or "")
    query = str(data.get("peer_query") or "")
    status = str(data.get("status") or "")
    obl = str(data.get("next_obligation") or "")
    why = str(data.get("why_not_solved_today") or "")
    blob = " ".join([unit, claim, obl, why])

    checks = {
        "has_unit": len(unit) >= 12 and not _UNIT_TOO_BIG_RE.search(unit),
        "math_noun": bool(_MATH_NOUN_RE.search(blob)),
        "latex": bool(LATEX_OR_CLAIM.search(claim) or "$" in claim or "\\" in claim),
        "en_query": bool(query.strip()) and not looks_like_cjk(query),
        "status_ok": status in {
            "open", "reconstructing", "probing", "obstructed",
            "narrowed", "withdrawn-with-obligation",
        },
        "obligation": len(obl) >= 8,
        "not_slogan": not _SLOGAN_RE.search(blob) or bool(_MATH_NOUN_RE.search(blob)),
        "not_premature": not looks_like_premature_verdict(blob),
    }
    note = score_research_note(blob)
    ok = sum(checks.values()) >= 6 and checks["has_unit"] and checks["not_premature"]
    failed = [k for k, v in checks.items() if not v]
    return {
        "angle": "mathematician_vs_slogan",
        **_score_bool(ok, f"pass={sum(checks.values())}/8 fail={failed} note_ok={note.get('ok')}"),
        "data": data,
        "checks": checks,
    }


def angle_role_voice(char: Character, llm: LLM) -> dict:
    """Does the character speak from their role under pressure?"""
    prompt = (
        "社区有人说：『我们先划定各自专长领域，再找难题。』\n"
        "用你自己的角色职责回应（2-4 句，中文可，术语可英文）。"
        "不要客套；直接施压或纠偏。"
    )
    text = llm.chat(
        [{"role": "user", "content": prompt}],
        system=char.build_system_prompt(),
        temperature=0.7,
    )
    markers = ROLE_MARKERS.get(char.name, [])
    hits = [m for m in markers if m.lower() in text.lower()]
    ok = len(hits) >= 1 and len(text.strip()) > 40
    return {
        "angle": "role_voice",
        **_score_bool(ok, f"marker_hits={hits}"),
        "data": {"reply": text[:500]},
    }


def probe_one(
    name: str,
    cfg: dict,
    llm: LLM,
    registry: ToolRegistry,
    frame: dict,
    sociology: dict,
    *,
    skip_tools: bool,
) -> dict:
    char_cfg = next(c for c in cfg["characters"] if c["name"] == name)
    char = Character(name, char_cfg)
    _attach_world(char, frame, sociology)
    results = []
    results.append(angle_seed_cite(char, llm, frame))
    results.append(angle_literature_sanitize(char, frame))
    results.append(angle_role_voice(char, llm))
    results.append(angle_mathematician_vs_slogan(char, llm))
    results.extend(
        angle_search_and_read(char, llm, registry, frame, skip_tools=skip_tools)
    )
    results.extend(
        angle_claim_and_code(char, llm, registry, frame, skip_tools=skip_tools)
    )
    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    return {
        "character": name,
        "role": (char_cfg.get("community_role") or "")[:80],
        "passed": passed,
        "total": total,
        "score": round(passed / total, 3) if total else 0.0,
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="math-commune")
    ap.add_argument("--chars", default="Elias,Yuki,Pavel,Nora")
    ap.add_argument("--skip-tools", action="store_true")
    args = ap.parse_args()

    cfg = load_world(args.world, ROOT / "worlds")
    frame = resolve_world_frame(cfg)
    sociology = resolve_sociology(cfg)
    names = [n.strip() for n in args.chars.split(",") if n.strip()]

    out_dir = ROOT / "outputs" / "capability-probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = LLM(cfg)
    registry = ToolRegistry(
        cfg.get("tools") or [],
        out_dir,
        llm,
        world_frame=frame,
        config=cfg,
    )

    print(f"🔬 Character capability probe · {args.world}")
    print(f"   cast: {', '.join(names)}")
    print(f"   tools: {'skipped' if args.skip_tools else 'live arxiv/code/write'}\n")

    reports = []
    for name in names:
        print(f"{'═' * 60}\n▶ {name}")
        try:
            rep = probe_one(
                name, cfg, llm, registry, frame, sociology, skip_tools=args.skip_tools
            )
        except Exception as e:
            traceback.print_exc()
            rep = {
                "character": name,
                "passed": 0,
                "total": 0,
                "score": 0.0,
                "error": str(e),
                "results": [],
            }
        reports.append(rep)
        for r in rep.get("results") or []:
            mark = "✅" if r.get("pass") else "❌"
            print(f"  {mark} {r.get('angle')}: {r.get('detail')}")
        print(f"  → {rep.get('passed')}/{rep.get('total')}  score={rep.get('score')}")

    # Community verdict: weakest link
    scores = [r["score"] for r in reports if r.get("total")]
    weakest = min(reports, key=lambda r: r.get("score", 0)) if reports else None
    verdict = {
        "hypothesis": "single-agent success ⇒ community has capacity",
        "mean_score": round(sum(scores) / len(scores), 3) if scores else 0,
        "min_score": round(min(scores), 3) if scores else 0,
        "weakest": weakest.get("character") if weakest else None,
        "community_ready": bool(scores) and min(scores) >= 0.6 and (sum(scores) / len(scores)) >= 0.7,
        "llm_calls": getattr(llm, "call_count", 0),
        "timestamp": datetime.now().isoformat(),
        "reports": reports,
    }

    path = out_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'═' * 60}")
    print(
        f"Community capacity: mean={verdict['mean_score']} min={verdict['min_score']} "
        f"weakest={verdict['weakest']} ready={verdict['community_ready']}"
    )
    print(f"Saved {path}")
    return 0 if verdict["community_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
