# TBGD Battle Evidence Record Template

## Record metadata

- Concept:
- Scope/entity:
- Game version context:
- TBGD revision:
- Evidence maturity: `candidate | manually_confirmed | cross_validated | runtime_verified`
- Authority class: `battle_authoritative | battle_supporting | mixed_requires_filter | progression_only | presentation_only | editor_tooling | telemetry_only | unknown_unreviewed`
- Battle-scope verdict: `include | exclude | mixed | unresolved`
- Confidence: `low | medium | high`
- Tracking issue/PR:

## Battle-scope gate

Before promoting evidence, state the concrete consequence test:

- What battle state/action/target/timeline/resource/numeric outcome/status/trigger/AI/encounter/mode/termination concept can this source change?
- If the source is mixed, which exact fields/rows/opcodes are included and which are excluded?
- If excluded, what was inspected and why can it not alter battle execution?
- Is any apparent timing only animation/camera/presentation timing rather than logical battle timing?
- Is any target operation internal execution targeting rather than the externally selectable action target contract?

Follow [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md). Filename/directory/field-name matching alone is never sufficient authority.

## Gameplay semantic model

Before source closure, establish the in-game combat behavior that the TBGD chain is expected to explain. Record enough gameplay semantics to know what must be searched, traced and falsified, including where relevant:

- the observable battle-state transition or numeric outcome;
- actor/owner/source/target relationships and legal targeting;
- preconditions, branches, resource gates and trigger conditions;
- timing/order, duration, refresh/stacking/snapshot behavior and cleanup;
- important edge cases or interactions that could reveal a missing producer/consumer;
- the basis for this gameplay understanding, such as official descriptions, direct gameplay observation or trusted mechanics references;
- any known disagreement between the gameplay model and the pinned TBGD evidence.

Gameplay knowledge is a **navigation hypothesis and completeness oracle**, not a replacement authority. It may tell us what behavior should be explained and what missing branches to search for, but it must never be used to invent a pinned value, reference edge, formula or opcode meaning that the raw chain does not prove.

A fully resolved reference graph is not, by itself, a semantically closed mechanism. The interpreted raw chain must coherently explain the relevant gameplay behavior. Any material mismatch must remain explicit as `unresolved`, `not_proven` or version drift until evidence closes it.

## Raw TBGD evidence

For every source occurrence, record:

- exact path;
- blob SHA when useful;
- JSON pointer / field / opcode / occurrence identity;
- representative raw structure/value;
- why this occurrence is relevant.

## Reference chain

```text
upstream identity
  -> join/reference key
  -> intermediate source
  -> semantic owner
  -> downstream runtime concept
```

Every edge should be marked as one of:

- `candidate`
- `manually_confirmed`
- `cross_validated`
- `runtime_verified`

## Semantic interpretation

Explain what the source means in the actual Honkai: Star Rail combat model. Distinguish similar-looking concepts explicitly, for example:

- SPD change vs action advance/delay;
- damage multiplier vs DMG bonus vs vulnerability;
- base chance vs effect hit rate vs resistance;
- damage vs toughness damage;
- energy cost vs energy generation;
- gameplay target selection vs camera/presentation target selection;
- battle-entry effects vs overworld/Technique presentation;
- combat effects of upgrades/mode assets vs their acquisition/progression systems.

## External corroboration

For each external source:

- source/site/document;
- live/beta/version context;
- exact claim checked;
- observed value/behavior;
- agrees/disagrees with TBGD;
- follow-up required if disagreement exists.

External sources are corroboration only and never replace pinned TBGD authority. Current-live values must not be used to silently fill historical/pinned gaps.

## Runtime/validator verification

If executable verification exists, record:

- simulator entry point/validator;
- fixed input;
- expected result derived independently;
- actual result;
- relevant commit SHA.

## Negative knowledge / false friends

Record nearby sources or fields that look relevant but are not valid authorities for this concept, and explain why. Reviewed exclusions are part of corpus-completeness evidence.

## Unresolved questions

List every remaining ambiguity. Do not silently promote unresolved assumptions into canonical data or silently classify an unresolved family as non-battle.

## Promotion checklist

- [ ] Relevant gameplay semantic model established well enough to know what behavior, branches and edge cases the source chain must explain.
- [ ] Gameplay understanding is sourced/version-scoped where material and is used for navigation/completeness, not as a substitute for pinned raw authority.
- [ ] Raw occurrence inspected manually.
- [ ] Reference owner traced far enough to understand semantic responsibility.
- [ ] Concrete battle-state consequence or exclusion rationale recorded.
- [ ] Battle vs progression/presentation/tooling semantics separated.
- [ ] Mixed sources filtered below filename level where needed.
- [ ] Similar-looking game concepts disambiguated.
- [ ] Logical battle timing distinguished from presentation timing where relevant.
- [ ] External selectable targeting distinguished from internal execution targeting where relevant.
- [ ] Raw interpretation reconciled with known gameplay behavior; material discrepancies remain explicit rather than normalized away.
- [ ] External corroboration performed where practical.
- [ ] Version/live-vs-beta context recorded.
- [ ] Runtime verification performed if the simulator already implements the concept.
- [ ] Negative knowledge recorded.
- [ ] Remaining gaps are explicit.
