# v8 P4-S8 Trace Eidolon Level Resource Hooks Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S8 行迹、星魂、等级提升、开局机制与角色资源槽位扩面。

目标产物：

- 输出 trace / eidolon / action level / startup listener / resource / build hook 分层矩阵。
- 用 `trace_node`、`mechanism_kind`、`eidolon rank`、`skill_add_level_list`、`skill_trigger_key`、`callback event`、`opcode`、`coverage_status`、`blocked_reason` 等结构化谓词分类。
- 对可执行的行迹静态属性和星魂技能等级提升提供 runtime assembly 样例和 source trace。
- 对未支持的行迹、星魂、startup listener、resource task 保留 admission gap，不在 scenario 或 runtime 中手写结果。
- 对光锥、遗器、套装等未来构筑入口只验证 hook / owner / boundary；缺构筑输入时不能产生装备规则 mutation。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s8_trace_eidolon_level_resource_hooks.py`
- `simulator_v8_clean_core/tools/validate_v0_267.py`
- `simulator_v8_clean_core/tools/validate_v0_270.py`
- `live_validation_reports/v8_p4_s8_trace_eidolon_level_resource_hooks_ready_for_review.md`

本阶段未修改：

- 未改 runtime / lowering / RuleBook / executor 语义。
- 未新增角色名、技能名、技能 ID、文件名、hash 特判到 core。
- 未在 scenario 里注入角色专属机制结果。
- 未在 runtime 中读取或解释光锥、遗器、套装规则。
- 未改 P4 第 22 节 checklist。
- 未新增 P4-S12 聚合脚本。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s8_current
```

主要文件：

```text
/tmp/hsr_v8_p4_s8_current/validation_summary_p4_s8_trace_eidolon_level_resource_hooks.json
/tmp/hsr_v8_p4_s8_current/p4_s8_trace_eidolon_level_resource_hooks_matrix.json
```

S8 主验证：

```text
ok=True
row_count=9
unclassified_count=0

classification_counts:
  admission_gap=4
  boundary_only=2
  executable=3

character_data_card_count=92
trace_node_count=5246
eidolon_slot_count=552
character_mechanism_slot_count=31865

gap_attribution_counts:
  admission_gap=4015
```

## Matrix 摘要

```text
action_level_ladder_matrix: executable, raw=6101, executable=6101, gap=0
trace_static_stat_assembly_runtime: executable, raw=1, executable=1, gap=0
eidolon_skill_level_assembly_runtime: executable, raw=1, executable=1, gap=0
trace_node_slot_matrix: admission_gap, raw=6359, executable=6278, gap=81
trace_startup_ability_boundary: admission_gap, raw=93, executable=12, gap=81
eidolon_slot_rank_matrix: admission_gap, raw=1104, executable=793, gap=311
startup_listener_resource_matrix: admission_gap, raw=15666, executable=12124, gap=3542
equipment_build_input_hook_boundary: boundary_only, raw=92, executable=0, gap=0
invalid_eidolon_level_boundary: boundary_only, raw=1, executable=0, gap=0
```

说明：

- `action_level_ladder_matrix` 证明 6101 个角色 action definition 的 level / trigger key 对 RuleBook 可见。
- `trace_static_stat_assembly_runtime` 通过数据卡 assembly 改变面板值，样例 source trace 来自 `AvatarSkillTreeConfig`，不是 scenario 手写结果。
- `eidolon_skill_level_assembly_runtime` 通过星魂 rank 前缀启用策略记录技能等级提升，样例 source trace 来自 `AvatarRankConfig`。
- `equipment_build_input_hook_boundary` 证明 92 张角色卡均有 `card_contract.equipment_boundary`，owner 为后续 `external_equipment_card`，缺构筑输入时不会产生装备/遗器规则 mutation。
- `invalid_eidolon_level_boundary` 证明非法星魂等级会被拒绝，不创建 state。

## Gap 归因

行迹：

```text
trace_node_coverage: executable=5246
trace_slot_coverage: executable=1032, blocked=81
blocked_reason:
  trace_ability_effect_not_admitted_v0_265=81
```

星魂：

```text
eidolon_slot_coverage: executable=552
mechanism_slot_coverage: executable=241, blocked=311
blocked_reason:
  eidolon_slot_has_no_runtime_effect_source=219
  eidolon_extra_effect_id_runtime_admission_pending=92
```

