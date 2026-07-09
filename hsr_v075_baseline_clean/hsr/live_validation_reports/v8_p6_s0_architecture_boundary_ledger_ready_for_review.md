# v8 P6-S0 架构越界总账本 ready_for_review

## 阶段边界

本阶段只建立 P6 架构边界总账本，不修改 runtime 行为，不搬迁伤害、削韧、召唤、波次或场景构建逻辑，不修改 `P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md` checklist。

本阶段新增轻量验证脚本：

```text
simulator_v8_clean_core/tools/validate_p6_s0_architecture_boundary_ledger.py
```

脚本只做当前源码证据扫描和结构化矩阵输出，不构建 TBGD lowering，不构建 RuleBook，不写完整 IR、RuleBook 或 transition dump。

## 验证输出

运行目录：

```text
hsr_v075_baseline_clean/hsr
```

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p6_s0_architecture_boundary_ledger --output-dir /tmp/hsr_v8_p6_s0_current
```

输出：

```text
v8 p6_s0_architecture_boundary_ledger ok=True rows=23 violations=10 questions_checked=5/5 classifications={'audit_only': 9, 'content_assembly_in_runtime': 5, 'fallback_execution_violation': 2, 'rule_input_violation': 3, 'scenario_assembly_ok': 4}
```

产物：

```text
/tmp/hsr_v8_p6_s0_current/validation_summary_p6_s0_architecture_boundary_ledger.json
/tmp/hsr_v8_p6_s0_current/p6_s0_architecture_boundary_ledger_matrix.json
```

## Summary

脚本 summary 关键字段：

```text
row_count=23
questions_checked=5/5
classification_counts:
  audit_only=9
  content_assembly_in_runtime=5
  fallback_execution_violation=2
  rule_input_violation=3
  scenario_assembly_ok=4
