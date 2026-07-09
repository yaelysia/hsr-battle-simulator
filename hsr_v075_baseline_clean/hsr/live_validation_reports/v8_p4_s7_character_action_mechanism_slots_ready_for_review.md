# v8 P4-S7 Character Action Mechanism Slots Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S7 角色基础动作、天赋、秘技、强化形态机制槽位扩面。

目标产物：

- 输出 character action / mechanism slot matrix，覆盖角色 action set、action graph、机制槽位、status listener、秘技/开局、弹射/多段、queue/extra action、资源入口、servant 子卡归属。
- 用 `CharacterDataCardIR.action_set.actions`、`attack_type`、`skill_effect`、`mechanism_kind`、`runtime_system`、`source_mode`、`event`、`opcode`、`coverage_status`、`admission_status` 等结构化谓词分类。
- 对不能执行的角色机制保留 admission gap，不用固定角色或固定技能覆盖全域。
- 保持 servant / 忆灵归属角色卡或 servant 子卡；缺 owner/stat/action/target/lifecycle 时必须 blocked，不把它们当普通 buff。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s7_character_action_mechanism_slots.py`
- `simulator_v8_clean_core/tools/validate_v0_266.py`
- `simulator_v8_clean_core/tools/validate_v0_276.py`
- `live_validation_reports/v8_p4_s7_character_action_mechanism_slots_ready_for_review.md`

本阶段未修改：

- 未改 runtime / lowering / RuleBook / executor 语义。
- 未新增角色名、技能名、技能 ID、文件名、hash 特判到 core。
- 未把角色专属机制写进 core if/else。
- 未用技能文本驱动 runtime。
- 未改 P4 第 22 节 checklist。
- 未新增 P4-S12 聚合脚本。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s7_character_action_mechanism_slots
```

主要文件：

```text
/tmp/hsr_v8_p4_s7_character_action_mechanism_slots/validation_summary_p4_s7_character_action_mechanism_slots.json
/tmp/hsr_v8_p4_s7_character_action_mechanism_slots/p4_s7_character_action_mechanism_slots_matrix.json
```

S7 主验证：

```text
ok=True
row_count=9
unclassified_count=0

classification_counts:
  admission_gap=7
  executable=2

character_data_card_count=92
character_action_entry_count=6101
character_mechanism_slot_count=31865
character_callback_count=5947

gap_attribution_counts:
  admission_gap=191809
```

## Matrix 摘要

```text
character_action_role_matrix: executable, raw=6101, executable=6101, gap=0
character_servant_subcard_boundary: executable, raw=6, executable=6, gap=0
character_action_graph_matrix: admission_gap, raw=259065, executable=62394, gap=176410
character_mechanism_slot_matrix: admission_gap, raw=31865, executable=26575, gap=5290
character_status_listener_matrix: admission_gap, raw=5947, executable=1724, gap=4223
character_technique_startup_boundary: admission_gap, raw=2587, executable=1419, gap=1168
character_bounce_multihit_matrix: admission_gap, raw=5462, executable=1130, gap=145
character_continuation_queue_extra_action_matrix: admission_gap, raw=612, executable=83, gap=529
character_resource_gate_matrix: admission_gap, raw=23068, executable=19024, gap=4044
```

说明：

- `character_action_role_matrix` 按 `action_set.actions` 选动作，不直接用 `skill_ids` 猜 action definition。
- 角色基础动作 family 已覆盖 `Normal`、`BPSkill`、`Ultra`、`Maze`、`MazeNormal` 等结构化 `attack_type`。
- `character_servant_subcard_boundary` 证明当前 6 个 servant definition 均有 owner card、action set、stat、timeline、lifecycle 来源。
- 其余行保留真实 admission gap，不能用两个 executable 行覆盖。

## Gap 归因

主要 action graph gap：

