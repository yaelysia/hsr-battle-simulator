# v8 TBGD Modifier Status Checkpoint v0_210

Date: 2026-06-16

## Scope

- Implemented the first TBGD modifier status pipeline:
  `TBGD modifier definition -> Canonical IR -> AddModifier EffectIR -> StatusInstance -> direct damage ModifierLedger`.
- Lowering now emits `modifier_definition` entities from ability modifier maps and `GlobalModifiers`.
- `AddModifier` lowering now standardizes `ModifierName`, `TargetType`, `DynamicValues`, `LifeTime`, `LayerAddWhenStack`, and `MaxLayer`.
- Runtime status instances are written through mutations into `UnitState.statuses` and `flags.status_details`.
- `EffectRegistry` can execute `AddModifier` through `StatusSystem` with explicit `EffectExecutionContext`.
- Direct damage formula now reads modifier terms from `actor.status` / `target.status` in addition to panel resources.

## Validation Evidence

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
```

Results:

- v0_200 through v0_210 validation: `ok=true`.
- v0_210 full ability lowering is not sampled: `ability_files=false`, `entity_tables=false`.
- Full Canonical IR is generated in memory for validation; default output stores `canonical_ir_summary_v0_210.json` to avoid committing an oversized full IR artifact. Use `--write-full-ir` only when a full local dump is needed.
- Modifier coverage:
  - `modifier_definitions=17257`
  - `global_modifier_definitions=5619`
  - `definitions_with_stack_properties=3137`
  - `AddModifier lowered=9633`
  - `AddModifier executable=7708`
- Runtime sample uses real TBGD source:
  - `Config/ConfigAbility/BattleEvent/Heliobus_Level_Ability.json`
  - `Modifier_StageAbility_HeliobusTutorial_DamageUp`
  - `AllDamageTypeAddedRatio -> actor.status damage_bonus`
- Direct damage ledger includes an applied `actor.status` term.
- Baseline direct damage in sample: `5552.704376470589`.
- Status-modified direct damage in sample: `48265.814964705874`.
- Snapshot completeness, transition contract, settlement traceability, replay, and static checks all pass.

## Remaining Risks

- This checkpoint validates only the first AddModifier status vertical slice.
- Duration ticking, refresh/stack replacement policy, removal/dispel, trigger windows, and turn lifecycle are still not implemented.
- Dynamic hash binding is intentionally not guessed; unresolved dynamic expressions are reported as unsupported.
- Only the first direct damage modifier buckets are wired: damage bonus, defense, resistance, and damage taken.
- TBGD target aliases outside `Caster`, `ModifierOwnerEntity`, `ParamEntity`, and `CurrentActionTarget` remain unsupported with explicit reasons.
