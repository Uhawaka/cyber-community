#!/usr/bin/env python3
"""Audit soul/memory hygiene after a simulation run."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SOUL_JUNK = re.compile(
    r"(使用\w+获得发现|代码运行|论文已保存|stdout|\[run_code\]|\[write_paper\]|"
    r"找到\s*\d+\s*篇|低频功率谱|alpha\s*[≈=]|exit_code|ToolResult)",
    re.I,
)

DOMAIN_DIRTY = re.compile(
    r"[—–―]|--|若持续|暂不确认|only if| lasting ",
    re.I,
)
DOMAIN_CJK = re.compile(r"[\u4e00-\u9fff]")

REFLECTION_BAD_START = re.compile(
    r"^(\d+[\.\)]\s*)|(?:我的)?核心洞见|My core insight",
    re.I,
)

FACT_SHELL = re.compile(
    r"(讨论了|来找我聊了|翻阅了|论文已保存|使用了\w+)",
    re.I,
)

REQUIRED_IDENTITY = (
    "who_i_am",
    "core_belief",
    "how_i_think",
    "what_drives_me",
)


def audit_soul(path: Path) -> list[str]:
    issues = []
    data = yaml.safe_load(path.read_text()) or {}
    name = data.get("name") or path.stem

    if data.get("soul_version") != "2.0":
        issues.append(f"{name}: soul_version != 2.0")
    if "knowledge_evolved" in data or "witnessed_moments" in data:
        issues.append(f"{name}: legacy scrapbook fields present")

    ident = data.get("identity") or {}
    for key in REQUIRED_IDENTITY:
        if not (ident.get(key) or "").strip():
            issues.append(f"{name}: identity.{key} empty")

    for dom in ident.get("domains") or []:
        d = str(dom)
        if DOMAIN_DIRTY.search(d) or DOMAIN_CJK.search(d):
            issues.append(f"{name}: dirty domain slug: {d!r}")

    blob = yaml.dump(data, allow_unicode=True)
    if SOUL_JUNK.search(blob):
        m = SOUL_JUNK.search(blob)
        issues.append(f"{name}: junk pattern in soul: {m.group(0)!r}")

    for i, ref in enumerate(data.get("reflections") or []):
        stmt = ref.get("statement") or ""
        if len(stmt) > 160:
            issues.append(f"{name}: reflection[{i}] too long ({len(stmt)} chars)")
        if SOUL_JUNK.search(stmt):
            issues.append(f"{name}: reflection[{i}] looks like lab note")
        if REFLECTION_BAD_START.search(stmt.strip()):
            issues.append(f"{name}: reflection[{i}] has boilerplate/numbering prefix")

    murmurs = data.get("recent_murmurs") or []
    if len(murmurs) > 3:
        issues.append(f"{name}: recent_murmurs overflow ({len(murmurs)})")

    return issues


def audit_memory(path: Path) -> list[str]:
    """Memory MAY contain research detail — flag structural breakage and shell facts."""
    issues = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path.name}: invalid json: {e}"]

    episodes = data.get("episodes") or []
    if not episodes:
        issues.append(f"{path.stem}: no episodes (unexpected after a run)")
    if not any(e.get("type") == "backstory" for e in episodes):
        issues.append(f"{path.stem}: missing backstory seeds")

    for i, fact in enumerate(data.get("semantic_facts") or []):
        text = fact.get("fact") if isinstance(fact, dict) else str(fact)
        if FACT_SHELL.search(text or ""):
            issues.append(f"{path.stem}: semantic_facts[{i}] is narrative shell")

    return issues


def main():
    world = sys.argv[1] if len(sys.argv) > 1 else "Math-Commune"
    base = ROOT / "outputs" / world
    if not base.exists():
        # try alternate spacing
        alt = ROOT / "outputs" / world.replace(" ", "-")
        if alt.exists():
            base = alt
        else:
            candidates = list((ROOT / "outputs").glob("*"))
            print(f"No outputs/{world}. Available: {[p.name for p in candidates]}")
            return 1

    soul_dir = base / "souls"
    mem_dir = base / "memory"
    all_issues = []

    print(f"Audit: {base}")
    print("── Souls ──")
    for path in sorted(soul_dir.glob("*.yaml")):
        issues = audit_soul(path)
        data = yaml.safe_load(path.read_text()) or {}
        ident = data.get("identity") or {}
        print(f"  {path.stem}: version={data.get('soul_version')} "
              f"belief={str(ident.get('core_belief',''))[:40]!r} "
              f"refs={len(data.get('reflections') or [])} "
              f"bonds={len(data.get('bonds') or {})}")
        for i in issues:
            print(f"    ❌ {i}")
        all_issues.extend(issues)

    print("── Memory ──")
    for path in sorted(mem_dir.glob("*.json")):
        issues = audit_memory(path)
        data = json.loads(path.read_text())
        eps = data.get("episodes") or []
        types = {}
        for e in eps:
            types[e.get("type", "?")] = types.get(e.get("type", "?"), 0) + 1
        print(f"  {path.stem}: episodes={len(eps)} types={types} "
              f"facts={len(data.get('semantic_facts') or [])}")
        for i in issues:
            print(f"    ❌ {i}")
        all_issues.extend(issues)

    print()
    if all_issues:
        print(f"FAIL — {len(all_issues)} issue(s)")
        return 1
    print("PASS — soul/memory boundary looks healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
