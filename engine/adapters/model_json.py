"""Strict-enough JSON extraction shared by model-backed adapters."""

from __future__ import annotations

import json


def decode_json_object(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        final_fence = text.rfind("```")
        if first_newline >= 0 and final_fence > first_newline:
            text = text[first_newline + 1 : final_fence].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value
