# Soul vs Memory Boundary

Normative. Matches `engine/soul.py` and `engine/memory.py`.

| | Soul (personality anchor) | Skills (earned craft) | Memory (experience stream) | DailyArchive | Production |
|--|---------------------------|----------------------|----------------------------|--------------|------------|
| Question | Who am I? How do I stand toward others? What occupies me now? | What can I do, and how do I work? | What happened? What was computed? Who said what? | What was today in one paragraph? | Finished notes, papers, code artifacts |
| Cadence | Slow (days/weeks) | Grows with practice (study / read / write / code) | Fast (per event) | Once per day boundary | On tool success |
| Allowed | `identity`, `bonds`, `orientation`, `reflections`, `milestones` | `skills.<id>`: level, moves, notes, stance snapshot | episodes, semantic facts, working focus | day/week summaries | markdown/code under `outputs/.../production` |
| Forbidden | Tool stdout, paper paths, formula drafts, chitchat, research scrapbooks; dumping catalog markdown into identity | World manifesto dumps; treating a catalog file as every character's prompt | Identity essays that belong in Soul; dumping full Soul into episodes | Tool dumps as "summary" | Treating production as personality |

## `recent_murmurs`

Tiny ephemeral blur for prompts only. Cap ≤3. Not identity. Do not treat as durable self-knowledge.

## Domain slugs (`identity.domains`)

- Form: English `snake_case` (or short phrase normalized to snake_case), length 3–40.
- Allowed in the slug: `a-z`, `0-9`, `_`.
- Forbidden in the slug: em-dash commentary, full sentences, Chinese meta-instructions (`若持续…`, `暂不确认…`), prompt leftovers (`only if…`).
- `reason` for opening a domain belongs in `meta.domain_log` / a short note on `orientation.recently_opened` — never concatenated into the domain name.

## Reflections

- One abstract insight sentence after cleaning.
- Strip leading numbering (`1.`), boilerplate (`我的核心洞见是`, `My core insight is`), and markdown `**`.
- Reject tool/log formats (same junk filter as milestones).
- Near-duplicates of the last few reflections are dropped.

## Semantic facts

- Must be reusable claims detached from the day's narrative: checkable assertions, relationship conclusions, falsified hypotheses.
- Forbidden shells: `与 X 讨论了…`, `翻阅了关于…`, `来找我聊了…`, `论文已保存`, tool stdout.
- Day-end promotion prefers `deep_think`, then `collision`, then `study`; never promote bare `tool_use` / `observe` summaries. Zero facts is better than junk.

## Update rules

1. Seed Soul once from character YAML (`soul:` + `orientation:` preferred).
2. Runtime Soul writes only via curated deltas (bonds, orientation, reflections, rare milestones, cleaned `opened_domains`, rare `opened_skills`).
3. Reject tool/log formats in milestones and reflections.
4. Research facts go to Memory or Production — never `identity.core_belief`.
5. Skills live on Soul as a sibling of identity (`skills`), not as `core_belief`. The engine catalog *creates* a skill; practice grows it. Do not dump `docs/skills/*.md` into every world prompt.

## References

Generative Agents (reflection ≠ observation); Character Card (persona vs chat memory).
