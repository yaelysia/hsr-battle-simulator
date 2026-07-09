# v8 P4-S9 Data Card Mutation Source Linkage Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S9 数据卡状态、资源、伤害、击杀归因联动。

目标产物：

- 输出 data-card mutation/source linkage matrix，覆盖 direct、DoT、hp loss、break、super-break、true damage、状态施加/刷新/移除、listener action delay、queue/extra action、resource mutation、击杀归因和生命周期负例。
- 每个 executable mutation row 必须有 settlement、source audit 或明确 boundary 说明、replay/transition 证据。
- removed / defeated / untargetable 负例必须 blocked 或 process-only，不能产生对应 mutation。
- servant / summon source frame 只能作为当前边界证据；servant damage formula 未 admitted 时不能宣称全正例。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s9_data_card_mutation_source_linkage.py`
- `live_validation_reports/v8_p4_s9_data_card_mutation_source_linkage_ready_for_review.md`

本阶段未修改：

- 未改 runtime / lowering / RuleBook / executor 语义。
- 未新增角色名、怪物名、技能 ID、文件名、hash 特判到 core。
- 未绕过状态系统、伤害系统、资源系统或 MutationReducer。
- 未从日志反推 settlement。
- 未改 P4 第 22 节 checklist。
- 未新增 P4-S12 聚合脚本。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s9_current
```

主要文件：

```text
/tmp/hsr_v8_p4_s9_current/validation_summary_p4_s9_data_card_mutation_source_linkage.json
/tmp/hsr_v8_p4_s9_current/p4_s9_data_card_mutation_source_linkage_matrix.json
```

S9 主验证：

```text
ok=True
row_count=11
unclassified_count=0

classification_counts:
  boundary_only=2
  executable=8
  source_gap_blocked=1

gap_attribution_counts:
  admission_gap=1
  source_gap_blocked=1
```

Mutation source 覆盖：

```text
break_system=3
combat_executor.timeline=9
damage_system=8
effect_system=5
status_callback_system=1
status_system=30
toughness_system=2
```

关键 settlement record 覆盖：

```text
damage=2
hp_loss=1
resource_delta=1
break_lifecycle=3
break_event=1
super_break_damage=1
status_apply_success=26
status_lifecycle=4
action_delay=1
damage_source_skipped=3
unit_lifecycle=4
```

## Matrix 摘要

```text
data_card_direct_damage_resource_linkage: executable, raw=1, executable=1, gap=0
data_card_break_linkage: executable, raw=1, executable=1, gap=0
data_card_super_break_linkage: executable, raw=1, executable=1, gap=0
data_card_hp_loss_linkage: executable, raw=1, executable=1, gap=0
data_card_status_apply_linkage: executable, raw=1, executable=1, gap=0
status_refresh_replace_linkage: executable, raw=2, executable=2, gap=0
status_remove_linkage: executable, raw=2, executable=2, gap=0
status_damage_dot_break_true_linkage: executable, raw=6, executable=6, gap=0
listener_queue_action_delay_resource_linkage: source_gap_blocked, raw=3, executable=2, gap=1
kill_attribution_source_frame_linkage: boundary_only, raw=2, executable=0, gap=2
removed_defeated_untargetable_negative: boundary_only, raw=3, executable=0, gap=3
```

说明：

- direct damage 与 `ModifySPNew` resource mutation 都有 settlement、source audit 和 replay。resource 正例来自真实 effect，不要求选中的 direct damage action 自身同时有资源变化。
- break / super-break / hp-loss 都通过现有通用系统执行；hp-loss 保留 `hp_loss` settlement，不走 direct multiplier ledger。
- 状态施加来自 servant data-card action；刷新/替换/移除来自 P2 通用状态系统正例。
- 状态伤害覆盖 ordinary DoT、break DoT、true damage、multi DoT、dead target skip、missing status blocked。
- listener 行中 action delay 和 resource mutation 为 executable；extra-turn queue 当前为 `source_gap_blocked`。

## Gap 归因

`listener_queue_action_delay_resource_linkage`：

```text
classification=source_gap_blocked
blocked item=automatic extra-turn queue intent
blocking_dependency=no executable mainline Avatar TurnInsertAction PrepareAbilityName extra-turn intent found
```

这不是 queue/runtime 假执行失败，而是当前结构化选择下没有完整可执行的 mainline Avatar extra-turn intent 来源。S9 保留 source gap，不合成正例。

`kill_attribution_source_frame_linkage`：

```text
classification=boundary_only
servant_boundary_classification=engine_source_frame_boundary_not_servant_damage_formula_executable
servant kill_credit_owner_id=ally:servant_owner
servant kill_credit_source_kind=summon_damage_source_frame_boundary
gap_attribution admission_gap=1
```

说明：主 action 击杀归因已有 source-audited transition；servant owner/source-frame 目前只证明 source-frame 边界正确，不宣称 servant damage formula 全正例。

## 负例覆盖

`removed_defeated_untargetable_negative`：

```text
removed summon damage blocked reason=damage_source_target_removed
defeated status damage target skipped process-only
untargetable servant blocked reason=summon_runtime_entity_not_targetable
all summon target negative state unchanged=true
```

负例均不产生对应 damage/target mutation。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s9_data_card_mutation_source_linkage.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s9_data_card_mutation_source_linkage --output-dir /tmp/hsr_v8_p4_s9_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_after_p4_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_after_p4_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_p4_s9
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s9_data_card_mutation_source_linkage.py live_validation_reports/v8_p4_s9_data_card_mutation_source_linkage_ready_for_review.md
```

结果：

- S9 主验证 `ok=True`。
- P2 聚合 `ok=True`，`p2_status_substrate_complete=True`，`p2_all_status_sources_classified=True`。
- P3 聚合 `validation_gate_ok=True`，`p3_summon_phase_complete=True`，`p3_summon_all_executable_complete=False`；P3 inherited gaps 保留。
- P1-9 聚合 `ok=True`，`phase1_minimum_battle_slice=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S9 触达文件尾随空白检查无匹配。

## 当前进度口径

当前做到 P4-S9 ready_for_review：数据卡触发的主要 mutation 类别已和通用状态、伤害、资源、break、super-break、queue/action-delay、source audit、replay 证据建立联动矩阵。

距离最小可用战斗纵切：P1/P2/P3 聚合回归均通过，S9 没有破坏既有 action/damage/status/summon/source audit 底座。

距离完整复刻：mainline Avatar extra-turn intent 正例仍为 source gap；servant damage formula 与 servant full kill attribution 仍是 boundary/admission gap，不能在 S11/S12 总账本中被 executable 行覆盖。
