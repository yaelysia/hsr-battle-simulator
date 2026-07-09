# v8 P5-S5 Damage/Toughness ValueResolver Consumers Ready For Review

日期：2026-07-09

## 范围

本阶段把第一批 runtime consumer 接入 `ValueResolver`：

- `CombatExecutor` 的 direct damage packet 构造前先解析 damage value resolution。
- `CombatExecutor` 的 toughness packet 构造前先解析 toughness value resolution。
- damage mutation、damage settlement、toughness mutation、toughness settlement 均携带 `value_resolution`。
- toughness dynamic hash 若缺少可绑定运行时来源，回落到同一 action 的 `ActionDefinitionIR.show_stance_list[hit_index]`；越界或缺 action 仍 blocked。
- heal / shield / hp-loss 本阶段只做来源扫描和范围归类，不合成正例。

## 产物

- `simulator_v8_clean_core/core/executor.py`
- `simulator_v8_clean_core/systems/toughness.py`
- `simulator_v8_clean_core/tools/validate_p5_s5_damage_toughness_value_resolver_consumers.py`
- `/tmp/hsr_v8_p5_s5_damage_toughness_value_resolver_consumers/validation_summary_p5_s5_damage_toughness_value_resolver_consumers.json`
- `/tmp/hsr_v8_p5_s5_damage_toughness_value_resolver_consumers/p5_s5_damage_toughness_value_resolver_consumers_matrix.json`

## 结果

S5 主验证输出：

```text
v8 p5_s5_damage_toughness_value_resolver_consumers ok=True rows=5 classifications={'executable': 4, 'source_absent_not_required': 1} gap_counts={}
```

summary：

```text
row_count=5
classification_counts={'executable': 4, 'source_absent_not_required': 1}
damage_value_resolution_count=1
toughness_value_resolution_count=1
runtime_action_sample_count=1
disallowed_gap_count=0
```

runtime sample：

```text
action_id=avatar_skill:111204
action_level=15
actor_data_card_id=character_data_card:avatar:1112
damage_mutation_count=1
toughness_mutation_count=1
```

## 关键 evidence

- `damage_consumer_value_resolver`：damage mutation 与 settlement 均携带 `value_resolution.ok=true`；样例来源是 `AbilityDamageEmission` 的 source-backed `fixed_numeric_expression`，source path 为 `Config/ConfigAbility/Avatar/Avatar_Topaz_00_Ability.json`。
- `toughness_consumer_value_resolver`：toughness mutation 与 settlement 均携带 `value_resolution.ok=true`；样例最终 value source 为 `ActionDefinitionIR.show_stance_list[0]`，并保留 preceding dynamic hash blocked evidence：`dynamic_hash_unbound:1659254037`。
- `blocked_value_resolution_no_damage_mutation`：缺 value resolution 的 damage packet 返回 process-only error，无 mutation，空 mutation replay 通过。
- `consumer_source_audit_replay`：runtime transition replay 通过；source audit `checked_mutations=22`、`checked_records=28`、`trace_count=22`、`ok=true`。
- `heal_shield_hp_loss_consumer_scope`：当前范围不合成 heal/shield/hp-loss 正例，归类为 `source_absent_not_required`，不声明这些 consumer 已完成。

## 资源口径

S5 验证默认只写 summary/matrix，不写完整 IR、RuleBook 或 transition dump：

```text
lowering_build_count=1
rulebook_build_count=1
combat_executor_runtime_sample_count=1
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
output_size=60K/56K
```

## 验证

已运行：

```bash
python3 -m py_compile hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/toughness.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s5_damage_toughness_value_resolver_consumers.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s5_damage_toughness_value_resolver_consumers --output-dir /tmp/hsr_v8_p5_s5_damage_toughness_value_resolver_consumers
du -h /tmp/hsr_v8_p5_s5_damage_toughness_value_resolver_consumers/validation_summary_p5_s5_damage_toughness_value_resolver_consumers.json /tmp/hsr_v8_p5_s5_damage_toughness_value_resolver_consumers/p5_s5_damage_toughness_value_resolver_consumers_matrix.json
```

待本阶段收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S5 不证明所有 damage consumer 都已经迁移到 `SkillFormulaBindingIR.param_value`；本次 runtime 样例证明的是 source-backed fixed expression 也必须经 `ValueResolver` admission 后才能产生 mutation。S0 中存在 `missing_consumer_refs` 的 source family 不能作为 S5 consumer 已接入证明，后续 S6 仍按真实 runtime mutation/settlement evidence 判定。