violation_row_count=10
unclear_count=0
evidence_missing_count=0
invalid_classification_count=0
invalid_question_count=0
high_risk_scan_uncovered_file_count=0
high_risk_scan_excluded_file_count=1
runtime_behavior_changed=false
s0_ready_for_s1_to_s5_routing=true
```

高风险扫描覆盖门槛：

```text
required_file_count=10
covered_file_count=9
excluded_file_count=1
uncovered_file_count=0
```

被覆盖文件：

```text
simulator_v8_clean_core/core/executor.py
simulator_v8_clean_core/core/source_audit.py
simulator_v8_clean_core/rules/value_binding.py
simulator_v8_clean_core/scenarios/build_state.py
simulator_v8_clean_core/scenarios/identity.py
simulator_v8_clean_core/systems/action_availability.py
simulator_v8_clean_core/systems/dynamic_values.py
simulator_v8_clean_core/systems/summon.py
simulator_v8_clean_core/systems/wave.py
```

明确排除：

```text
simulator_v8_clean_core/systems/unit_lifecycle.py
reason=UnitLifecycleSystem receives an already-built UnitState and creates lifecycle mutations; it does not read content cards or assemble combatant rules.
```

## 五个问题覆盖

1. 结算是否从审计来源反查规则：
   - `rule_input_violation`: `core/executor.py::_damage_value_resolution` 从 `damage_plan.hit_source_trace` 递归提取 `skill_formula_binding`。
   - `rule_input_violation`: `core/executor.py::_toughness_value_resolution` 从 `toughness_plan.source_trace` 派生 numeric binding sources。
   - `rule_input_violation`: `systems/dynamic_values.py::character_skill_param_binding_source` 从角色卡 source evidence 读取 `character_config_dynamic_value_bindings`。
   - `audit_only`: `core/action_plan.py::build_action_execution_plan` 已有 `DamageEmissionIR` / `ToughnessEmissionIR` 显式机制入口，可作为 S1 回正目标。
   - `audit_only`: `rules/value_binding.py::ValueResolver` 消费显式 `ValueBindingRequest`，自身是目标收敛合同；问题在调用方从 trace/evidence 构造 request。

2. 召唤 / servant / 波次生成单位是否在 runtime 临时拼装：
   - `content_assembly_in_runtime`: `systems/summon.py::plan_spawn_summoned_monster` 读取 `combatant_profile` 和 `monster_data_card`。
   - `content_assembly_in_runtime`: `systems/summon.py::apply_spawn` 重新读取 `SummonMonsterIntentIR` 并调用 `_unit_from_entry`。
   - `content_assembly_in_runtime`: `systems/summon.py::_unit_from_entry` 组装 stats、resources、timeline、flags 和 `UnitState`。
   - `content_assembly_in_runtime`: `systems/summon.py::apply_spawn_servant` / `_unit_from_servant_definition` 重新读取 servant definition 并拼 `UnitState`。
   - `content_assembly_in_runtime`: `systems/wave.py` next-wave spawn 使用 `_unit_from_wave_entry` 拼单位。

3. 初始配置 / 场景 / UI 是否推导战斗规则：
   - `scenario_assembly_ok`: `scenarios/build_state.py` 当前做初始 UnitState 装配，不是 route-time 规则执行；但和 summon/wave unit birth 有重复，归入 P6-S3。
   - `scenario_assembly_ok`: 初始 wave spec 计算初始 AV，归 P6-S3 统一 birth-order 复查。
   - `scenario_assembly_ok`: `scenarios/build_state.py::_apply_initial_servant` 读取 servant definition 并调用 SummonSystem，归 P6-S2/P6-S3 统一出生单。
   - `scenario_assembly_ok`: `scenarios/identity.py` 读取 servant definition 做初始配置身份校验和来源收集，非机制执行。
   - `audit_only`: `systems/action_availability.py` 读取角色卡 / 怪物卡 / servant definition 生成行动查询来源说明，非 mutation 路径。
   - `audit_only`: `simulator_v8_ui/report.py` 消费后端候选和 target ids 做展示/选择，不自行判断目标合法性。

4. 内容卡是否执行机制 / core 是否写具体内容特判：
   - `audit_only`: `systems/enemy_action.py` 明确是 read-only candidate generation，只消费已 lowered 的 `MonsterDataCardIR.action_sequence`，不选目标、不执行动作。
   - `audit_only`: `rules/evaluator.py::ByCompareMonsterID` 使用 IR payload 比较目标 monster id，并在缺目标/缺 numeric 时 blocked；不是固定 MonsterID 特判。
   - `audit_only`: `core/source_audit.py::_audit_summon_mutation` 读取 servant / summon IR 只用于 source audit 校验，不驱动 mutation。

5. 缺资料 / 缺计算说明 / 缺目标时是否默认执行：
   - `fallback_execution_violation`: `_toughness_value_resolution` 在 dynamic hash 失败后 fallback 到 `ActionDefinitionIR.show_stance_list`。
   - `fallback_execution_violation`: `_damage_value_resolution` 在 trace 中无 formula binding 时 fallback 到 fixed `damage_plan.scaling_ratio`。
   - `audit_only`: missing damage/toughness emission 已有 blocked reason。
   - `audit_only`: status callback payload target fallback 缺有效 payload 时返回空 tuple，不默认 actor/all/enemy。

## 后续阶段归属

```text
P6-S1:
  - q1_damage_value_resolution_reads_formula_binding_from_trace
  - q1_toughness_value_resolution_reads_binding_sources_from_trace
  - q5_toughness_show_stance_list_fallback_after_dynamic_hash
  - q5_damage_formula_binding_absent_fixed_ratio_fallback
  - q5_missing_damage_or_toughness_emission_blocks
  - q1_value_resolver_consumes_explicit_value_binding_requests

P6-S2:
  - q2_summon_plan_reads_profile_and_monster_card
  - q2_summon_apply_reloads_intent_and_builds_units
  - q2_summon_unit_from_entry_constructs_combat_unit
  - q2_servant_spawn_reopens_definition_and_constructs_unit
  - q3_initial_servant_setup_reads_definition_and_invokes_summon_system

P6-S3:
  - q3_wave_runtime_constructs_next_wave_units
  - q3_initial_scenario_unit_assembly
  - q3_initial_wave_spec_derives_unit_setup
  - q3_identity_initial_servant_definition_validation
  - q3_initial_servant_setup_reads_definition_and_invokes_summon_system

P6-S4:
  - q4_enemy_action_read_only_candidate_from_card
  - q4_condition_compare_monster_id_uses_ir_payload
  - q3_action_availability_reads_data_cards_for_query_source_context

P6-S5:
  - q1_dynamic_value_store_reads_character_card_source_evidence
  - q1_value_resolver_consumes_explicit_value_binding_requests
  - q3_action_availability_reads_data_cards_for_query_source_context
  - q4_source_audit_reads_summon_ir_for_audit_only
  - q3_ui_report_consumes_candidate_targets
  - q5_status_callback_payload_target_fallback_returns_empty_when_missing
```

## 资源与范围

本阶段没有运行 P1-P5 聚合，因为没有修改 runtime 行为。验证脚本记录：

```text
tbgd_lowering_build_count=0
rulebook_build_count=0
subprocess_validation_count=0
large_artifacts_written=false
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
```

## 结论

P6-S0 已提交 `ready_for_review` evidence。该报告不代表阶段 done；是否勾选 P6 checklist 仍需验收线程复核脚本、矩阵、源码证据和验证输出。
