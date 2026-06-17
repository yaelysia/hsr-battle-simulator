# v8 Trigger Effect Spine Checkpoint v0_211

Date: 2026-06-17

## Scope

- Added stable `trigger_windows` to every `BattleTransition`.
- Added status-local trigger lookup from Canonical IR:
  `StatusInstance.trigger_ids_by_event -> RuleBook.triggers_for_modifier_event`.
- Wired action lifecycle windows into `CombatExecutor.execute()`:
  `OnBeforeSkillUse`, `OnBeforeAttack`, `OnAfterAttack`, `OnAfterSkillUse`.
- Added `TriggerSystem` execution through:
  `TriggerIR -> ConditionIR -> EffectIR -> EffectRegistry -> Mutation/Settlement`.
- Unsupported condition/effect paths now emit process-only records with explicit reason.
- Effect mutations are applied in window order, so later windows and damage see updated state.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir validation_outputs_v0_211
```

Results:

- v0_200 through v0_211 validation: `ok=true`.
- v0_211 full ability lowering is not sampled: `ability_files=false`, `entity_tables=false`.
- Canonical IR trigger count: `27368`.
- Runtime sample uses real TBGD source:
  - `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json`
  - pre-status: `MAvatar_Advanced_Seele_00_Skill02InsertMuteSp_Clean`
  - trigger window: `OnAfterSkillUse`
  - triggered AddModifier: `MAvatar_Advanced_Seele_00_Skill02InsertCD_ShowBuff`
- Sample action transition contains all four canonical trigger windows.
- Trigger window execution produced status mutations inside the same action transition.
- Unsupported `RemoveModifier` / `RemoveSelfModifier` effects in the sample trigger are recorded as unsupported process-only effects.
- Snapshot completeness, transition contract, settlement traceability, replay, and static checks all pass.

## Remaining Risks

- This checkpoint only supports status-local trigger windows.
- `OnListen*`, being-hit, turn-end, global watcher, and queue-related trigger windows remain audit-only.
- Unsupported conditions block execution; no condition is guessed as true.
- `RemoveModifier`, `RemoveSelfModifier`, duration tick, refresh/stack policy, dispel, and turn lifecycle are not implemented yet.
- Trigger ordering is fixed to unit order, status detail order, trigger order, effect order; advanced priority semantics still need TBGD evidence.
