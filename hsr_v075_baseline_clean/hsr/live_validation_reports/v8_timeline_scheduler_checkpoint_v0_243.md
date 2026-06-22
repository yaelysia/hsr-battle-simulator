# v8 Timeline Scheduler Checkpoint v0_243

## Summary

v0_243 adds the first source-audited timeline scheduler layer. The runtime can now advance AV to the next admitted actor, open and close a regular turn, preserve explicit scenario action-value overrides, and prefer an admitted queue drain before natural AV advancement.

The timeline base formula is recorded as `TimelineRuleIR` with `source_kind=engine_convention`:

```text
base_action_gauge = 10000
action_value = base_action_gauge / speed
```

This is intentionally not represented as a TBGD raw source until a concrete TBGD constant source is admitted.

## Implemented

- Added `TimelineRuleIR` to Canonical IR and RuleBook.
- Added stable timeline snapshot fields: `global_av`, `active_turn`, `turn_queue_policy`, `last_advanced_delta`, `turn_sequence_index`.
- Extended `TimelineSystem` with action-value initialization, next-actor planning, AV advance, turn begin, and turn end/reset.
- Added `CombatScheduler` as the boundary for queue-first scheduling and natural timeline progression.
- Added source audit policy for natural `timeline_system` mutations.
- Added `validate_v0_243`.

## Validation Results

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_regression_v0_238
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_243 --output-dir /tmp/hsr_v8_v0_243
git diff --check
```

All checks passed.

v0_243 checked:

- AV advance selects the next actor and mutates all affected action values.
- turn begin writes active turn metadata.
- turn end resets regular-turn actor AV using the admitted timeline rule.
- explicit scenario action-value override is preserved.
- admitted queue drain is handled before natural AV progression.
- enemy turn without AI policy is process-only blocked and leaves after snapshot unchanged.
- unsupported duration tick and speed recompute hooks are process-only blocked and leave after snapshot unchanged.
- source audit, settlement traceability, and snapshot replay pass for mutating transitions.

## Remaining Boundaries

- `enemy_ai_action` remains blocked until enemy AI action and target selection are admitted.
- `full_status_duration_tick` remains blocked until lifecycle decrement/expire sources are admitted.
- Full ultimate/follow-up/counter queue semantics, recursive inserted action ordering, waves, and bounce RNG are not part of this checkpoint.
