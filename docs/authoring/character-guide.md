# Character authoring guide

Copy [templates/character.yaml](../templates/character.yaml).

## Fill order

1. `name`, `domain`, `seed` (epistemic stance)
2. `soul.*` — craft, who_i_am, core_belief, voice, bonds
3. `orientation.*` — current program and stuck question
4. `research` — optional detail (project, stuck_point, obsession as *current* fixation)
5. Flat psych: `personality`, `drives`, `cognitive`, `defense`
6. `relationships` if bonds need surface/history beyond soul.bonds
7. `scripts` / `autonomy` for behavior bias

## Do not

- Nest psych under `psychology.drives` (engine expects flat keys)
- Put the open problem into `seed` / `core_belief`
- Leave `seed: ""` hoping the engine invents a personality
- Use Chinese for technical math/finance terms in config

## Engine seeding

`SoulFile.init_from_config` copies `soul:` / `orientation:` 1:1. Fallbacks: `seed`→`core_belief`, `self_concept`→`who_i_am`, `research.*`→`orientation`, `relationships[].true_feeling`→`bonds`.
