# v8 Toughness / Weakness Break Core Checkpoint v0_231

## Summary

v0_231 moves toughness from an admission-only gate to a trusted current-scope runtime path.

The executable source is now:

```text
ConfigAbility AbilityTask DamageByAttackProperty.AttackProperty.StanceValue
-> ToughnessEmissionIR
-> ToughnessPlan
-> ToughnessSystem
-> toughness mutation
-> break lifecycle mutation when toughness reaches 0
```

`ShowStanceList` remains audit/display evidence only. It does not drive toughness mutation.

## Implemented

- Lowered executable `ToughnessEmissionIR` from real mainline Ability task `AttackProperty.StanceValue`.
- Kept `ShowStanceList` as audit-only hit profile evidence.
- Added global normal break template IR from `StanceBreak_{element}` templates.
- Added blocked `BreakDamageEmissionIR` evidence for `FormulaType=ByBreakDamage`.
- Changed runtime toughness amount resolution to use the unified numeric evaluator and trusted dynamic value binding sources.
- Decoupled toughness execution from HP damage emission; executable toughness can run even if HP damage is blocked.
- Added break lifecycle mutations for toughness depletion: `broken`, `break_element`, and `break_source`.
- Added source audit coverage for `break_system` mutations.
- Updated v0_230 validation semantics for the new `AttackProperty.StanceValue` source.
- Added `validate_v0_231`.

## Validation Snapshot

- `validate_v0_231`: `ok=true`
- Toughness emissions lowered: `360`
- Toughness emissions executable: `135`
- Toughness emissions blocked: `225`
- Break templates lowered: `7`
- Break templates executable: `7`
- Break damage emissions lowered: `7`
- Break damage emissions executable: `0`
- Break damage emissions blocked: `7`
- Selected structured action: `avatar_skill:121209` level `10`
- Selected structured avatar: `avatar:1212`
- Reduce case source audit: `ok=true`
- Break case source audit: `ok=true`
- Snapshot replay: `ok=true`
- Settlement traceability: `ok=true`

## Current Trust Boundary

- `toughness_execution`: `trusted_for_current_scope`
  - Scope: executable `ToughnessEmissionIR` from `AttackProperty.StanceValue`, with fixed or trusted dynamic value binding.
- `normal_break_lifecycle`: `trusted_for_current_scope`
  - Scope: toughness depletion sets broken state and records `OnTriggerBreak` / `OnBeingBreak` process events.
- `break_damage`: `blocked`
  - Dependency: `ByBreakDamage` formula inputs and postfix semantics are not admitted yet.
- `super_break`: out of scope for normal toughness/break v0_231.

## Commands Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_229 --output-dir /tmp/hsr_v8_regression_v0_229
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_230 --output-dir /tmp/hsr_v8_regression_v0_230
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_231 --output-dir /tmp/hsr_v8_v0_231
git diff --check
```
