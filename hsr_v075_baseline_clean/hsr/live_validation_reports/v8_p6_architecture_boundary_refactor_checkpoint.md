# v8 P6 架构边界回正验收检查点

## 阶段边界

本报告覆盖 P6-S1 到 P6-S6 的执行证据及验收线程复核结果。P6 唯一 checklist 已由验收线程在代码审查、对抗性复现和 P1-P6 回归全部通过后更新。

P6 目标是边界回正，不是机制覆盖率扩面：

- 伤害 / 削韧 runtime 消费显式计算入口，不从 source/audit trace 或 raw path 文本反查规则。
- lowering 将 summon / servant / wave 出生模板投影为一等 Canonical IR；runtime 只物化请求绑定规格，apply 不重新理解内容卡，也不为坏出生单补默认单位。
- dynamic value caller 不直接挖 data-card source evidence。
- RuleBook / static checks 增加边界防线。
- 聚合继承允许延期的 S0-S5 gap，并对任何未列入显式延期白名单的 P6 自有越界直接失败；当前白名单为空。

## 主要代码产物

```text
simulator_v8_clean_core/core/action_plan.py
simulator_v8_clean_core/core/executor.py
simulator_v8_clean_core/rules/ir.py
simulator_v8_clean_core/tbgd/lowering.py
simulator_v8_clean_core/systems/unit_spawn.py
simulator_v8_clean_core/systems/summon.py
simulator_v8_clean_core/systems/wave.py
simulator_v8_clean_core/systems/dynamic_values.py
simulator_v8_clean_core/rules/rulebook.py
simulator_v8_clean_core/tools/validate_p6_s1_damage_toughness_calculation_entry.py
simulator_v8_clean_core/tools/validate_p6_s2_s3_unit_spawn_birth_plan.py
simulator_v8_clean_core/tools/validate_p6_s4_s5_boundary_static.py
simulator_v8_clean_core/tools/validate_p6_architecture_boundary_refactor.py
```

同步迁移旧验证谓词：

```text
simulator_v8_clean_core/tools/validate_v0_231.py
simulator_v8_clean_core/tools/validate_v0_235.py
simulator_v8_clean_core/tools/validate_p5_s7_monster_custom_summon_binding.py
```

这些验证迁移不新增 runtime 规则，只把旧样例选择从 show_stance / dynamic-hash fallback 和 runtime 内容读取口径迁到显式 value_request / 一等出生模板 / blocked 口径。

## 聚合验证

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_architecture_boundary_refactor --output-dir /tmp/hsr_v8_p6_refactor_aggregate_probe
```

输出：

```text
v8 p6_architecture_boundary_refactor ok=True stages=4/4 ready_for_review=True
```

关键 summary：

```text
stage_ok:
  p6_s0=true
  p6_s1=true
  p6_s2_s3=true
  p6_s4_s5=true

inherited_s0_unresolved:
  violation_row_count=0
  blocking_rows=[]
  explicitly_deferred_rows=[]
  classification_counts:
    audit_only=21
    scenario_assembly_ok=4

p6_all_mechanisms_reimplemented=false
```

新增聚合边界检查：

```text
s1_no_raw_param_path_parsing=true
s2_s3_birth_template_projected_before_runtime=true
s2_s3_incomplete_birth_plan_blocks=true
s2_s3_incomplete_birth_plan_no_mutations=true
s2_s3_tampered_birth_plan_blocks=true
s2_s3_tampered_birth_plan_no_mutations=true
s2_s3_wave_level_source_backed=true
s0_no_p6_owned_unresolved=true
```

P6 聚合没有声明全机制复刻完成。

## 分阶段 evidence

S0 当前账本：

```text
v8 p6_s0_architecture_boundary_ledger ok=True rows=25 violations=0 questions_checked=5/5 classifications={'audit_only': 21, 'scenario_assembly_ok': 4}
```

S1 伤害 / 削韧计算入口：

```text
v8 p6_s1_damage_toughness_calculation_entry ok=True rows=5 classifications={'boundary_guard': 3, 'executable': 2}
```

S2/S3 出生单：

```text
v8 p6_s2_s3_unit_spawn_birth_plan ok=True rows=15 classifications={'boundary_guard': 11, 'executable': 4}
```

S4/S5 静态边界：

```text
v8 p6_s4_s5_boundary_static ok=True rows=6 classifications={'audit_only': 1, 'boundary_guard': 5}
```

## P1-P5 回归

全部串行、低优先级、输出 `/tmp`。

```text
compileall simulator_v8_clean_core simulator_v8_ui: passed

