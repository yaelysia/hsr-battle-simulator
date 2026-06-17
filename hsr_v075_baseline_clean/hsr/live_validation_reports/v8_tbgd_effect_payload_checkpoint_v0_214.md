# v8 TBGD Effect Payload Checkpoint v0_214

## Scope

- Standardized real TBGD effect payloads for `RemoveModifier`, `RemoveSelfModifier`, `HealHP`, `InitShield`, `StackShield`, `ModifyShield`, `SetEnergyBarState`, `SetMonsterEnergyBarState`, and `SetSummonerEnergyBarState`.
- Runtime effect execution now gates on opcode plus executable standard payload, not opcode registration alone.
- `RemoveSelfModifier` is lowered as `target_alias=ModifierOwnerEntity` with `modifier_name` from the source modifier.
- Mechanism bar state effects write `unit.flags.mechanism_bars` only for fixed state/count fields and never mutate unit `energy`.
- Dynamic heal/shield formulas remain blocked with explicit reasons instead of being treated as executable fixed effects.

## Validation

Command:

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir validation_outputs_v0_214
```

Result:

- `ok=true`
- Full regression chain `v0_200`, `v0_203`-`v0_214` passed.
- `RemoveModifier`: real mainline TBGD sample executable and lifecycle remove replay passed.
- `RemoveSelfModifier`: real mainline TBGD sample executable and source modifier self-remove replay passed.
- `HealHP`: no strict mainline fixed-value sample was found; dynamic Huohuo heal sample is blocked with `fixed_modify_value_required`.
- `InitShield/StackShield/ModifyShield`: strict mainline fixed executable sample was not used; dynamic Gepard shield sample is blocked with `fixed_shield_value_required`.
- `SetEnergyBarState`: real mainline Huohuo sample writes `flags.mechanism_bars` and does not produce `energy` mutation.
- Static checks, snapshot completeness, transition contract, settlement traceability, and replay passed for executable effect transitions.

## Coverage Counts

- `RemoveModifier`: lowered `3397`, executable `2232`
- `RemoveSelfModifier`: lowered `1545`, executable `1545`
- `HealHP`: lowered `264`, executable `0`
- `InitShield`: lowered `64`, executable `8`
- `StackShield`: lowered `4`, executable `0`
- `ModifyShield`: lowered `14`, executable `0`
- `SetEnergyBarState`: lowered `281`, executable `248`
- `SetMonsterEnergyBarState`: lowered `301`, executable `261`
- `SetSummonerEnergyBarState`: lowered `16`, executable `16`

## Remaining Risks

- Heal and shield dynamic formulas are still not executable. They need formula evaluator support before they can represent real in-game healing/shield amounts.
- Mechanism bar state currently records only fixed visible state/count fields. It does not yet model full special gauge semantics.
- Action event planning is still derived from `ActionDefinitionIR`, not a full TBGD action-event plan.
- Trigger scope remains conservative: actor/primary-target local only; listener/global/being-hit windows are still blocked.
- Status lifecycle still marks unsupported stack/refresh/duration policy as partial instead of fully implementing those policies.
