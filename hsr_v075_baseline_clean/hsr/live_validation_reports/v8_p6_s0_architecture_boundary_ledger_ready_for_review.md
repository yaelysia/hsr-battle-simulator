# v8 P6-S0 架构越界总账本 ready_for_review

## 阶段边界

本阶段只建立 P6 架构边界总账本，不修改 runtime 行为，不搬迁伤害、削韧、召唤、波次或场景构建逻辑，不修改 `P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md` checklist。

脚本：

```text
simulator_v8_clean_core/tools/validate_p6_s0_architecture_boundary_ledger.py
```

脚本只做当前源码证据扫描和结构化矩阵输出，不构建 TBGD lowering，不构建 RuleBook，不写完整 IR、RuleBook 或 transition dump。

## 当前验证输出

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p6_s0_architecture_boundary_ledger --output-dir /tmp/hsr_v8_p6_s0_current
```

输出：

```text
v8 p6_s0_architecture_boundary_ledger ok=True rows=25 violations=0 questions_checked=5/5 classifications={'audit_only': 21, 'scenario_assembly_ok': 4}
```

产物：

```text
/tmp/hsr_v8_p6_s0_current/validation_summary_p6_s0_architecture_boundary_ledger.json
/tmp/hsr_v8_p6_s0_current/p6_s0_architecture_boundary_ledger_matrix.json
```

## Summary

```text
schema_version=p6_s0_architecture_boundary_ledger_matrix_v4
row_count=25
questions_checked=5/5
classification_counts:
  audit_only=21
  scenario_assembly_ok=4
violation_row_count=0
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
required_file_count=12
covered_file_count=11
excluded_file_count=1
uncovered_file_count=0
```

新增覆盖了此前漏项和后续回正新增入口：

```text
simulator_v8_clean_core/rules/rulebook.py
simulator_v8_clean_core/systems/unit_spawn.py
```

明确排除：

```text
simulator_v8_clean_core/systems/unit_lifecycle.py
reason=UnitLifecycleSystem receives an already-built UnitState and creates lifecycle mutations; it does not read content cards or assemble combatant rules.
```

## 当前剩余行

当前 S0 账本已经随 S1-S5 回正更新为“当前代码状态”：

- 伤害 / 削韧 value resolution 已改为显式 `value_request` 入口；原 trace mining / show_stance fallback 行已转为 `audit_only` 当前证据。
- summon / servant / wave 来源在 lowering 阶段投影为一等 `UnitBirthTemplateIR`；runtime `UnitSpawnSystem` 只物化绑定规格，不读取 RuleBook、内容卡、servant 定义或波次定义。
- apply 阶段只消费与外层 `UnitSpawnRequest` 严格绑定的 `UnitSpawnPlan`；缺失、不完整或被篡改的出生单均 blocked、零 mutation、state unchanged。
- 波次等级和 HardLevelGroup 属性倍率来自结构化 Stage / HardLevelGroup 来源，不再存在 runtime `level=80` 默认值。
- `systems/dynamic_values.py` 不再直接读取 character card source evidence，改为调用 RuleBook accessor。
- `systems/action_availability.py`、`core/source_audit.py`、`scenarios/identity.py` 明确归类为 query / audit / scenario validation 路径。

当前 `content_assembly_in_runtime=0`。聚合验证会把所有非显式延期的 S0 违规行作为失败；当前显式延期白名单为空。

## 结论

P6-S0 当前 evidence 已刷新为 `ready_for_review`。该报告不是验收结论，也不修改 checklist；是否勾选仍由验收线程复核脚本、矩阵、源码证据和验证输出后决定。