开局监听与资源：

```text
startup_event_counts:
  OnCreate=396
  OnEnterBattle=420
  OnStack=1586

startup_admission_counts:
  executable=1234
  blocked=1168

resource_task_coverage:
  executable=10890
  blocked=2374

resource_task_opcode_counts:
  SetDynamicValue=10263
  ModifySPNew=1915
  DefineDynamicValue=417
  SetDynamicValueByAddValue=312
  SetDynamicValueByCharacterCount=288
  ModifySP=69
```

主要 blocking dependency：

```text
status_callback_source_mode_not_admitted=970
status_callback_event_not_admitted:OnCreate=101
status_callback_event_not_admitted:OnEnterBattle=97
```

这些缺口是 S8 矩阵的一部分，后续 S11/S12 总账本必须继承，不能用 3 个 executable 行覆盖。

## 旧回归口径迁移

`validate_v0_267.py`：

- 旧逻辑要求示例角色星魂 effect slots 全部不能 fake runtime。
- 当前 IR 已有部分星魂机制槽进入 executable，继续要求“全部 blocked”会误报。
- 验证迁移为 `effect_slots_classified_without_fake_runtime`：可执行槽必须有真实 semantics 和 source path；不可执行槽必须有 blocked reason。
- 迁移后仍禁止星魂效果在 runtime 中伪造执行。

`validate_v0_270.py`：

- 旧逻辑要求示例角色 E6 终结技、flag、buff、真伤和生命周期完整 executable。
- 当前 source / lowering 仍存在，但 execution 分支被 admission 阻断，典型 blocker 包括 `target_expression_alias_mismatch:ParamEntity:ParamEntitySkillTargetEntityList`、`fixed_or_bound_dynamic_value_required`、`dynamic_hash_unbound:1659254037`、`event_source_missing:OnListenAfterAttack`。
- 验证迁移为双口径：若完整 executable，继续跑旧断言；若不可执行，必须分类为 `admission_gap`，并证明来源已 lowering、transition/source audit 通过、flag/buff/true damage 没有假 mutation。
- 迁移后输出 `eidolon_six_case.classification=admission_gap`，阻断原因保留到报告，不吞掉缺口。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s8_trace_eidolon_level_resource_hooks.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_v0_267.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_v0_270.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s8_trace_eidolon_level_resource_hooks --output-dir /tmp/hsr_v8_p4_s8_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_267 --output-dir /tmp/hsr_v8_v0_267_after_p4_s8
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_271 --output-dir /tmp/hsr_v8_v0_271_after_p4_s8
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_270 --output-dir /tmp/hsr_v8_v0_270_after_p4_s8
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_276 --output-dir /tmp/hsr_v8_v0_276_after_p4_s8
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_after_p4_s8
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s8_trace_eidolon_level_resource_hooks.py simulator_v8_clean_core/tools/validate_v0_267.py simulator_v8_clean_core/tools/validate_v0_270.py live_validation_reports/v8_p4_s8_trace_eidolon_level_resource_hooks_ready_for_review.md
```

结果：

- S8 主验证 `ok=True`。
- v0_267 `ok=True`，星魂 effect slots 按真实 executable/blocked 分类。
- v0_271 `ok=True`。
- v0_270 `ok=True`，E6 分支分类为 `admission_gap`，无假 flag/buff/true damage mutation。
- v0_276 `ok=True`。
- P1-8 BattleSetup `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S8 触达文件尾随空白检查无匹配。

## 当前进度口径

当前做到 P4-S8 ready_for_review：行迹静态属性、星魂技能等级提升、技能等级 ladder、构筑 hook、非法星魂等级边界已有可验收证据；行迹/星魂/startup/resource 的未支持部分保留 admission gap 并有 blocked reason。

距离最小可用战斗纵切：角色卡 assembly、星魂等级、行迹面板、BattleSetup、状态/死亡触发相关旧回归未退化。

距离完整复刻：行迹能力 hook、星魂 extra effect、OnCreate / OnEnterBattle startup listener、动态值与资源任务、示例 E6 完整链路仍有 admission gap，后续阶段不能把 S8 标成全正例完成。
