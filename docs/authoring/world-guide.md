# World authoring guide

## Credibility bar

Every character needs:

1. **`soul.craft`** — what they are trained to *do*
2. **`soul.core_belief`** — about truth/method/life — **not** the open problem
3. **`soul.voice`** — working habits, not slogans
4. **`orientation.current_focus` + `open_question`** — what occupies them *now*
5. **Bonds** with technical *and* interpersonal stakes
6. **Tools consistent with `world.permeability`** — do not give `search_web` to `enclosed` worlds

## Language

See [language-policy.md](../contracts/language-policy.md).

- Config (world, soul, research, sociology): **English**
- Dialogue: `world.speech_language` (default `zh`)
- Technical nouns stay English inside Chinese prose (no forced translation)
- Academic search queries: English
- Literary quotations may stay in source language inside `voice` as citations

## Identity ≠ orientation

Bad: `core_belief: "twin primes are ordered"`  
Good: `core_belief: "claims without checkable consequences are unfinished"` + `orientation.current_focus: "long-range order in prime gaps"`

## WDL dialect

Use `format_version: "2.0"` with `meta` / `world` / `characters` / `tools`. See [wdl-v2-spec.yaml](../contracts/wdl-v2-spec.yaml).

## Depth

Prefer one precise stuck point over buzzword lists. Prefer relationship history that changes behavior over cartoon nicknames alone.

## Shared arena + growing domains

Digital lives are not bound by human specialization limits.

1. Declare one `world.shared_program` (gravity well / collision surface).
2. Give each character **several seed `domains`** (not one narrow label).
3. Craft = how they do mathematics; seasonal conjectures stay in `orientation`.
4. Runtime: Soul may grow `identity.domains` when curiosity opens a lasting new field (`opened_domains` via soul extract).
5. Bonds = methodological conflict over shared objects — even while domains wander.
