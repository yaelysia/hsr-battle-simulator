# v8 Damage Emission Task Checkpoint v0_223

## Scope

- Added `DamageEmissionIR` as the task-sourced damage emission boundary:
  `AbilityTaskIR -> DamageEmissionIR -> ActionExecutionPlan.damage_plan -> DamagePacket`.
- Runtime damage packets now carry `damage_emission_id`, `source_task_id`, `hit_profile_id`, source trace, and numeric fidelity metadata.
- Removed placeholder damage emissions that were not traceable to real `AbilityTaskIR`; missing or non-executable emissions are now reported as process-only `damage_emission_blocked` settlement records.
- Strengthened static checks so runtime core/systems cannot hardcode raw damage task opcodes such as `DamageByAttackProperty` or `AttackData`.

## Validation Summary

- `validate_v0_223`: `ok=true`
- TBGD discovery files: `8683`
- Canonical IR:
  - action definitions: `6949`
  - ability tasks: `83202`
  - hit profiles: `5132`
  - damage emissions: `360`
  - damage emission status: `150 executable`, `210 blocked`
- Blocked emission reasons:
  - `damage_target_group_mismatch:AbilityTargetAdjoinEntity:primary`: `75`
  - `damage_target_group_mismatch:AbilityTargetEntity:adjacent`: `75`
  - `damage_target_group_mismatch:AllEnemy:adjacent`: `30`
  - `damage_target_group_mismatch:AllEnemy:primary`: `30`

## Acceptance Notes

- At least one real mainline avatar action emits direct damage from `AbilityTaskIR` sourced `DamageEmissionIR`.
- Damage settlement and mutation metadata both include emission/task/source trace.
- Actions without executable damage emission do not create fake damage mutations and produce blocked process records instead.
- Existing direct damage, true damage, hp loss, status ledger, snapshot, transition, settlement traceability, replay, and static contracts remain part of the regression suite.

## Remaining Risks

- `DamageEmissionIR` currently covers the first confirmed task family (`DamageByAttackProperty`) and target-group mapping only; `AttackData` and other damage task semantics remain blocked/audit candidates until confirmed.
- AOE/blast damage is still structural-only for numeric fidelity; target-group multipliers, per-hit trigger context, and multi-hit sequencing are not implemented.
- No toughness, break, DoT, super-break, bounce RNG, queue insertion, or full Ability VM execution in this checkpoint.