P1:
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True

P2:
v8 p2_status_system_complete validation ok=True
p2_status_substrate_complete=True
p2_all_status_sources_classified=True

P3:
v8 p3_summon_assistant_servant_complete validation_gate_ok=True p3_summon_foundation_closed=True p3_summon_phase_complete=True p3_summon_all_executable_complete=False p3_summon_sources_classified=True gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}

P4:
v8 p4_combatant_data_card_expansion validation_gate_ok=True p4_substrate_complete=True p4_all_executable_complete=False gap_counts={'admission_gap': 1333000, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 55, 'unclassified': 0, 'validation_gap': 0}

P5:
v8 p5_formula_dynamic_param_binding validation_gate_ok=True p5_substrate_complete=True p5_all_executable_complete=False gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
```

`p3_summon_all_executable_complete=false`、`p4_all_executable_complete=false`、`p5_all_executable_complete=false` 仍是已归因 backlog，不是当前底座失败。

## 剩余 backlog

P6 后仍未完成完整复刻：

- S4/S5 的 `RuleBook.character_dynamic_value_bindings_for_card()` 是过渡 accessor，systems 不再直接挖 evidence，但 accessor 仍从 `CharacterDataCardIR.source.evidence` 桥接动态绑定；后续需要一等投影。
- P3 inherited summon gaps 仍保留 `admission_gap=2123`、`source_gap_blocked=27`。
- P4 数据卡扩面仍保留 `admission_gap=1333000`、`source_gap_blocked=55`。
- P5 公式 / 动态值 / 参数绑定仍保留 `admission_gap=1492393`。
- break status 中存在 chance admission gap，例如部分 break status raw chance 超出当前 admission 范围；旧验证已改为记录 blocked，而不是把它误当 super-break runtime 失败。

## 验收结论

2026-07-10 验收线程复核通过：

- S0 当前 25 行均为 `audit_only` 或 `scenario_assembly_ok`，`violation_row_count=0`，显式延期白名单为空。
- S1 伤害 / 削韧计算入口不再解析 raw path；真实正例、缺入口负例、source audit 和 replay 均通过。
- S2/S3 出生模板已在 lowering 投影为一等 Canonical IR；runtime materializer 不读取 RuleBook 或内容卡内部结构。
- 缺失、不完整以及完整篡改的召唤怪、servant、波次出生单均 blocked、no mutation、state unchanged。
- 上一轮可用出生单注入不同单位的复现现已返回 `unit_spawn_plan_request_mismatch`，mutation 数为 0。
- 波次等级和属性倍率来自 StageConfig 与 HardLevelGroup；runtime 中不再存在固定 80 级。
- P6 聚合输出 `ok=true`、`stages=4/4`，并明确要求 `s0_no_p6_owned_unresolved=true`。
- 本线程重新串行运行 P1、P2、P3、P4、P5 聚合，全部按各自底座完成口径通过。

P6 架构边界回正完成验收。`p3_summon_all_executable_complete=false`、`p4_all_executable_complete=false`、`p5_all_executable_complete=false` 和 `p6_all_mechanisms_reimplemented=false` 仍表示已归因的后续扩面 backlog，不影响本阶段边界回正结论。
