# v8 Toughness Emission Gate Checkpoint v0_230

## Summary

v0_230 adds the toughness emission admission boundary without pretending `ShowStanceList` is executable toughness damage.

The new chain is:

```text
TBGD / Ability Task evidence -> ToughnessEmissionIR -> ToughnessPlan -> ToughnessSystem -> Mutation/Settlement
```

Current admitted executable toughness source count is `0`. This is intentional: current lowered evidence is not enough to prove real in-game toughness damage semantics.

## Implemented

- Added `ToughnessEmissionIR` to Canonical IR and RuleBook queries.
- Lowered toughness emission evidence from ability damage task + hit profile evidence.
- Kept `ShowStanceList` evidence blocked with `show_stance_semantics_not_confirmed`.
- Added `ToughnessPlan` to `ActionExecutionPlan`.
- Added `ToughnessSystem` with source-traceable mutation support for future executable emissions.
- Added source audit policy for `toughness_system`.
- Added runtime static guard against raw `ShowStanceList` / `ShowStance` inference.
- Added `validate_v0_230`.

## Validation Snapshot

- `validate_v0_230`: `ok=true`
- Toughness emissions lowered: `360`
- Toughness emissions executable: `0`
- Toughness emissions blocked: `360`
- Selected structured action: `avatar_skill:121209` level `1`
- Selected structured enemy profile: `monster:1002011`
- Source audit: `ok=true`
- Static checks: `ok=true`
- Executor toughness mutations: `0`

Blocked reason counts:

- `show_stance_semantics_not_confirmed`: `150`
- `toughness_target_group_mismatch:AbilityTargetAdjoinEntity:primary`: `75`
- `toughness_target_group_mismatch:AbilityTargetEntity:adjacent`: `75`
- `toughness_target_group_mismatch:AllEnemy:adjacent`: `30`
- `toughness_target_group_mismatch:AllEnemy:primary`: `30`

## Remaining Boundaries

- No toughness mutation is trusted yet because no executable `ToughnessEmissionIR` has been admitted.
- `ShowStanceList` remains display/evidence only until its combat semantics are confirmed.
- Break trigger, break damage, super-break, DoT, queue, bounce RNG, and per-hit trigger remain out of scope.

## Commands Run

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_229 --output-dir /tmp/hsr_v8_regression_v0_229
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_230 --output-dir /tmp/hsr_v8_v0_230
git diff --check
```
