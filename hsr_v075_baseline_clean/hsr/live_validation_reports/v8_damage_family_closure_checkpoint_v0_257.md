# v8 v0_257 Damage Family Closure Checkpoint

## Summary

This checkpoint closes the current damage-family baseline around explicit runtime policies and source windows.

Done:

- Added explicit `DamageFamilyPolicy` rows for `direct`, `dot`, `break`, `super_break`, `true_damage`, `hp_loss`, and `elation`.
- Added a `dot` runtime branch that only executes when an upstream admitted source has already produced a final amount.
- Lowered ordinary `AttackType=DOT` status damage sources into `StatusDamageEmissionIR(damage_formula_family=dot)`, but kept them blocked because the `DamageValue/DamagePercentage/ExtraFormulaType` formula is not admitted yet.
- Tightened source audit so every `damage_system` HP mutation must carry `source_frame`.
- Preserved v0_256 kill-credit behavior: primary action sequences can continue after lethal, while derived/additional/status/DoT sources skip defeated targets.

## Current Damage Family Status

- `direct`: `trusted_for_current_scope`
- `break`: `trusted_for_current_scope`
- `super_break`: `trusted_for_current_scope`
- `hp_loss`: `trusted_for_current_scope`
- `dot`: `blocked` for ordinary DoT formula admission; break DoT remains covered under `break`
- `true_damage`: `blocked`, no admitted executable TBGD true-damage effect/emission source yet
- `elation`: `blocked`, 4.0 mainline damage family discovered but formula inputs are not admitted yet

No family is reported as vague `structural_only`.

## Not Done

- Ordinary DoT formula execution is not guessed.
- Elation damage formula is not guessed.
- True damage is not executed from a fake source; only fixed-amount DamageSystem semantics exist until an executable source is admitted.
- Enemy AI, complete character panels, bounce RNG, waves, and observed-number corrections remain out of scope.

## Validation

Run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_249 --output-dir /tmp/hsr_v8_regression_v0_249
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_253 --output-dir /tmp/hsr_v8_regression_v0_253
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_256 --output-dir /tmp/hsr_v8_regression_v0_256
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_v0_257
git diff --check
```

Results:

- compileall: passed
- validate_v0_225: ok=true
- validate_v0_249: ok=true
- validate_v0_253: ok=true
- validate_v0_256: ok=true
- validate_v0_257: ok=true
- git diff --check: passed

## Progress

Damage now has a single explicit family policy surface and a source-window rule shared across direct, fixed, status, and future DoT paths. The next damage-related work should only admit currently blocked families after their TBGD formula/source inputs are proven, not by adding fallback math.
