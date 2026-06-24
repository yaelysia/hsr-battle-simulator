# v8 v0_255 - Kill Attribution and Automatic Extra-Turn Trigger

## Summary

v0_255 replaces the v0_254 manual death callback trigger with a runtime damage-caused defeat event:

```text
DamageSystem HP transition >0 -> 0
-> unit.defeated
-> OnTriggerDeath / OnTriggerDeathrattle
-> dynamic value / queue intent
-> extra-turn queue drain and child action
```

The kill-credit rule is now explicit: only the damage packet that changes a target from positive HP to 0 receives `unit.defeated` credit. Earlier nonlethal packets and later packets against an already defeated target do not produce kill-credit events.

## Implemented

- `DamageSystem` now emits `unit.defeated` alongside `damage.hit` when a packet causes the HP transition from `>0` to `0`.
- The defeat event carries `killer_id`, `defeated_unit_id`, `lethal_damage_event_id`, damage family, attack type, emission ids, and source trace.
- `EventDispatchSystem` maps `unit.defeated` to `OnTriggerDeath` / `OnTriggerDeathrattle` with kill-credit owner scope.
- Runtime status callback filtering now respects `trigger_ids_by_event` strictly when that mapping is present.
- v0_255 validation covers automatic defeat event dispatch, wrong-owner negative case, and multi-source kill attribution.

## Findings

- The structured extra-turn source is still the real mainline Avatar callback chain from `Local_Seele_ListenKill`.
- The same-source selected extra-turn action `avatar_skill:110201` currently has no admitted `DamageEmissionIR`.
- v0_255 therefore validates kill attribution with a separate executable mainline damage action, while keeping the same-source damage gap explicit instead of faking damage emission.

## Validation

Run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_regression_v0_248
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_253 --output-dir /tmp/hsr_v8_regression_v0_253
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_254 --output-dir /tmp/hsr_v8_regression_v0_254
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_255 --output-dir /tmp/hsr_v8_v0_255
```

Observed result: all commands pass with `ok=true`.

## Remaining Scope

- Same-source extra-turn action damage execution still depends on admitted `DamageEmissionIR` for that action source.
- This stage does not add enemy AI, full character profile assembly, waves, assistant actors, or bounce RNG.
