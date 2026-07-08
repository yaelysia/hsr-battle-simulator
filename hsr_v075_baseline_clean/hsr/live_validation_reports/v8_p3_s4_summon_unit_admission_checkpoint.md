# v8 P3-S4 SummonUnitData 来源拆分和 runtime admission 检查点

日期：2026-07-06

## 本步完成

- `SummonUnitDefinitionIR` 的 lowering 增加 `raw_flags`、`source_mode`、`config_markers` 和结构化 `battle_admission`，把 definition/catalog 与 runtime spawn trigger 明确分离。
- `ConfigSummonUnit` 摘要补充 `has_trigger_config`、`has_resident_effects`、`on_create_opcodes`、`on_destroy_opcodes`、`trigger_opcodes` 和 adventure/maze marker。
- `SummonUnitData` 分类从旧的粗略 battle candidate 回正为非战斗 runtime 边界：client/visual、destroy-on-enter-battle、adventure/maze。
- 新增 `simulator_v8_clean_core.tools.validate_p3_s4_summon_unit_admission`，验证 raw -> IR 分类、全 TBGD 引用扫描、battle runtime source boundary、required runtime sources 和 runtime blocked/state unchanged。
- 修正 S0 总账本的 gap 归因：`summon_unit_adventure_or_maze_not_combat_runtime` 是边界原因，不是 `implementation_missing`。

## 关键计数

```text
definition_count=36
raw_count=36
failed_group_count=0

source_mode_counts.client_or_visual=9
source_mode_counts.destroy_on_enter_battle=21
source_mode_counts.adventure_or_maze=6

summon_kind_counts.client_or_visual_summon=9
summon_kind_counts.destroy_on_enter_battle_summon=21
summon_kind_counts.adventure_or_maze_summon=6

blocked_reason_counts.summon_unit_client_only_not_combat_runtime=9
blocked_reason_counts.summon_unit_destroy_on_enter_battle_not_battle_spawn=21
blocked_reason_counts.summon_unit_adventure_or_maze_not_combat_runtime=6

battle_runtime_trigger_ref_count=0
adventure_trigger_ref_count=124
non_battle_ref_count=1379
```

Case group 结果：

```text
raw_ir_classification: boundary_only, ok=True
reference_trigger_scan: source_absent_not_required, ok=True
battle_runtime_source_boundary: source_absent_not_required, ok=True
required_runtime_sources: boundary_only, ok=True
runtime_blocked_boundary: boundary_only, ok=True
```

## 分层结论

- 当前数据库中没有可执行的 `SummonUnitData` battle runtime 来源。全库引用扫描没有发现 battle ability / battle stage / battle event / monster / avatar 下的 runtime trigger。
- 36 条 raw definition 都有 IR definition，但都只是 definition/catalog 或非战斗 runtime 边界；看到 `SummonUnitData` 不能直接创建战斗单位。
- `IsClient`、`DestroyOnEnterBattle`、`FollowUnit`、`FollowField`、`Field`、`AddMazeBuff`、`RemoveEffect`、adventure ability 等证据已进入 source evidence，作为 blocked admission 的来源。
- battle runtime 所需的 unit profile、stats、position、lifetime、targetability、actionability 在当前数据库没有对应真实 trigger，因此全部保持 blocked / process-only / state unchanged。
- 本步没有 `SummonUnitData` 正例 spawn；这是 `source_absent_not_required` 收口，不是 validation gap 或 runtime fallback。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s4_summon_unit_admission --output-dir /tmp/hsr_v8_p3_s4_summon_unit_admission
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory --output-dir /tmp/hsr_v8_p3_s0_summon_source_inventory_p3_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s1_summon_ir_rulebook_contract --output-dir /tmp/hsr_v8_p3_s1_summon_ir_rulebook_contract_p3_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_summoned_monster_spawn_p3_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_p3_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_p3_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s4_summon_unit_admission validation ok=True
v8 p3_s0_summon_source_inventory validation ok=True
v8 p3_s1_summon_ir_rulebook_contract validation ok=True
v8 p3_s3_summoned_monster_spawn validation ok=True
v8 p1_8_battle_setup validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
```

## 本步没有完成

- 没有实现 `SummonUnitData` battle runtime spawn，因为当前数据库没有真实 battle runtime trigger。
- 没有把 client / visual / adventure / maze summon 纳入 combat core。
- 没有处理 servant 属性、生命周期和 owner 关系完整化；这是 P3-S5。
- 没有放开 assistant actor/stats/action graph 执行；这是 P3-S7。

## 后续影响

- P3-S0/S1 中旧的 `SummonUnitData` battle candidate admission gap 已回正为当前数据库 source absent / boundary。
- 后续若 TBGD 增加真实 battle runtime trigger，应先扩展 S4 引用扫描和 admission，再接入 runtime spawn。
- P3-S5 可以继续推进 servant / 忆灵定义、属性、生命周期和 owner 关系，不需要等待 `SummonUnitData` battle unit spawn。
