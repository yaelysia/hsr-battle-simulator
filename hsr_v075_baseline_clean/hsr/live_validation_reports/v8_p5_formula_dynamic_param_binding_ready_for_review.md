# v8 P5 Formula / Dynamic / Param Binding Ready For Review

日期：2026-07-09

## 范围

P5-S10 聚合 S0-S9 子矩阵，提交公式、动态值、自定义值、技能参数、等级缩放和运行时上下文绑定的底座验收包。执行线程仅提交 `ready_for_review`，不修改 P5 checklist，不声明 `done`。

## 产物

- `simulator_v8_clean_core/rules/value_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_formula_dynamic_param_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s0_formula_dynamic_source_ledger.py`
- `simulator_v8_clean_core/tools/validate_p5_s1_value_binding_contract.py`
- `simulator_v8_clean_core/tools/validate_p5_s2_static_param_level_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s3_dynamic_custom_binding_projection.py`
- `simulator_v8_clean_core/tools/validate_p5_s4_value_resolver_admission.py`
- `simulator_v8_clean_core/tools/validate_p5_s5_damage_toughness_value_resolver_consumers.py`
- `simulator_v8_clean_core/tools/validate_p5_s6_resource_status_callback_consumers.py`
- `simulator_v8_clean_core/tools/validate_p5_s7_monster_custom_summon_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s8_character_trace_eidolon_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s9_negative_audit_replay_migration.py`
- `/tmp/hsr_v8_p5_formula_dynamic_param_binding_current/validation_summary_p5_formula_dynamic_param_binding.json`
- `/tmp/hsr_v8_p5_formula_dynamic_param_binding_current/p5_formula_dynamic_param_binding_matrix.json`

## 聚合结果

P5 主验证输出：

```text
v8 p5_formula_dynamic_param_binding validation_gate_ok=True p5_substrate_complete=True p5_all_executable_complete=False gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
```

summary：

```text
stage_count=10
failed_stage_count=0
p5_formula_dynamic_param_binding_substrate_complete=true
p5_all_executable_complete=false
p5_sources_classified=true
p5_classification_counts={'admission_gap': 17, 'boundary_only': 9, 'executable': 48, 'source_absent_not_required': 1}
p5_gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
allowed_gap_evidence_summary={'row_count': 32, 'allowed_gap_count': 1509172, 'disallowed_gap_count': 0, 'all_evidence_ok': True}
positive_sample_count=16
blocked_sample_count=16
source_audit_replay_sample_count=16
```

## S0 注意继承

S0 验收时提到的部分 `missing_consumer_refs` 未被当成 consumer 已接入证明。S1/S5/S6/S10 聚合只使用直接 IR consumer/source evidence、stage row checks 和 gap evidence；S0 的缺失引用只保留为 ledger 背景，不提升为 executable consumer admission。

## 关键机制

- `ValueResolver` 统一准入 `skill_formula_param`、`dynamic_hash`、`fixed_numeric_expression`、`runtime_numeric_expression`、`combatant_profile_base_stat` 等 binding kind。
- damage/toughness/resource/status callback/queue/summon/trace/eidolon 消费侧写入 `value_resolution`，source audit 和 replay 正例通过。
- 缺 context、缺 binding、未知 binding kind、缺 profile/card/level source 等负例均 blocked 或 process-only，state unchanged。
- 旧 P4-S9/v0_231 toughness helper 已迁移：P5 后真实 `SetDynamicValue` 会写入动态值，验证样例改为调整目标韧性边界，不压低 runtime 真实来源值。

## 回归结果

S10 阶段验收集已串行运行：

```text
compileall: pass
P5 aggregate: validation_gate_ok=True, p5_substrate_complete=True, p5_all_executable_complete=False
P1-9: ok=True, phase1_minimum_battle_slice=True
P2: ok=True, p2_status_substrate_complete=True, p2_all_status_sources_classified=True
P3: validation_gate_ok=True, p3_summon_foundation_closed=True, p3_summon_phase_complete=True, p3_summon_all_executable_complete=False
P4: validation_gate_ok=True, p4_substrate_complete=True, p4_all_executable_complete=False
git diff --check: pass
P5 untracked trailing whitespace check: pass
```

保留既有跨阶段 gap：

```text
P3 gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}
P4 gap_counts={'admission_gap': 1333000, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 55, 'unclassified': 0, 'validation_gap': 0}
P5 gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
```

## 资源口径

P5 聚合输出：

```text
validation_summary_p5_formula_dynamic_param_binding.json = 93032 bytes
p5_formula_dynamic_param_binding_matrix.json = 114634 bytes
lowering_build_count=1
rulebook_build_count=1
subprocess_validation_count=0
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
s9_reused_s5_to_s8_stage_matrices=true
```

回归 summary 大小：

```text
P1-9 summary = 1105224 bytes
P2 summary = 2619559 bytes
P3 summary = 17027 bytes
P4 summary = 24286 bytes
```

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_formula_dynamic_param_binding_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_p5_regression
git diff --check
```

## 当前做到哪里

P5 底座闭环已可验收：公式/动态值/参数绑定从 source ledger、IR/RuleBook contract、ValueResolver admission 到 runtime consumers、negative/source-audit/replay、聚合继承 gap 的链路已经打通。

距离最小可用战斗纵切：P1 最小完整战斗纵切仍通过；P5 没引入会阻断 P1 的 implementation/lowering/validation gap。

距离完整复刻：仍缺完整角色面板装配、全量角色/怪物机制、装备/遗器/关卡环境、更多目标系统、波次/阶段/关卡倍率、全正例公式和动态值消费者。P5 当前不是全正例完成，`p5_all_executable_complete=false` 是预期结果。
