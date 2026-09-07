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

- [ ] Raw occurrence inspected manually.
- [ ] Reference owner traced far enough to understand semantic responsibility.
- [ ] Concrete battle-state consequence or exclusion rationale recorded.
- [ ] Battle vs progression/presentation/tooling semantics separated.
- [ ] Mixed sources filtered below filename level where needed.
- [ ] Similar-looking game concepts disambiguated.
- [ ] Logical battle timing distinguished from presentation timing where relevant.
- [ ] External selectable targeting distinguished from internal execution targeting where relevant.
- [ ] External corroboration performed where practical.
- [ ] Version/live-vs-beta context recorded.
- [ ] Runtime verification performed if the simulator already implements the concept.
- [ ] Negative knowledge recorded.
- [ ] Remaining gaps are explicit.
