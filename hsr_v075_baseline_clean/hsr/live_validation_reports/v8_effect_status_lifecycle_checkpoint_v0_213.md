# v8 Effect/Status Lifecycle Checkpoint v0_213

## Summary

v0_213 promotes status lifecycle handling from implicit replacement to explicit lifecycle plans/results. AddModifier now emits `StatusLifecyclePlan` and `StatusLifecycleResult`, duplicate application is recorded as `refresh_or_replace_partial`, and RemoveModifier can remove runtime status ids and status details through mutation-linked settlement records.

This checkpoint also adds fixed-value runtime handlers for Heal, Shield, and ResourceDelta. These handlers validate the effect execution spine and mutation/settlement/replay contract. They do not mean raw TBGD HealHP/InitShield/SetEnergyBarState opcodes are fully lowered or executable yet.

## Risk Guards

- `ActionEventPlan` is still derived from `ActionDefinitionIR`; it must eventually be replaced by explicit TBGD Action/Event IR.
- Trigger scope remains conservative: actor-local and primary-target-local status triggers are supported; listener/global/being-hit scopes remain blocked for later stages.
- Status lifecycle is still partial for full stack, refresh, duration, expire, and tick semantics. v0_213 requires these partial states to be visible in lifecycle records instead of silent replacement.

## Runtime Changes

- Added `StatusLifecyclePlan` and `StatusLifecycleResult`.
- Extended `StatusInstance` with remaining duration, duration unit, stack policy, refresh policy, and lifecycle state.
- Routed AddModifier through lifecycle planning and mutation-linked lifecycle settlement.
- Added RemoveModifier runtime execution for standardized fixed target/status payloads.
- Added fixed-value Heal, Shield, and ResourceDelta handlers for runtime contract validation.
- Added unsupported records for complex fixed-effect formulas, unsupported target scope, and non-guaranteed AddModifier chance.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_213 --output-dir validation_outputs_v0_213
```

All validations returned `ok=True`.

v0_213 added checks:

- `risk_guards=True`
- `status_lifecycle=True`
- `remove_modifier=True`
- `fixed_effects=True`
- `unsupported_effect_contract=True`
- `effect_transition_contracts=True`

## Remaining Risks

- Raw TBGD RemoveModifier/HealHP/InitShield/SetEnergyBarState payloads are still not standardized by lowering.
- Duration tick, expiration, dispel, stack merge, and full refresh policies are not complete.
- Heal/shield/resource effects are fixed-value runtime contract handlers only; formula/effect-window semantics remain future work.
