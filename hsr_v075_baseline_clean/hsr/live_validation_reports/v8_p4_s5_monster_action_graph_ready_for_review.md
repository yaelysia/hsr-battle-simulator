# v8 P4-S5 Monster Action Graph Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S5 怪物技能 action graph 覆盖扩面。

目标产物：

- 输出 monster action graph matrix，覆盖 action definition、ability binding、event/phase/task/effect、target、damage/toughness、status、dynamic、queue/action delay、ILBattle 和 blocked family 归因。
- 用多个结构化谓词选出的怪物技能 runtime 正例验证 fixed sequence candidate、single damage、aoe damage、attached status effect。
- 保持敌方动作只产出 candidate，由外部选择；不引入敌方 AI 自动选招。
- 对不能执行的怪物技能 family 记录具体 admission gap，不用少量正例覆盖全域。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s5_monster_action_graph.py`
- `live_validation_reports/v8_p4_s5_monster_action_graph_ready_for_review.md`

本阶段未修改：

- 未改 runtime / lowering / RuleBook / executor 语义。
- 未新增怪物名、MonsterID、技能 ID 特判。
- 未让 core 自动选择敌方动作或目标。
- 未改 P4 第 22 节 checklist。
- 未新增 P4-S12 聚合脚本。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s5_monster_action_graph
```

主要文件：

```text
/tmp/hsr_v8_p4_s5_monster_action_graph/validation_summary_p4_s5_monster_action_graph.json
/tmp/hsr_v8_p4_s5_monster_action_graph/p4_s5_monster_action_graph_matrix.json
```

S5 主验证：

```text
ok=True
row_count=11
unclassified_count=0

classification_counts:
  admission_gap=6
  executable=5

monster_action_definition_count=3575
monster_action_graph_record_count=3575

gap_attribution_counts:
  admission_gap=69450
```

## Matrix 摘要

```text
monster_action_definition_sources: executable, raw=3575, executable=3575
monster_fixed_sequence_candidate_source_trace: executable
monster_runtime_single_damage: executable
monster_runtime_aoe_damage: executable
monster_runtime_attached_status_effect: executable
monster_action_binding_event_graph: admission_gap, admission_gap=970
monster_damage_toughness_sources: admission_gap, admission_gap=5803
monster_effect_opcode_backlog: admission_gap, admission_gap=2616
monster_status_resource_queue_delay_sources: admission_gap, admission_gap=1309
ilbattle_monster_action_graph: admission_gap, admission_gap=330
monster_blocked_family_attribution: admission_gap, admission_gap=58422
```

样本 ID 是验证输出，不是选择条件。runtime 样例均由 `MonsterDataCardIR.action_sequence`、`ActionDefinitionIR`、`ActionEventIR`、target mode、damage kind、effect opcode、candidate availability、replay/source audit 等结构化谓词选择。

## Runtime 正例

```text
single_damage:
  action=monster_skill:100204001
  target_mode=single
  damage_mutation_count=1
  toughness_mutation_count=3
  mutation_count=8
  replay/source_audit ok

aoe_damage:
  action=monster_skill:100201101
  target_mode=aoe
  selected_targets=3
  damage_mutation_count=3
  toughness_mutation_count=3
  mutation_count=12
  replay/source_audit ok

attached_status_effect:
  action=monster_skill:101202002
  target_mode=self_or_team
  status_mutation_count=2
  mutation_count=9
  replay/source_audit ok
```

这三个样例只是证明当前通用链路有正例，不代表全怪物技能完成。

## Gap 归因

关键 effect opcode 来源计数：

```text
DamageByAttackProperty=2912
AddModifier=5656
RemoveModifier=2884
SetDynamicValue=1219
DefineDynamicValue=801
SummonMonster=775
Retarget=2348
```

blocked family 分类：

```text
action_definition_missing=58
action_graph_admission_gap=1115
formula_or_dynamic_gap=1649
profile_or_card_gap=212
status_source_gap=25998
target_gap=4130
other_admission_gap=25260
```

解释：

- `ActionDefinitionIR` 来源总数 3575 且 RuleBook 可见，包含 `MonsterSkillConfig`、`MonsterSkillUniqueConfig`、`ILBattleMonsterSkill`。
- 但 action binding / event graph 仍有 blocked：binding blocked 435，event blocked 535，合计 gap 970。
- ILBattle monster action definitions 存在 165 个，但 binding/event 当前仍没有 executable 纵切，保留 admission gap。
- damage/toughness source 有正例，但同域仍有 5803 个未 executable source，不能覆盖。
- queue/action delay 的 monster source 已盘点，但当前未纳入本阶段可执行正例，保留 gap。
- SummonMonster / SetDynamicValue / dynamic/custom/profile/card 相关缺口不在 S5 硬补，后续归 S6/S10 或 dynamic/profile admission 收敛。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s5_monster_action_graph.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s5_monster_action_graph --output-dir /tmp/hsr_v8_p4_s5_monster_action_graph
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_280 --output-dir /tmp/hsr_v8_v0_280_after_p4_s5
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_p4_s5
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_v0_284_after_p4_s5
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution --output-dir /tmp/hsr_v8_p3_s6_after_p4_s5
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
if rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s5_monster_action_graph.py; then exit 1; fi
```

结果：

- S5 主验证 `ok=True`。
- v0_280 `ok=True`。
- v0_283 `ok=True`。
- v0_284 `ok=True`。
- P3-S6 `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S5 新脚本尾随空白检查通过。

## 当前进度口径

当前做到 P4-S5 ready_for_review：怪物 action graph 来源、runtime 正例和 blocked family 总账已形成矩阵证据；本阶段没有改运行时语义。

距离最小可用战斗纵切：P1/P3 相关怪物动作与召唤怪执行回归未退化。

距离完整复刻：仍缺 S6 怪物被动/监听/阶段/波次/召唤交叉边界，S7/S8 角色机制，S9 状态/资源/伤害联动，S10 P3 backlog 深度回收，以及 S12 最终聚合。
