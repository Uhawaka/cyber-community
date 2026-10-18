#!/usr/bin/env python3
"""Blindly compare two story documents with the EXP-009 rubric."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from engine.adapters.openai_compatible import OpenAICompatibleTextModel
from engine.adapters.model_json import decode_json_object


DIMENSIONS = (
    "character_credibility",
    "scene_dynamics",
    "subtext",
    "pacing",
    "imagery",
    "language_distinction",
    "ending_resonance",
    "factual_coherence",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("story_a", type=Path)
    parser.add_argument("story_b", type=Path)
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.model_config.read_text(encoding="utf-8"))
    model = OpenAICompatibleTextModel(config)
    paths = [args.story_a, args.story_b]
    if _sha(paths[0]) > _sha(paths[1]):
        paths.reverse()
    samples = {
        label: _body(path)
        for label, path in zip(("A", "B"), paths, strict=True)
    }
    prompt = (
        "你是严格的中文类型小说终审。匿名比较两个由同一事实素材生成的场景。"
        "不要因篇幅长、古风词或信息完整自动加分。按八项各0至10整数评分："
        "character_credibility、scene_dynamics、subtext、pacing、imagery、"
        "language_distinction、ending_resonance、factual_coherence。"
        "56/80只是可继续迭代的文学技术线，不是专业发表线。"
        "只返回JSON：samples对象中A/B各含scores、total、strengths、failures；"
        "winner为A、B或tie；reason不超过120字。样本："
        + json.dumps(samples, ensure_ascii=False)
    )
    result = decode_json_object(
        model.complete(prompt, timeout_seconds=120.0)
    )
    if not isinstance(result, dict):
        raise ValueError("judge response is not an object")
    result["blind_mapping"] = {
        label: str(path)
        for label, path in zip(("A", "B"), paths, strict=True)
    }
    result["rubric_dimensions"] = list(DIMENSIONS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "\n---\n\n# "
    return text.split(marker, 1)[-1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
