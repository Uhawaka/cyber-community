#!/usr/bin/env python3
"""Run 1 day and write results to /tmp/cc_test_result.json"""
import sys, yaml, random, json, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from engine.llm import LLM
from engine.engine import SimulationEngine

os.makedirs("/tmp/cc_test", exist_ok=True)
random.seed(42)

with open("worlds/math-commune/community.yaml") as f:
    config = yaml.safe_load(f)

llm = LLM(config)
engine = SimulationEngine(config, llm)

try:
    engine.run(max_days=1, verbose=False)
    
    result = {
        "day": engine.day,
        "events": len(engine.event_log),
        "artifacts": len(engine.production.artifacts),
        "observations": len(engine.production.observations),
        "collaborations": [
            {"topic": p.topic, "participants": p.participants, "progress": p.progress}
            for p in engine.collab.get_active()
        ],
        "artifacts_sample": [
            {"type": a.type, "authors": a.authors, "title": a.title[:100]}
            for a in engine.production.artifacts[-5:]
        ],
        "obs_sources": {},
        "success": True,
    }
    for o in engine.production.observations:
        s = o.get("source", "?")
        result["obs_sources"][s] = result["obs_sources"].get(s, 0) + 1
        
except Exception as e:
    result = {"success": False, "error": str(e)}

with open("/tmp/cc_test_result.json", "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("DONE")
