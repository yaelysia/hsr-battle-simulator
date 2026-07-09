# v8 P5-S8 Character Trace / Eidolon Binding Ready For Review

日期：2026-07-09

## 范围

本阶段回收角色行迹、星魂、强化形态中已有真实结构来源的数值绑定：

- `ScenarioStateBuilder` 的 trace static stat mapped term 改为通过 `ValueResolver(fixed_numeric_expression)` 解析。
- eidolon `skill_add_level_list` 改为通过 `ValueResolver(fixed_numeric_expression)` 解析，并把 resolution 写入 skill level bonus source。
- eidolon effective action level 样例执行时，command metadata 继承 value resolution，transition replay/source audit 通过。
- 缺 `data_card_source` context 的 trace/eidolon 数值解析保持 blocked，不产生正例。

## 产物

- `simulator_v8_clean_core/scenarios/build_state.py`
- `simulator_v8_clean_core/tools/validate_p5_s8_character_trace_eidolon_binding.py`
- `/tmp/hsr_v8_p5_s8_current/validation_summary_p5_s8_character_trace_eidolon_binding.json`
- `/tmp/hsr_v8_p5_s8_current/p5_s8_character_trace_eidolon_binding_matrix.json`

## 结果

S8 主验证输出：

```text
v8 p5_s8_character_trace_eidolon_binding ok=True rows=5 classifications={'admission_gap': 1, 'boundary_only': 1, 'executable': 3} gap_counts={'admission_gap': 1}
```

summary：

```text
row_count=5
classification_counts={'admission_gap': 1, 'boundary_only': 1, 'executable': 3}
trace_value_resolution_count=1
eidolon_value_resolution_count=1
action_execution_sample_count=1
disallowed_gap_count=0
```

## 关键 evidence

- `trace_static_stat_value_resolver`：行迹静态属性样例 `target_key=defense`，`before=100.0`、`after=105.0`，term 中携带 `fixed_numeric_expression` value resolution。
- `eidolon_skill_level_value_resolver`：星魂技能等级样例 `avatar_skill:1100404`，bonus=2，source payload 携带 `fixed_numeric_expression` value resolution。
- `eidolon_effective_level_replay_source_audit`：同一 action 使用较低 requested level 执行，effective level 由星魂 bonus 提升；transition replay 和 source audit 均通过。
- `missing_trace_eidolon_value_context_blocked`：trace/eidolon 缺 `data_card_source` context 时均 `context_missing:data_card_source` blocked。
- `character_gap_visibility`：trace/eidolon 仍保留 admission gap，不声明全角色机制完成。

## 残留注意

S8 只回收真实结构来源中已能数值绑定的 trace static stat 与 eidolon skill level bonus。以下仍不属于本阶段完成范围：

```text
trace_ability_hook blocked
eidolon_extra_effect_id runtime admission pending
文本缩放依据缺解释
缺事件源 / 缺目标源 / 缺动态 binding 的 startup ability
装备与遗器
```

## 资源口径

```text
lowering_build_count=1
rulebook_build_count=1
scenario_builder_runtime_samples=2
combat_executor_runtime_sample_count=1
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
output_size=11668/10268 bytes
```

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/scenarios/build_state.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s8_character_trace_eidolon_binding.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr_v075_baseline_clean.hsr.simulator_v8_clean_core.tools.validate_p5_s8_character_trace_eidolon_binding --output-dir /tmp/hsr_v8_p5_s8_current
wc -c /tmp/hsr_v8_p5_s8_current/validation_summary_p5_s8_character_trace_eidolon_binding.json /tmp/hsr_v8_p5_s8_current/p5_s8_character_trace_eidolon_binding_matrix.json
cd hsr_v075_baseline_clean/hsr && PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s8_trace_eidolon_level_resource_hooks --output-dir /tmp/hsr_v8_p4_s8_after_p5_s8
cd hsr_v075_baseline_clean/hsr && PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s11_action_query_contract --output-dir /tmp/hsr_v8_p4_s11_after_p5_s8
cd hsr_v075_baseline_clean/hsr && PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_after_p5_s8
```

回归输出：

```text
P4-S8: ok=True rows=9 classifications={'admission_gap': 4, 'boundary_only': 2, 'executable': 3}
P4-S11: ok=True rows=6 classifications={'boundary_only': 2, 'executable': 4}
P2: ok=True, p2_status_substrate_complete=True, p2_all_status_sources_classified=True
```

待 P5 收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S8 不解释技能文本，不全量完成所有角色卡，不补装备/遗器。使用的角色样本来自结构化 predicate 选择：trace sample 按 `trace_static_stat_bonus` executable term 选择；eidolon sample 按 `skill_add_level_list` 且 action query 可选选择，不按角色名硬编码。
