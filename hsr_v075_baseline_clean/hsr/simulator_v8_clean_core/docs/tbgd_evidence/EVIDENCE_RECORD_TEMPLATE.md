# TBGD Battle Evidence Record Template

## Record metadata

- Concept:
- Scope/entity:
- Game version context:
- TBGD revision:
- Evidence maturity: `candidate | manually_confirmed | cross_validated | runtime_verified`
- Authority class: `battle_authoritative | battle_supporting | mixed_requires_filter | progression_only | presentation_only | editor_tooling | telemetry_only | unknown_unreviewed`
- Confidence: `low | medium | high`
- Tracking issue/PR:

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
- gameplay target selection vs camera/presentation target selection.

## External corroboration

For each external source:

- source/site/document;
- live/beta/version context;
- exact claim checked;
- observed value/behavior;
- agrees/disagrees with TBGD;
- follow-up required if disagreement exists.

External sources are corroboration only and never replace pinned TBGD authority.

## Runtime/validator verification

If executable verification exists, record:

- simulator entry point/validator;
- fixed input;
- expected result derived independently;
- actual result;
- relevant commit SHA.

## Negative knowledge / false friends

Record nearby sources or fields that look relevant but are not valid authorities for this concept, and explain why.

## Unresolved questions

List every remaining ambiguity. Do not silently promote unresolved assumptions into canonical data.

## Promotion checklist

- [ ] Raw occurrence inspected manually.
- [ ] Reference owner traced far enough to understand semantic responsibility.
- [ ] Battle vs progression/presentation/tooling semantics separated.
- [ ] Similar-looking game concepts disambiguated.
- [ ] External corroboration performed where practical.
- [ ] Version/live-vs-beta context recorded.
- [ ] Runtime verification performed if the simulator already implements the concept.
- [ ] Negative knowledge recorded.
- [ ] Remaining gaps are explicit.
