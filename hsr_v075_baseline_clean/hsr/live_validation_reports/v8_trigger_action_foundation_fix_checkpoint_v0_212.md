# v8 Trigger/Action Foundation Fix Checkpoint v0_212

## Summary

v0_212 fixes structural issues found during the v0_210/v0_211 review. The executor now follows an explicit action event plan instead of hard-coded attack windows, damage packets use resolved selected targets, trigger execution is scoped to the action actor or primary target, and AddModifier partial semantics are visible instead of silently replacing status details.

## Runtime Changes

- Added `ActionEventPlan` so each action declares its trigger windows and damage step from `ActionDefinitionIR`.
- Reworked `CombatExecutor` to append mutations and settlement records in actual execution order.
- Built `DamagePacket` from `TargetResolution.selected`, not raw command target input.
- Added trigger window context with `SkillType`, `AttackType`, `damage_kind`, and `damage_formula_family`.
- Added actor/primary-target scope gating for status-local trigger windows.
- Marked duplicate AddModifier application and unimplemented stack/refresh/duration behavior as partial/unsupported.
- Tightened `EffectRegistry.coverage()` so registered opcodes are not automatically executable.
- Expanded unsupported effect trace with window, status instance, modifier, trigger source, and status source evidence.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir validation_outputs_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir validation_outputs_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir validation_outputs_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir validation_outputs_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir validation_outputs_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir validation_outputs_v0_209
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir validation_outputs_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir validation_outputs_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_212 --output-dir validation_outputs_v0_212
```

All validations returned `ok=True`.

v0_212 added checks:

- `action_event_plan=True`
- `damage_target_resolution=True`
- `trigger_scope_gating=True`
- `condition_payload=True`
- `add_modifier_partial=True`
- `effect_coverage=True`
- `unsupported_effect_trace=True`

## Remaining Risks

- Status lifecycle is still partial: duration tick, remove, dispel, full stack/refresh rules are not implemented.
- Trigger support is still status-local only; global listeners, being-hit windows, queue windows, and turn lifecycle are blocked for later stages.
- Non-damage action semantics are only window-gated here; heal/shield/buff resource effects still need their own effect handlers.
