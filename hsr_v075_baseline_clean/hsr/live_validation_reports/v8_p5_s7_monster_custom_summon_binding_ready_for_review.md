# v8 P5-S7 Monster Custom / Summon Binding Ready For Review

日期：2026-07-09

## 范围

本阶段回收怪物公式参数与召唤怪参数绑定路径：

- `ValueResolver` 新增 `combatant_profile_base_stat` binding，用于从 `CombatantProfileIR.base_stats` 解析召唤怪基础属性。
- summoned monster spawn 的 `max_hp` / `attack` / `defense` / `speed` 改为经 `ValueResolver` resolution 后写入 unit、mutation metadata 和 settlement plan。
- summoned monster plan admission 增加 profile stat、monster card source、level policy source 检查；缺来源时 process-only blocked，不进入 spawn mutation。
- monster skill formula binding 通过 `skill_formula_param` resolver 验证 `data_card_kind=monster` 正例。

## 产物

- `simulator_v8_clean_core/rules/value_binding.py`
- `simulator_v8_clean_core/systems/summon.py`
- `simulator_v8_clean_core/tools/validate_p5_s7_monster_custom_summon_binding.py`
- `/tmp/hsr_v8_p5_s7_current/validation_summary_p5_s7_monster_custom_summon_binding.json`
- `/tmp/hsr_v8_p5_s7_current/p5_s7_monster_custom_summon_binding_matrix.json`

## 结果

S7 主验证输出：

```text
v8 p5_s7_monster_custom_summon_binding ok=True rows=5 classifications={'admission_gap': 1, 'boundary_only': 1, 'executable': 3} gap_counts={'admission_gap': 1}
```

summary：

```text
row_count=5
classification_counts={'admission_gap': 1, 'boundary_only': 1, 'executable': 3}
summon_value_resolution_count=4
monster_formula_binding_sample_count=1
blocked_negative_case_count=2
summon_intent_status_counts={'blocked': 761, 'executable': 14}
disallowed_gap_count=0
```

## 关键 evidence

- `summon_profile_base_stat_value_resolver`：unit spawn mutation 和 spawned unit flags 均携带 4 条 `combatant_profile_base_stat` resolution，value source 为 `CombatantProfileIR.base_stats.<field>`。
- `summon_profile_card_level_source_binding`：profile/card/source trace 来自 `CombatantProfileIR` 与 `MonsterDataCardIR`；level policy 为 `profile_base_stats_no_runtime_level_scaling`，不声明完整 runtime level scaling。
- `monster_skill_formula_binding_value_resolver`：monster skill formula 样例 `skill_formula_binding:monster_skill:100201101:1:direct_damage:param:0:monster` 通过 `skill_formula_param` resolution，source path 为 `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json`。
- `missing_profile_card_level_source_blocked`：缺 profile/card 与缺 level policy 的负例均 process-only、0 mutation、state unchanged。
- `summon_binding_replay_settlement_gap_visibility`：spawn replay 与 settlement traceability 通过；P3 inherited summon admission gap 保留为 `admission_gap`，没有被隐藏。

## 残留注意

当前 executable summon entry 的 level policy 是：

```text
kind=profile_base_stats_no_runtime_level_scaling
source_basis=CombatantProfileIR.base_stats
```

因此 S7 只证明 summoned monster profile/card/base stat source 已经接入 value binding；不把 `owner.level` 当成 TBGD level source，也不声明完整召唤怪等级缩放已完成。

P3 inherited summon gap 仍存在：

```text
summon_intent_status_counts={'blocked': 761, 'executable': 14}
```

这些 blocked intent 主要仍是 custom value hash、dynamic monster id、特殊 location / level policy unresolved 等 admission gap，留给 P5 聚合继承，不能用本阶段正例覆盖。

## 资源口径

```text
lowering_build_count=1
rulebook_build_count=1
summon_runtime_sample_count=1
monster_formula_resolver_sample_count=1
negative_runtime_sample_count=2
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
output_size=19848/18492 bytes
```

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/summon.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s7_monster_custom_summon_binding.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr_v075_baseline_clean.hsr.simulator_v8_clean_core.tools.validate_p5_s7_monster_custom_summon_binding --output-dir /tmp/hsr_v8_p5_s7_current
wc -c /tmp/hsr_v8_p5_s7_current/validation_summary_p5_s7_monster_custom_summon_binding.json /tmp/hsr_v8_p5_s7_current/p5_s7_monster_custom_summon_binding_matrix.json
cd hsr_v075_baseline_clean/hsr && PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_after_p5_s7
```

P3 summon 聚合回归输出：

```text
validation_gate_ok=True
p3_summon_foundation_closed=True
p3_summon_phase_complete=True
p3_summon_all_executable_complete=False
p3_summon_sources_classified=True
gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}
```

待 P5 收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S7 不批量实现全怪物技能、不补完整波次/关卡 override、不为缺 profile/card 的 summon intent 手写数据卡。`MonsterDataCardIR.coverage_status=lowered` 可作为 summoned monster 身份与卡来源 evidence，但不能冒充该怪物 action graph 全部 executable。
