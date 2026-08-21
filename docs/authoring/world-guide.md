# World authoring guide

后续开发方向（知识社默认、检索仅前沿模式）见 [development-plan.md](development-plan.md)。

## Credibility bar

Every character needs:

1. **`soul.craft`** — what they are trained to *do*
2. **`soul.core_belief`** — about truth/method/life — **not** the open problem
3. **`soul.voice`** — working habits, not slogans
4. **`orientation.current_focus` + `open_question`** — what occupies them *now*
5. **Bonds** with technical *and* interpersonal stakes
6. **Tools consistent with `world.permeability`** — do not give `search_web` to `enclosed` worlds

On-demand search (`world.literature.enabled`) may add a shelf:

```yaml
world:
  literature:
    enabled: true
    shelf:
      arxiv_categories: [math.*, math-ph, cs.CC, hep-th, hep-lat]
```

The engine adds `cat:` to the arXiv query and drops off-shelf hits before they go on the unread pile. Empty shelf = no filter. Relevance among on-shelf hits is still the character's.

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

## Research vocation (optional)

If the world is a research studio (not an engineering shop):

```yaml
world:
  vocation: research
  skill_catalog: [research]   # templates the engine may *open* on characters
  vocation_soul:
    stance: "A researcher, not an engineer. …"
```

`world.skills: [research]` is an alias for `skill_catalog`.

On `expand_world` / `load_world` the engine:

1. Injects `soul.vocation` + `soul.vocation_stance` (does not overwrite authored craft / beliefs)
2. **Opens** the `research` skill on each character (a living book on Soul: level, moves, notes). The catalog file is a factory template, not a world prompt dump.

Skills grow the way Memory and Soul grow: `read_arxiv` / `write_paper` / `run_code` / study practice the book. Prompts inject *this character's* book.

The template method: orient → review peers → carve a working unit → cross-domain if blocked → probe with obligation → record status. Engine does not invent this text.

`vocation_soul.traits` are shared researcher habits (curiosity, question
your own proof, unfinished-is-legal…). Working habits, not costumes.
Warrants in `docs/skills/research.md` §Temperament should be *contemporary*
(Tao, Gowers, Scholze, Zhang, Huh…) — not 19th-century mythology. Names
stay in the skill file, not in `voice`.

Worlds may override the template at `worlds/<name>/skills/research.md`.
A character may also list `skills: [research]` to open extras from the catalog.

## Shared arena + growing domains

Digital lives are not bound by human specialization limits.

1. Declare one `world.shared_program` (gravity well / collision surface).
2. Give each character **several seed `domains`** (not one narrow label).
3. Craft = how they do mathematics; seasonal conjectures stay in `orientation`.
4. Runtime: Soul may grow `identity.domains` when curiosity opens a lasting new field (`opened_domains` via soul extract).
5. Bonds = methodological conflict over shared objects — even while domains wander.
