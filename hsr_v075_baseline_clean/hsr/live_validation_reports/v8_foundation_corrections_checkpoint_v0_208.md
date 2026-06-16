# v8 Foundation Corrections Checkpoint v0_208

## Scope

This checkpoint corrects the foundation issues found after v0_207.

- Key TBGD Excel tables are no longer truncated to the first 500 rows.
- Damage taxonomy now recognizes Elation damage, true damage, and HP loss separately.
- Target legality is driven by `TargetPolicy`, not a hard-coded same-side rejection.
- `CombatExecutor.execute()` now produces damage mutations in the main action transition.
- True damage and HP loss both bypass normal damage multipliers, while keeping different settlement semantics.

## Implemented

- `TBGDLowering` defaults key entity/action tables to full-table lowering.
- IR metadata and coverage output include table `raw_count`, `lowered_count`, and `skipped_count`.
- `ActionDefinitionIR` no longer defaults unknown damage to `direct`.
- `AttackType=ElationDamage` lowers to `damage_formula_family=elation`.
- Global damage behavior templates lower `TrueDamage`, `DirectlyLoseHp`, and `DirectlyLoseHpHit` evidence.
- `TargetPolicy` supports enemy, ally, self, and defeated-target policy decisions.
- Executor damage smoke uses the action definition and records damage in the same transaction as target/resource/timeline.
- `true_damage` settlement remains `record_type=damage`.
- `hp_loss` settlement uses `record_type=hp_loss`.
- Both true damage and HP loss set `bypasses_normal_multipliers=true` and emit no normal multiplier terms.

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
```

Results:

- v0_200 ok=true
- v0_203 ok=true
- v0_204 ok=true
- v0_205 ok=true
- v0_206 ok=true
- v0_207 ok=true
- v0_208 ok=true
- v0_208 replay ok=true, mutations=7
- v0_208 settlement traceability ok=true, checked_records=10

Key counts:

- IR entities: 4893
- IR action definitions: 6949
- IR formulas: 3185
- Key entity/action tables sampled=false
- Ability files sampled=true and explicitly marked in metadata
- Elation action definitions found: 106

## Current Distance

Minimum usable battle route is closer but still not ready. v8 now has clean full-table identity/action lowering, target/resource/timeline/damage in one transition, and corrected fixed-damage semantics. It still lacks full TBGD-driven direct damage formulas, status modifiers, trigger execution, toughness/break, queues, turn end, kill/wave processing, and route-level scenario reconstruction.

Approximate progress toward a minimal usable combat vertical slice: 22%.

Approximate progress toward game-faithful full combat replication: 7%-10%.

## Known Risks

- Direct damage amount is still `v0_208_base_amount_only`, not the real full formula.
- Elation damage is correctly classified but still blocked for formula execution.
- Ability lowering remains sampled for validation speed; this is explicitly marked and must not be treated as full runtime coverage.
- True damage and HP loss fixed-amount behavior is implemented, but later event-window and shield interaction details still need validation.
