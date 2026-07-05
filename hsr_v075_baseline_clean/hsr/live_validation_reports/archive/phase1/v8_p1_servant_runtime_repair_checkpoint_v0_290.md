# v8 P1 servant runtime repair checkpoint v0.290

日期：2026-07-04

## 结论

本检查点完成 P1 修复计划中 servant/忆灵相关的 implementation_missing 项：

- `AvatarServantConfig` / `AvatarServantSkillConfig` 已进入 TBGD lowering、ActionDefinition、ActionAbilityBinding、CombatantActionSet 与 `ServantDefinitionIR`。
- `ServantDefinitionIR` 现在可基于 owner/stat/timeline/action/lifecycle admission 形成 `executable` unit representation。
- blocked servant skill 槽位不会使整个 servant definition 失败；可执行槽位进入 `executable_binding_ids`，不可执行槽位进入 `skipped_slots` 审计。
- `SummonSystem` 支持通用 `servant_spawn`、标准 UnitLifecycle spawn/remove mutation、`summon_runtime.servants` registry 与 removal 标记。
- `TargetSystem` 支持 `ServantEntityList`、`CasterServant`、`GetServant`、`RemoveServant`、`GetSummoner`，并要求 runtime entity source trace，flag-only 伪 servant 不会被解析为目标。
- `BattleSetup.initial_summons(kind="servant")` 走同一套 servant definition admission 与 summon runtime，不再是 blocked 占位。
- P1-3、P1-6、P1-8、P1-9 验证均改为真实 servant 正例 + 负例边界，而不是把 blocked/no mutation 当完成。

## 来源边界

本次正例来源：

- `ExcelOutput/AvatarServantConfig.json`
- `ExcelOutput/AvatarServantSkillConfig.json`
- `Config/ConfigCharacter/Servant/*.json`
- `Config/ConfigAbility/Servant/*.json`
- `Config/GlobalConfig/TargetAliasConfig.json`
- `Config/GlobalConfig/TargetOperationConfig.json`

runtime 仍只读取 Canonical IR / RuleBook / scenario IR，不读取 raw TBGD、TextMap、旧 v7 或 model pack。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_servant_target_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_servant_setup_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_servant_repair
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

P1-9 输出：

```text
ok=True
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=True
```

P1-9 source-gap matrix 中：

- `p1_6.servant_target`: `executable`
- `p1_8.servant_initial_setup`: `executable`
- `p1_5.follow_up`: `source_absent_not_required`
- `p1_5.counter`: `source_absent_not_required`
- `p1_5.assistant`: `boundary_only`

## 尚未宣称完成

本次只完成 servant unit runtime、action availability、target registry、BattleSetup initial setup 的通用纵切。仍未宣称：

- servant damage stat binding 完整复刻；当前 attack/defense 仅作为 `UnitState` schema carry，不作为 servant damage formula admission。
- battle_unit_summon 自动战斗生成；`SummonUnitData` 仍按 catalog/boundary-only 处理。
- assistant queue family executable；当前 P1-9 仍记录为 boundary-only。
