# Language policy

## Layers

| Layer | Language |
|-------|----------|
| World / character / soul YAML | English (technical accuracy) |
| Dialogue & narration to the user | `speech_language` (math-commune: `zh`) |
| Technical nouns (theorems, venues, tools) | **Keep English** even inside Chinese prose |
| Academic search queries | English |

## Why

- Forced Chinese translations of math terms are often wrong or opaque.
- Chinese idioms / 网文腔 translate poorly into research talk.
- Literature (arXiv, journals) is English-native; digital researchers should use those nouns.

## Rules for prompts

1. Narration follows `speech_language`.
2. Terms like `L-function`, `sieve`, `random matrix`, `Annals` stay English.
3. Prefer plain clarity over idioms.
4. Mixed sentences are fine: Chinese glue + English terms.

Implemented in [`engine/language.py`](../../engine/language.py) and injected via character system prompts, `LLM.think()`, study/collision/tool prompts, and observation queries.