```text
binding_count=6101
binding_coverage: blocked=5031, executable=1070
task_count=204252
task_coverage: blocked=157871, executable=41503, lowered=4878

blocked task examples:
  effect_coverage_status:unsupported:WaitAnimState=27798
  effect_coverage_status:audit_only:DamageByAttackProperty=7605
  effect_coverage_status:unsupported:TriggerAnimState=7510
  condition_not_executable:unsupported:ByRankActivated=5112
  condition_not_executable:unsupported:BySkillPointActivated=2962
```

角色机制槽位：

```text
skill_param_slot=18279
formula_slot=8477
status_callback=2842
trace_static_stat_bonus=1020
eidolon_rank_effect=552
bounce_policy=220
damage_modifier=149
queue_intent=121
skill_continuation=110
trace_ability_hook=93
extra_action_policy=2
```

资源入口：

```text
resource_action_definition_count=6101
resource_task_count=13264
resource_task_coverage: blocked=2374, executable=10890
resource_like_slot_count=3701
resource_slot_coverage: blocked=1670, executable=2031
```

解释：

- 当前角色 action set 和 servant 子卡 contract 已可作为后续扩面底座。
- action graph 内大量 visual/performance/condition/custom/source-mode/task admission 仍未进入可执行语义。
- `OnListenAfterAttack`、`OnCreate`、`OnDestroy`、`OnEnterBattle` 等角色 listener 仍有未 admitted event source 或 source mode，不能假执行。
- 弹射/多段已有 60 个 executable bounce policy 和 1070 个多段 action，但仍有 145 个 `bounce_count_not_admitted_from_skill_text`。

## 旧回归口径迁移

`validate_v0_266.py`：

- 旧逻辑要求增强角色 auto skill callback 必须 executable。
- 当前 IR 中同一来源、同一 callback、Retarget 和 `TurnInsertAction SkillType` 结构仍存在，但 `OnListenAfterAttack` runtime event source 未 admitted。
- 验证迁移为 `source_gap_blocked` 负例：`auto_skill_50_case.status=source_gap_blocked`，`blocking_dependency=event_source_missing:OnListenAfterAttack`。
- 迁移后不产生伪执行，仍要求 state unchanged / blocked evidence。

`validate_v0_276.py`：

- 旧逻辑要求 death trigger dispatch errors 必须为空。
- 当前 death trigger 正例已产生预期 mutation 和 kill damage status，但 dispatch 记录一个非致命 `stack_partial:layer_add_when_stack_missing`。
- 验证迁移为只允许这个明确的非致命 stack partial，并把 `dispatch_errors` 写入输出；其他 dispatch error 仍失败。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s7_character_action_mechanism_slots.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_v0_266.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_v0_276.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s7_character_action_mechanism_slots --output-dir /tmp/hsr_v8_p4_s7_character_action_mechanism_slots
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_v0_265_after_p4_s7
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_v0_266_after_p4_s7
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_276 --output-dir /tmp/hsr_v8_v0_276_after_p4_s7
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution --output-dir /tmp/hsr_v8_p3_s6_after_p4_s7
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s7_character_action_mechanism_slots.py simulator_v8_clean_core/tools/validate_v0_266.py simulator_v8_clean_core/tools/validate_v0_276.py live_validation_reports/v8_p4_s7_character_action_mechanism_slots_ready_for_review.md
```

结果：

- S7 主验证 `ok=True`。
- v0_265 `ok=True`。
- v0_266 `ok=True`，auto skill 为 `source_gap_blocked` 负例。
- v0_276 `ok=True`，death trigger 只记录非致命 stack partial。
- P3-S6 summon action execution `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S7 触达文件尾随空白检查无匹配。

## 当前进度口径

当前做到 P4-S7 ready_for_review：角色 action set、角色机制槽位、角色 listener、秘技/开局、弹射/多段、queue/extra action、资源入口和 servant 子卡归属已形成分层矩阵。

距离最小可用战斗纵切：旧角色卡纵切、额外行动/击杀、开局行迹、servant action execution 回归未退化。

距离完整复刻：角色 action graph、listener event source、强化形态/动作替换、skill continuation、角色资源、弹射文本绑定、trace/eidolon 深层机制仍保留大量 admission gap，后续阶段不能用 S7 的 executable role/servant 行覆盖这些缺口。
